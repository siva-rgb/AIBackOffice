# Google Butler — Drive Intelligence Reference

Scans the user's "Kora" folder in Drive and Google Meet transcripts.
Classifies each file by type and routes to the appropriate processor.

NOTE: The Google Docs API must be enabled in GCP Console for files.export()
to work on native Google Docs (application/vnd.google-apps.document).
Drive's export call internally routes through the Docs API. No new OAuth
scope is needed — the existing drive.readonly scope covers it.

---

## Drive intelligence service

```python
# app/services/drive_intel.py
import json
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from app.services.google_auth import get_user_credentials
from app.services.vertex_ai import generate_with_retry, getGeminiForAgent
from app.services.agent_logger import log_action
from app.services.meeting_agent import process_transcript
from app.utils.security import sanitize_prompt_input
from supabase import create_client
from app.config import settings


FILE_TYPE_MAP = {
    "application/vnd.google-apps.document": "google_doc",
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/plain": "txt",
    "text/vtt": "vtt",
    "image/jpeg": "image",
    "image/png": "image",
    "application/vnd.google-apps.spreadsheet": "spreadsheet",
}

TRANSCRIPT_NAME_PATTERNS = [
    "transcript", "meeting transcript", "call transcript",
    "recorded meeting", "meet recording"
]


async def sync_drive_intel(user_id: str):
    """
    Main entry point. Scans Kora folder and Meet transcripts.
    Routes each file to the appropriate processor.
    Called daily by the morning briefing worker.
    """
    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    creds = await get_user_credentials(user_id)
    if not creds:
        return

    service = build("drive", "v3", credentials=creds)
    conn = db.table("google_connections").select(
        "kora_folder_id"
    ).eq("user_id", user_id).single().execute().data
    kora_folder_id = conn.get("kora_folder_id") if conn else None

    files_to_process = []

    # 1. Files in the Kora folder
    if kora_folder_id:
        kora_files = await _list_folder_files(service, kora_folder_id)
        files_to_process.extend(kora_files)

    # 2. Google Meet transcripts (auto-saved by Workspace)
    transcript_files = await _find_meet_transcripts(service)
    files_to_process.extend(transcript_files)

    # 3. Filter: only process new or modified files
    new_files = await _filter_unprocessed(user_id, files_to_process, db)

    for file_meta in new_files:
        try:
            await _route_file(user_id, file_meta, service, db)
        except Exception as e:
            print(f"Drive file processing failed: {file_meta.get('name')}: {e}")
            continue


async def _list_folder_files(service, folder_id: str) -> list:
    result = service.files().list(
        q=f"'{folder_id}' in parents and trashed = false",
        fields="files(id, name, mimeType, modifiedTime, size)",
        pageSize=50,
    ).execute()
    return result.get("files", [])


async def _find_meet_transcripts(service) -> list:
    thirty_days_ago = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S")
    query = (
        f"(name contains 'transcript' or name contains 'Transcript') "
        f"and modifiedTime > '{thirty_days_ago}' "
        f"and trashed = false"
    )
    result = service.files().list(
        q=query,
        fields="files(id, name, mimeType, modifiedTime)",
        pageSize=20,
    ).execute()
    return result.get("files", [])


async def _filter_unprocessed(user_id: str, files: list, db) -> list:
    if not files:
        return []
    file_ids = [f["id"] for f in files]
    cached = db.table("drive_doc_cache").select(
        "drive_file_id, processed_at, drive_modified_time"
    ).eq("user_id", user_id).in_("drive_file_id", file_ids).execute().data

    cached_map = {c["drive_file_id"]: c for c in cached}
    new_files = []
    for f in files:
        fid = f["id"]
        if fid not in cached_map:
            new_files.append(f)
        else:
            cached_modified = cached_map[fid].get("drive_modified_time", "")
            if f.get("modifiedTime", "") > cached_modified:
                new_files.append(f)
    return new_files


async def _route_file(user_id: str, file_meta: dict, service, db):
    """Classify a file and route to the right processor."""
    mime = file_meta.get("mimeType", "")
    name = file_meta.get("name", "").lower()

    is_transcript = (
        mime == "text/vtt" or
        any(p in name for p in TRANSCRIPT_NAME_PATTERNS)
    )

    if is_transcript:
        await _process_transcript_file(user_id, file_meta, service, db)
    elif "pdf" in mime or "document" in mime:
        await _classify_and_process_document(user_id, file_meta, service, db)
    elif "image" in mime:
        _cache_file(user_id, file_meta, "receipt_image", db)
    elif "spreadsheet" in mime:
        _queue_spreadsheet_review(user_id, file_meta, db)
    else:
        _cache_file(user_id, file_meta, "unsupported", db)


async def _process_transcript_file(user_id: str, file_meta: dict, service, db):
    """Download transcript, create meeting record, process with meeting_agent."""
    file_id = file_meta["id"]
    mime = file_meta.get("mimeType", "")

    # Google Docs API must be enabled for this export to work on native Google Docs
    if mime == "application/vnd.google-apps.document":
        content = service.files().export(fileId=file_id, mimeType="text/plain").execute()
        text = content.decode("utf-8") if isinstance(content, bytes) else str(content)
    else:
        content = service.files().get_media(fileId=file_id).execute()
        text = content.decode("utf-8") if isinstance(content, bytes) else str(content)

    client_id = await _detect_client_from_text(user_id, text, db)

    result = db.table("meetings").insert({
        "user_id": user_id,
        "client_id": client_id,
        "title": file_meta.get("name", "Drive transcript"),
        "meeting_date": file_meta.get("modifiedTime", datetime.utcnow().isoformat()),
        "meeting_type": "video",
        "source": "drive_transcript",
        "raw_transcript": text[:10000],
        "parse_status": "pending",
    }).execute()
    meeting_id = result.data[0]["id"]

    await process_transcript(user_id, meeting_id, text, "drive_transcript")
    _cache_file(user_id, file_meta, "transcript", db, {"meeting_id": meeting_id})


async def _classify_and_process_document(user_id: str, file_meta: dict, service, db):
    """Download PDF/Doc, classify intent, route to action."""
    file_id = file_meta["id"]
    mime = file_meta.get("mimeType", "")

    # Google Docs API required for native Google Doc export
    if "google-apps.document" in mime:
        content = service.files().export(fileId=file_id, mimeType="text/plain").execute()
        text = content.decode("utf-8")[:5000] if isinstance(content, bytes) else str(content)[:5000]
    else:
        content = service.files().get_media(fileId=file_id).execute()
        try:
            import io, pdfplumber
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                text = "\n".join(page.extract_text() or "" for page in pdf.pages[:3])[:5000]
        except Exception:
            text = ""

    if not text.strip():
        _cache_file(user_id, file_meta, "unreadable", db)
        return

    safe_text = sanitize_prompt_input(text[:1500])
    model = getGeminiForAgent("butler")
    classify_prompt = f"""
Classify this business document in one word.
Options: contract | invoice | receipt | proposal | brief | scope | report | other

Document title: {file_meta.get('name', '')}
First 1000 characters:
{safe_text[:1000]}

Return ONLY one word from the options above.
"""
    result = await generate_with_retry(lambda: model.generate_content(classify_prompt))
    doc_type = result.response.candidates[0].content.parts[0].text.strip().lower()

    if doc_type == "contract":
        db.table("manager_tasks").insert({
            "user_id": user_id,
            "kind": "review_contract",
            "title": f"Contract detected in Drive: {file_meta.get('name')}",
            "rationale": "Kora found a contract document in your Drive folder.",
            "severity": "info",
            "status": "proposed",
            "payload": {"drive_file_id": file_meta["id"], "file_name": file_meta.get("name"),
                        "text_preview": text[:500]},
            "source_record_type": "drive_file",
            "source_record_id": file_meta["id"],
        }).execute()
    elif doc_type in ("invoice", "receipt"):
        # Extract financial data for a draft transaction
        await _create_draft_transaction_from_doc(user_id, file_meta, text, db)
    elif doc_type in ("brief", "scope", "proposal"):
        client_id = await _detect_client_from_text(user_id, text, db)
        if client_id:
            db.table("client_notes").insert({
                "user_id": user_id,
                "client_id": client_id,
                "note_type": "general",
                "content_md": f"**{doc_type.title()} from Drive:** {file_meta.get('name')}\n\n{text[:1000]}",
                "is_ai_generated": False,
            }).execute()

    _cache_file(user_id, file_meta, doc_type, db)

    await log_action(
        user_id=user_id,
        agent_type="butler_drive",
        action=f"Classified Drive file: {file_meta.get('name')} → {doc_type}",
        input_data={"file_id": file_meta["id"], "mime": mime},
        output_data={"doc_type": doc_type},
        latency_ms=0,
        triggered_by="scheduler"
    )


async def _create_draft_transaction_from_doc(user_id: str, file_meta: dict, text: str, db):
    """Extract financial data from an invoice/receipt and create a draft transaction."""
    safe_text = sanitize_prompt_input(text[:2000])
    model = getGeminiForAgent("butler")
    prompt = f"""
Extract financial data from this invoice or receipt.
Document: {file_meta.get('name', '')}
Content:
{safe_text}

Return JSON:
{{
  "vendor": "company or person",
  "amount": number,
  "currency": "USD or detected",
  "date": "YYYY-MM-DD or null",
  "description": "what was purchased",
  "is_expense": true or false,
  "likely_tax_deductible": true or false
}}
"""
    result = await generate_with_retry(lambda: model.generate_content(prompt))
    raw = result.response.candidates[0].content.parts[0].text
    try:
        extracted = json.loads(raw.replace("```json", "").replace("```", "").strip())
        if extracted.get("amount"):
            db.table("transactions").insert({
                "user_id": user_id,
                "date": extracted.get("date") or datetime.utcnow().date().isoformat(),
                "description": f"{extracted.get('vendor', '')} — {extracted.get('description', '')}",
                "amount": -abs(extracted["amount"]) if extracted.get("is_expense") else abs(extracted["amount"]),
                "currency": extracted.get("currency", "USD"),
                "type": "expense" if extracted.get("is_expense") else "income",
                "category": "other_expense",
                "tax_deductible": extracted.get("likely_tax_deductible", False),
                "ai_categorized": True,
                "ai_confidence": 0.6,
                "source": "drive",
                "raw_text": text[:500],
            }).execute()
    except Exception:
        pass


async def _detect_client_from_text(user_id: str, text: str, db) -> str | None:
    import re
    emails = re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', text)
    if not emails:
        return None
    clients = db.table("clients").select("id, email").eq("user_id", user_id).execute().data
    client_emails = {c["email"].lower(): c["id"] for c in clients if c.get("email")}
    for email in emails:
        if email.lower() in client_emails:
            return client_emails[email.lower()]
    return None


def _queue_spreadsheet_review(user_id: str, file_meta: dict, db):
    db.table("manager_tasks").insert({
        "user_id": user_id,
        "kind": "review_contract",
        "title": f"Spreadsheet may contain transactions: {file_meta.get('name')}",
        "rationale": "Found a spreadsheet in your Kora folder. Import for bookkeeping?",
        "severity": "info",
        "status": "proposed",
        "payload": {"drive_file_id": file_meta["id"], "file_name": file_meta.get("name")},
    }).execute()


def _cache_file(user_id: str, file_meta: dict, doc_type: str, db, extra: dict = None):
    db.table("drive_doc_cache").upsert({
        "user_id": user_id,
        "drive_file_id": file_meta["id"],
        "file_name": file_meta.get("name"),
        "mime_type": file_meta.get("mimeType"),
        "doc_type": doc_type,
        "drive_modified_time": file_meta.get("modifiedTime"),
        "processed_at": datetime.utcnow().isoformat(),
        **(extra or {}),
    }, on_conflict="user_id,drive_file_id").execute()
```

---

## File type routing table

```
File type                → Action
──────────────────────────────────────────────────
Google Doc (transcript)  → meeting_agent.process_transcript()
.vtt / .srt / .txt       → meeting_agent.process_transcript()
PDF (contract)           → queue contract review in manager_tasks
PDF (invoice/receipt)    → extract amount → draft transaction
Receipt image (jpg/png)  → Document AI OCR → draft transaction
Google Doc (brief/scope) → save as client_note
Word document (.docx)    → extract text → classify → route same as above
CSV / Spreadsheet        → offer to import for bookkeeping
Audio recording          → cannot transcribe at zero budget → flag for user
```

---

## Kora folder setup (first-time after OAuth)

```python
# app/services/drive_intel.py — add to sync_drive_intel()

async def create_kora_folder(user_id: str) -> str:
    """Create a 'Kora' folder in the user's Drive root. Returns folder ID."""
    creds = await get_user_credentials(user_id)
    service = build("drive", "v3", credentials=creds)

    folder_metadata = {
        "name": settings.DRIVE_KORA_FOLDER_NAME or "Kora",
        "mimeType": "application/vnd.google-apps.folder"
    }
    folder = service.files().create(body=folder_metadata, fields="id").execute()
    folder_id = folder.get("id")

    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    db.table("google_connections").update({
        "kora_folder_id": folder_id
    }).eq("user_id", user_id).execute()

    return folder_id
```
