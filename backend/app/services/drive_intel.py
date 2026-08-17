from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone

from ..config import settings
from .google_auth import get_user_credentials


def drive_source_id(drive_file_id: str) -> str:
    """Stable UUID for a Drive file, for UUID-typed source_record_id columns.

    Drive ids are opaque Google strings, not UUIDs, and Postgres rejects them
    with 22P02. uuid5 keeps the dedupe property that matters: the same file
    always maps to the same id, so a document is queued for review once.
    """
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"kora:drive:{drive_file_id}"))


_FILE_TYPE_MAP = {
    "application/vnd.google-apps.document": "google_doc",
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/plain": "txt",
    "text/vtt": "vtt",
    "image/jpeg": "image",
    "image/png": "image",
    "application/vnd.google-apps.spreadsheet": "spreadsheet",
}

# Drive v3 returns My Drive only unless these are set, so a Workspace user whose
# watched folder or Meet transcripts live in a **shared drive** got an empty scan
# and no error to explain it — the same silent-nothing failure as D-017.
#
# Two constants because the parameters differ per method:
#   files.list      → both flags
#   files.get       → supportsAllDrives only (includeItemsFromAllDrives is a
#                     list-only parameter; passing it raises TypeError)
#   files.export    → takes neither, and needs neither
ALL_DRIVES_LIST = {"supportsAllDrives": True, "includeItemsFromAllDrives": True}
ALL_DRIVES_GET = {"supportsAllDrives": True}


def _db():
    from supabase import create_client

    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)


_MIN_BODY_NAME_LEN = 4


def _normalize(text: str) -> str:
    """Lowercase and reduce every run of non-alphanumerics to a single space.

    "Northwind_Brief-v2.docx" becomes " northwind brief v2 docx ". The padding
    spaces let `_mentions` test whole-token containment without a regex, and
    normalising separators is what makes `_` and `-` behave as word breaks.
    """
    return " " + re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip() + " "


def _mentions(haystack: str, name: str) -> bool:
    """Whole-token containment — `haystack` must already be `_normalize`d."""
    needle = _normalize(name)
    return len(needle) > 2 and needle in haystack


def _resolve_client_id(user_id: str, name: str = "", text: str = "") -> str | None:
    """Best-effort: link a Drive file to a Butler client. Returns an id or None.

    Matching is whole-token rather than substring, so a client called "Apex" is
    matched by the word "apex" and no longer by "apexon-retro.docx". Ambiguity
    resolves conservatively: when the body names two clients we return None
    instead of taking whichever came first out of `list_clients`. A wrong tag is
    worse than no tag — it files one client's document on another's page, and
    from there into that client's recall scope.
    """
    try:
        from .. import store

        clients = store.list_clients(user_id)
    except Exception:
        return None

    fname = _normalize(name)
    body = _normalize((text or "")[:4000])

    # Strongest signal: the client's name in the file name. Two clients can both
    # match ("Acme" and "Acme Digital" for acme-digital-msa.pdf); the longer name
    # is the more specific one, so it wins.
    by_name = [c for c in clients if _mentions(fname, c.name or "")]
    if by_name:
        return max(by_name, key=lambda c: len((c.name or "").strip())).id

    # Next: an email address in the body. It identifies exactly one client, so a
    # single hit is trustworthy even in a document that mentions several names.
    by_email = [c for c in clients if any(e and _mentions(body, e) for e in [c.email, *(getattr(c, "contact_emails", None) or [])])]
    if by_email:
        return by_email[0].id if len(by_email) == 1 else None

    # Weakest: the client's name in the body. Short names throw too many false
    # positives to be worth reading, and a document naming two clients is
    # genuinely ambiguous — "similar to the Northwind build" inside Acme's brief
    # must not file it under Northwind.
    by_body = [c for c in clients if len((c.name or "").strip()) >= _MIN_BODY_NAME_LEN and _mentions(body, c.name or "")]
    return by_body[0].id if len(by_body) == 1 else None


def sync_drive_intel(user_id: str) -> None:
    """Scan the user's Kora folder + Meet transcripts; route each file.

    Called daily by the butler sync worker. Silently no-ops when not connected.
    """
    if not settings.SUPABASE_URL:
        return

    creds = get_user_credentials(user_id)
    if not creds:
        return

    from googleapiclient.discovery import build

    service = build("drive", "v3", credentials=creds)
    db = _db()

    conn_rows = db.table("google_connections").select("kora_folder_id").eq("user_id", user_id).single().execute().data
    kora_folder_id = (conn_rows or {}).get("kora_folder_id")

    files_to_process: list[dict] = []

    if kora_folder_id:
        files_to_process.extend(_list_folder_files(service, kora_folder_id))

    files_to_process.extend(_find_meet_transcripts(service))

    new_files = _filter_unprocessed(user_id, files_to_process, db)
    for file_meta in new_files:
        try:
            _route_file(user_id, file_meta, service, db)
        except Exception as exc:
            print(f"[drive-intel] failed for {file_meta.get('name')}: {exc}")


def download_drive_file_text(user_id: str, file_id: str, mime_type: str = "") -> str:
    """Download a Drive file and return its text. Google Docs are exported to
    plain text; PDF/DOCX/txt are fetched and run through the document extractor.
    Raises ValueError if Google isn't connected. Used by the contract-review
    approval executor."""
    creds = get_user_credentials(user_id)
    if not creds:
        raise ValueError("Google account not connected")

    from googleapiclient.discovery import build

    service = build("drive", "v3", credentials=creds)

    if mime_type == "application/vnd.google-apps.document":
        content = service.files().export(fileId=file_id, mimeType="text/plain").execute()
        return content.decode("utf-8", errors="ignore") if isinstance(content, bytes) else str(content)

    raw = service.files().get_media(fileId=file_id, **ALL_DRIVES_GET).execute()
    if not isinstance(raw, bytes):
        return str(raw)
    # Resolve a filename for extension-based extraction.
    try:
        meta = service.files().get(fileId=file_id, fields="name", **ALL_DRIVES_GET).execute()
        name = meta.get("name", "document")
    except Exception:
        name = "document"
    from ..utils.document_text import extract_text

    return extract_text(name, mime_type or None, raw)


_FOLDER_MIME = "application/vnd.google-apps.folder"
_MAX_FOLDER_FILES = 300
_MAX_FOLDER_DEPTH = 3


def _list_folder_files(service, folder_id: str) -> list:
    """Every file under the watched folder, subfolders included.

    Was one non-recursive page of 50, which failed two ways: a `Kora/Contracts/`
    layout ingested nothing at all, and past 50 files the rest was dropped
    silently — and since Drive's default ordering isn't newest-first, it wasn't
    even "the 50 most recent". Depth and total stay capped so one enormous
    folder can't stall the daily sync for every other user.
    """
    files: list[dict] = []
    seen: set[str] = set()
    frontier: list[tuple[str, int]] = [(folder_id, 0)]

    while frontier and len(files) < _MAX_FOLDER_FILES:
        current, depth = frontier.pop(0)
        if current in seen:
            continue  # Drive lets one folder sit under several parents.
        seen.add(current)

        page_token = None
        while len(files) < _MAX_FOLDER_FILES:
            result = (
                service.files()
                .list(
                    q=f"'{current}' in parents and trashed = false",
                    fields="nextPageToken, files(id, name, mimeType, modifiedTime, size)",
                    pageSize=100,
                    pageToken=page_token,
                    **ALL_DRIVES_LIST,
                )
                .execute()
            )
            for f in result.get("files", []):
                if f.get("mimeType") == _FOLDER_MIME:
                    if depth < _MAX_FOLDER_DEPTH:
                        frontier.append((f["id"], depth + 1))
                    continue
                files.append(f)
                if len(files) >= _MAX_FOLDER_FILES:
                    break
            page_token = result.get("nextPageToken")
            if not page_token:
                break

    if len(files) >= _MAX_FOLDER_FILES:
        # Say so rather than let a truncated scan read as a complete one.
        print(f"[drive-intel] folder scan hit the {_MAX_FOLDER_FILES}-file cap, some files were not read")
    return files


def _find_meet_transcripts(service) -> list:
    thirty_days_ago = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S")
    query = f"(name contains 'transcript' or name contains 'Transcript') " f"and modifiedTime > '{thirty_days_ago}' " f"and trashed = false"
    result = (
        service.files()
        .list(
            q=query,
            fields="files(id, name, mimeType, modifiedTime)",
            pageSize=20,
            **ALL_DRIVES_LIST,
        )
        .execute()
    )
    return result.get("files", [])


def _filter_unprocessed(user_id: str, files: list, db) -> list:
    if not files:
        return []
    file_ids = [f["id"] for f in files]
    cached = (
        db.table("drive_doc_cache")
        .select("drive_file_id, processed_at, drive_modified_time")
        .eq("user_id", user_id)
        .in_("drive_file_id", file_ids)
        .execute()
        .data
    )
    cached_map = {c["drive_file_id"]: c for c in cached}

    new_files = []
    for f in files:
        fid = f["id"]
        if fid not in cached_map:
            new_files.append(f)
            continue
        cached_item = cached_map[fid]
        if f.get("modifiedTime") != cached_item.get("drive_modified_time"):
            new_files.append(f)
    return new_files


def _route_file(user_id: str, file_meta: dict, service, db) -> None:
    """Classify and route one Drive file to the appropriate processor."""
    mime = file_meta.get("mimeType", "")
    name = (file_meta.get("name") or "").lower()
    file_type = _FILE_TYPE_MAP.get(mime, "other")

    # Read the document before deciding what it is. Classifying on the filename
    # alone sent anything without a keyword to "other", which the router ignores.
    # Extraction is best-effort: an unreadable file still gets cached by name.
    text = ""
    if file_type in ("google_doc", "pdf", "docx", "txt", "vtt"):
        try:
            text = download_drive_file_text(user_id, file_meta["id"], mime)
        except Exception as exc:
            print(f"[drive-intel] text extraction failed for {file_meta.get('name')}: {exc}")

    doc_type = _classify_doc_type(name, file_type, mime, text)
    # Log the outcome: a silent extraction failure and a genuinely unclassifiable
    # document both end as doc_type="other", and without this there is no way to
    # tell them apart from the outside.
    print(f"[drive-intel] {file_meta.get('name')}: type={file_type} extracted={len(text)} chars -> doc_type={doc_type}")

    # Mark as seen in the cache immediately (avoids re-processing on next run).
    # The body is a stronger client signal than the file name, so pass both.
    client_id = _resolve_client_id(user_id, file_meta.get("name", ""), text)
    db.table("drive_doc_cache").upsert(
        {
            "user_id": user_id,
            "drive_file_id": file_meta["id"],
            "file_name": file_meta.get("name"),
            "mime_type": mime,
            "doc_type": doc_type,
            "client_id": client_id,
            "drive_modified_time": file_meta.get("modifiedTime"),
            "processed_at": datetime.now(timezone.utc).isoformat(),
        },
        on_conflict="user_id,drive_file_id",
    ).execute()

    if doc_type == "transcript" or _is_transcript_name(name):
        _handle_transcript(user_id, file_meta, service, db)
    elif doc_type in ("contract", "invoice", "receipt"):
        _queue_document_review(user_id, file_meta, doc_type, db)
    elif doc_type in ("brief", "scope", "proposal"):
        # Previously gated on file_type == "google_doc", so a .docx brief was
        # classified and then silently dropped. document_text.extract_text
        # handles docx/pdf/txt, so there is no reason to restrict it.
        _save_as_client_note(user_id, file_meta, service, db)
    # Spreadsheets and other types: logged in cache, no action taken


_DOC_TYPE_KEYWORDS = (
    ("transcript", ("transcript", "recording", "meeting notes")),
    ("contract", ("contract", "agreement", "nda", "sow", "statement of work")),
    ("invoice", ("invoice", "inv-", "inv ")),
    ("receipt", ("receipt", "payment")),
    ("brief", ("brief", "scope", "proposal", "rfp", "rfi")),
)


def _classify_doc_type(name: str, file_type: str, mime: str, text: str = "") -> str:
    """Classify by filename first, then by the document's own opening text.

    Filename remains the strongest signal — people do name files well, and it is
    free. But classifying on the name ALONE meant any document not happening to
    contain a keyword became "other", for which the router takes no action. A
    real file called `DQ_Implimentation_Usecase.docx` was ingested and produced
    nothing at all.

    `text` is the extracted body; only its opening is inspected, which is where
    document types announce themselves ("MASTER SERVICES AGREEMENT", "INVOICE
    #123"), and it keeps the scan cheap on long files.
    """
    for doc_type, keywords in _DOC_TYPE_KEYWORDS:
        if any(kw in name for kw in keywords):
            return doc_type

    head = (text or "")[:2000].lower()
    if head:
        for doc_type, keywords in _DOC_TYPE_KEYWORDS:
            if any(kw in head for kw in keywords):
                return doc_type

    return "other"


def _is_transcript_name(name: str) -> bool:
    return any(kw in name for kw in ("transcript", "meet recording", "recorded meeting", "call transcript"))


def _existing_meeting_id(user_id: str, file_id: str, db) -> str | None:
    """The meeting already created from this Drive file, if any."""
    try:
        rows = db.table("drive_doc_cache").select("meeting_id").eq("user_id", user_id).eq("drive_file_id", file_id).execute().data or []
        return (rows[0] or {}).get("meeting_id") if rows else None
    except Exception:
        return None


def _handle_transcript(user_id: str, file_meta: dict, service, db) -> None:
    """Download a Drive transcript file and trigger meeting agent processing."""
    try:
        from .meeting_agent import process_transcript

        mime = file_meta.get("mimeType", "")
        file_id = file_meta["id"]

        # `_filter_unprocessed` re-queues a file whose modifiedTime changed, and
        # this function used to insert unconditionally — so editing a transcript
        # produced a second meeting and a second set of action items. Contracts
        # already dedupe via drive_source_id; transcripts did not.
        already = _existing_meeting_id(user_id, file_id, db)
        if already:
            print(f"[drive-intel] {file_meta.get('name')}: already processed as meeting {already}, skipping")
            return

        # Raw get_media returns the *encoded* bytes — for a .docx or .pdf named
        # "transcript" that decoded to binary noise and fed it to the meeting
        # agent. download_drive_file_text runs the right extractor per type.
        text = download_drive_file_text(user_id, file_id, mime)

        # Resolve the client from the file name + transcript body (stronger).
        client_id = _resolve_client_id(user_id, file_meta.get("name", ""), text)

        # Create a meeting record then process
        now = datetime.now(timezone.utc)
        res = (
            db.table("meetings")
            .insert(
                {
                    "user_id": user_id,
                    "client_id": client_id,
                    "title": file_meta.get("name", "Drive transcript"),
                    "meeting_type": "video",
                    "meeting_date": now.isoformat(),
                    "source": "drive_transcript",
                    "raw_transcript": text[:10000],
                    "parse_status": "pending",
                }
            )
            .execute()
        )
        if res.data:
            meeting_id = res.data[0]["id"]
            process_transcript(user_id, meeting_id, text, "drive_transcript")

            # Link drive cache entry to the meeting (and the resolved client).
            db.table("drive_doc_cache").update(
                {
                    "meeting_id": meeting_id,
                    "client_id": client_id,
                }
            ).eq(
                "user_id", user_id
            ).eq("drive_file_id", file_id).execute()

    except Exception as exc:
        print(f"[drive-intel] transcript processing failed: {exc}")


def _queue_document_review(user_id: str, file_meta: dict, doc_type: str, db) -> None:
    """Queue a contract/invoice/receipt Drive file for user review."""
    from ..models import ManagerTask
    from .. import store

    title = f"Review {doc_type} from Drive: {file_meta.get('name', 'Document')}"
    # manager_tasks.source_record_id is a UUID column, but a Drive file id is an
    # opaque Google string ("187A7iKJ7m0R4H83qDCSwta1i2tgT95XY"). Storing it raw
    # makes Postgres raise 22P02 — the same defect already fixed for the daily
    # digest. Derive a stable UUID; the real id stays in `payload.driveFileId`.
    src = drive_source_id(file_meta["id"])
    if store.find_open_manager_task(user_id, "review_contract", src):
        return
    store.insert_manager_task(
        ManagerTask(
            id=store.uid("task"),
            user_id=user_id,
            kind="review_contract",
            title=title,
            rationale=f"A new {doc_type} file was detected in your Kora Drive folder.",
            severity="info",
            status="proposed",
            payload={"driveFileId": file_meta["id"], "fileName": file_meta.get("name"), "docType": doc_type, "mimeType": file_meta.get("mimeType", "")},
            source_record_type="drive_file",
            source_record_id=src,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
    )


def _save_as_client_note(user_id: str, file_meta: dict, service, db) -> None:
    """Save a brief/scope/proposal as a client note.

    Uses download_drive_file_text rather than files().export, which only works
    for native Google Docs — a .docx would raise, be swallowed by the except
    below, and silently save nothing.
    """
    try:
        text = download_drive_file_text(user_id, file_meta["id"], file_meta.get("mimeType", ""))

        client_id = _resolve_client_id(user_id, file_meta.get("name", ""), text)
        db.table("client_notes").insert(
            {
                "user_id": user_id,
                "client_id": client_id,
                "note_type": "general",
                "content_md": f"**From Drive:** {file_meta.get('name')}\n\n{text[:5000]}",
                "is_ai_generated": False,
            }
        ).execute()
        if client_id:
            db.table("drive_doc_cache").update({"client_id": client_id}).eq("user_id", user_id).eq("drive_file_id", file_meta["id"]).execute()
    except Exception as exc:
        print(f"[drive-intel] save-as-note failed: {exc}")
