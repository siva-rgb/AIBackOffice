from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Request

from .. import store
from ..config import settings
from ..dependencies import get_current_user, verify_cron_secret
from ..models import User
from ..seed import DEMO_USER_ID
from ..services.drive_intel import sync_drive_intel
from ..utils.casing import camelize

router = APIRouter(prefix="/api/drive", tags=["drive"])


def _scheduler_user_id() -> str:
    if settings.KORA_DATA_BACKEND == "supabase":
        u = store.get_user_by_email(settings.DEMO_EMAIL)
        if u:
            return u.id
    return DEMO_USER_ID


@router.post("/sync")
async def sync_drive(
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
):
    """Manually trigger Drive intelligence sync (Kora folder + Meet transcripts)."""
    background_tasks.add_task(sync_drive_intel, user.id)
    return {"status": "syncing"}


@router.post("/run")
async def run_drive(
    request: Request,
    background_tasks: BackgroundTasks,
    authorization: str | None = Header(default=None),
    is_cron: bool = Depends(verify_cron_secret),
):
    """Daily scheduled Drive sync. Scheduler path uses x-cron-secret; a user path
    (auth) also works for a manual run."""
    if is_cron:
        background_tasks.add_task(sync_drive_intel, _scheduler_user_id())
        return {"status": "syncing", "trigger": "scheduler"}
    user = await get_current_user(request, authorization)
    background_tasks.add_task(sync_drive_intel, user.id)
    return {"status": "syncing", "trigger": "user"}


@router.get("/cache")
async def get_drive_cache(
    client_id: str | None = None,
    user: User = Depends(get_current_user),
):
    """Return cached Drive file records for the user, optionally filtered to one
    client (per-client Drive tab)."""
    if not settings.SUPABASE_URL:
        return []
    from supabase import create_client

    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    try:
        q = db.table("drive_doc_cache").select("drive_file_id, file_name, doc_type, mime_type, processed_at, meeting_id, client_id").eq("user_id", user.id)
        if client_id:
            q = q.eq("client_id", client_id)
        return camelize(q.order("processed_at", desc=True).limit(50).execute().data)
    except Exception:
        # Pre-migration fallback: the client_id column isn't present yet
        # (2026-07-16_drive_client_link.sql). Keep the global Drive page working;
        # a per-client request simply has nothing to show until it's applied.
        if client_id:
            return []
        rows = (
            db.table("drive_doc_cache")
            .select("drive_file_id, file_name, doc_type, mime_type, processed_at, meeting_id")
            .eq("user_id", user.id)
            .order("processed_at", desc=True)
            .limit(50)
            .execute()
            .data
        )
        return camelize(rows)
