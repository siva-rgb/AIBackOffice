from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..config import settings
from .google_auth import get_user_credentials

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


def _db():
    from supabase import create_client

    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)


def _resolve_client_id(user_id: str, name: str = "", text: str = "") -> str | None:
    """Best-effort: link a Drive file to a Butler client. Strongest signal is the
    client's name in the file name; otherwise the client's email/name inside the
    document body. Returns the client id or None."""
    try:
        from .. import store

        clients = store.list_clients(user_id)
    except Exception:
        return None
    fname = (name or "").lower()
    body = (text or "")[:4000].lower()
    fallback = None
    for c in clients:
        cname = (c.name or "").lower().strip()
        if cname and cname in fname:
            return c.id  # strong: client name in the file name
        emails = [c.email] + list(getattr(c, "contact_emails", None) or [])
        if any(e and e.lower() in body for e in emails):
            fallback = fallback or c.id
        elif cname and cname in body:
            fallback = fallback or c.id
    return fallback


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

    raw = service.files().get_media(fileId=file_id).execute()
    if not isinstance(raw, bytes):
        return str(raw)
    # Resolve a filename for extension-based extraction.
    try:
        meta = service.files().get(fileId=file_id, fields="name").execute()
        name = meta.get("name", "document")
    except Exception:
        name = "document"
    from ..utils.document_text import extract_text

    return extract_text(name, mime_type or None, raw)


def _list_folder_files(service, folder_id: str) -> list:
    result = (
        service.files()
        .list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields="files(id, name, mimeType, modifiedTime, size)",
            pageSize=50,
        )
        .execute()
    )
    return result.get("files", [])


def _find_meet_transcripts(service) -> list:
    thirty_days_ago = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S")
    query = f"(name contains 'transcript' or name contains 'Transcript') " f"and modifiedTime > '{thirty_days_ago}' " f"and trashed = false"
    result = (
        service.files()
        .list(
            q=query,
            fields="files(id, name, mimeType, modifiedTime)",
            pageSize=20,
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
    doc_type = _classify_doc_type(name, file_type, mime)

    # Mark as seen in the cache immediately (avoids re-processing on next run).
    # Link to a client by file name now; transcript/note handlers below refine it
    # with the document body.
    client_id = _resolve_client_id(user_id, file_meta.get("name", ""))
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
    elif doc_type in ("brief", "scope", "proposal") and file_type == "google_doc":
        _save_as_client_note(user_id, file_meta, service, db)
    # Spreadsheets and other types: logged in cache, no action taken


def _classify_doc_type(name: str, file_type: str, mime: str) -> str:
    if any(kw in name for kw in ("transcript", "recording", "meeting notes")):
        return "transcript"
    if any(kw in name for kw in ("contract", "agreement", "nda", "sow")):
        return "contract"
    if any(kw in name for kw in ("invoice", "inv-", "inv ")):
        return "invoice"
    if any(kw in name for kw in ("receipt", "payment")):
        return "receipt"
    if any(kw in name for kw in ("brief", "scope", "proposal", "rfp", "rfi")):
        return "brief"
    return "other"


def _is_transcript_name(name: str) -> bool:
    return any(kw in name for kw in ("transcript", "meet recording", "recorded meeting", "call transcript"))


def _handle_transcript(user_id: str, file_meta: dict, service, db) -> None:
    """Download a Drive transcript file and trigger meeting agent processing."""
    try:
        from .meeting_agent import process_transcript

        mime = file_meta.get("mimeType", "")
        file_id = file_meta["id"]

        if mime == "application/vnd.google-apps.document":
            content = service.files().export(fileId=file_id, mimeType="text/plain").execute()
            text = content.decode("utf-8", errors="ignore") if isinstance(content, bytes) else str(content)
        else:
            content = service.files().get_media(fileId=file_id).execute()
            text = content.decode("utf-8", errors="ignore") if isinstance(content, bytes) else str(content)

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
    if store.find_open_manager_task(user_id, "review_contract", file_meta["id"]):
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
            source_record_id=file_meta["id"],
            created_at=datetime.now(timezone.utc).isoformat(),
        )
    )


def _save_as_client_note(user_id: str, file_meta: dict, service, db) -> None:
    """Export a Google Doc (brief/scope) and save as a client note."""
    try:
        content = service.files().export(fileId=file_meta["id"], mimeType="text/plain").execute()
        text = content.decode("utf-8", errors="ignore") if isinstance(content, bytes) else str(content)

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
