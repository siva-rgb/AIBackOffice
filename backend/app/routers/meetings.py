from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile

from ..config import settings
from ..dependencies import get_current_user
from ..models import CamelModel, User
from ..services.meeting_agent import extract_transcript_text, process_transcript
from ..utils.casing import camelize
from ..utils.security import sanitize_prompt_input

router = APIRouter(prefix="/api/meetings", tags=["meetings"])

_MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB


def _db():
    from supabase import create_client
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MeetingCreate(CamelModel):
    title: str
    meeting_date: str
    client_id: Optional[str] = None
    engagement_id: Optional[str] = None
    meeting_type: str = "call"
    duration_minutes: Optional[int] = None
    attendees: Optional[list] = None


class QuickMeetingNote(CamelModel):
    notes: str
    client_id: Optional[str] = None
    meeting_date: Optional[str] = None
    title: Optional[str] = None


@router.get("")
async def list_meetings(
    client_id: str | None = None,
    limit: int = 20,
    user: User = Depends(get_current_user),
):
    """List meetings with inline action items."""
    if not settings.SUPABASE_URL:
        return []
    db = _db()
    q = db.table("meetings").select(
        "*, clients(name), meeting_action_items(id, description, status, owner)"
    ).eq("user_id", user.id).order("meeting_date", desc=True).limit(limit)
    if client_id:
        q = q.eq("client_id", client_id)
    return camelize(q.execute().data)


@router.get("/action-items")
async def list_all_action_items(
    status: str = "open",
    user: User = Depends(get_current_user),
):
    """All meeting action items (default: open) across every meeting, with the
    parent meeting + client — powers the consolidated Tasks view."""
    if not settings.SUPABASE_URL:
        return []
    db = _db()
    q = db.table("meeting_action_items").select(
        "*, meetings(title, meeting_date, client_id, clients(name))"
    ).eq("user_id", user.id)
    if status and status != "all":
        q = q.eq("status", status)
    return camelize(q.order("due_date", desc=False).execute().data)


@router.post("")
async def create_meeting(
    body: MeetingCreate,
    user: User = Depends(get_current_user),
):
    """Create a meeting record (no transcript yet)."""
    if not settings.SUPABASE_URL:
        raise HTTPException(503, "Supabase not configured")
    db = _db()
    payload = body.model_dump(exclude_none=True)
    payload.update({"user_id": user.id, "parse_status": "pending", "source": "manual"})
    res = db.table("meetings").insert(payload).execute()
    return res.data[0]


@router.post("/{meeting_id}/transcript")
async def upload_transcript(
    meeting_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    """Upload a transcript file (.txt, .vtt, .srt, .docx, .pdf) for AI processing."""
    if not settings.SUPABASE_URL:
        raise HTTPException(503, "Supabase not configured")

    content = await file.read()
    if len(content) > _MAX_FILE_SIZE:
        raise HTTPException(413, "Transcript file too large (max 2 MB)")

    transcript_text = extract_transcript_text(content, file.filename or "upload.txt")

    db = _db()
    # Verify ownership before writing
    row = db.table("meetings").select("id").eq("id", meeting_id).eq(
        "user_id", user.id).single().execute().data
    if not row:
        raise HTTPException(404, "Meeting not found")

    db.table("meetings").update({
        "raw_transcript": transcript_text[:10000],
        "source": "transcript_upload",
        "parse_status": "pending",
    }).eq("id", meeting_id).eq("user_id", user.id).execute()

    background_tasks.add_task(process_transcript, user.id, meeting_id,
                               transcript_text, "transcript_upload")
    return {"meeting_id": meeting_id, "status": "processing", "chars": len(transcript_text)}


@router.post("/quick-note")
async def create_quick_meeting_note(
    body: QuickMeetingNote,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
):
    """Create a meeting from a quick freeform note. AI processes it in the background."""
    if not settings.SUPABASE_URL:
        raise HTTPException(503, "Supabase not configured")

    safe_notes = sanitize_prompt_input(body.notes, max_len=3000)
    db = _db()
    res = db.table("meetings").insert({
        "user_id": user.id,
        "client_id": body.client_id,
        "title": body.title or "Meeting note",
        "meeting_date": body.meeting_date or _now(),
        "meeting_type": "call",
        "raw_notes": safe_notes,
        "source": "quick_capture",
        "parse_status": "pending",
    }).execute()
    meeting_id = res.data[0]["id"]

    background_tasks.add_task(process_transcript, user.id, meeting_id,
                               safe_notes, "quick_capture")
    return {"meeting_id": meeting_id, "status": "processing"}


@router.post("/{meeting_id}/followup")
async def draft_meeting_followup(
    meeting_id: str,
    user: User = Depends(get_current_user),
):
    """Draft + queue a post-meeting follow-up email for the owner's approval."""
    from ..services.meeting_agent import queue_followup_for_meeting
    result = queue_followup_for_meeting(user.id, meeting_id)
    if not result.get("queued"):
        raise HTTPException(400, result.get("reason", "Could not queue follow-up"))
    return result


@router.get("/{meeting_id}/action-items")
async def list_action_items(
    meeting_id: str,
    user: User = Depends(get_current_user),
):
    """Return action items for a specific meeting."""
    if not settings.SUPABASE_URL:
        return []
    db = _db()
    return camelize(db.table("meeting_action_items").select("*").eq(
        "meeting_id", meeting_id).eq("user_id", user.id).execute().data)


@router.patch("/{meeting_id}/action-items/{item_id}")
async def update_action_item(
    meeting_id: str,
    item_id: str,
    body: dict,
    user: User = Depends(get_current_user),
):
    """Update status/priority of a meeting action item."""
    if not settings.SUPABASE_URL:
        raise HTTPException(503, "Supabase not configured")
    allowed = {"status", "priority", "due_date", "completed_at"}
    update = {k: v for k, v in body.items() if k in allowed}
    if not update:
        raise HTTPException(400, "No valid fields to update")
    db = _db()
    res = db.table("meeting_action_items").update(update).eq(
        "id", item_id).eq("user_id", user.id).execute()
    if not res.data:
        raise HTTPException(404, "Action item not found")
    return res.data[0]
