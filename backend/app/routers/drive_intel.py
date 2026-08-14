from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request

from ..config import settings
from ..dependencies import get_current_user, require_scheduler_user_id, verify_cron_secret
from ..models import User
from ..services.drive_intel import ALL_DRIVES_GET, ALL_DRIVES_LIST, sync_drive_intel
from ..services.google_auth import get_user_credentials
from ..utils.casing import camelize

router = APIRouter(prefix="/api/drive", tags=["drive"])


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
        background_tasks.add_task(sync_drive_intel, require_scheduler_user_id())
        return {"status": "syncing", "trigger": "scheduler"}
    user = await get_current_user(request, authorization)
    background_tasks.add_task(sync_drive_intel, user.id)
    return {"status": "syncing", "trigger": "user"}


# --- Kora folder selection -------------------------------------------------
# `sync_drive_intel` only scans the folder recorded in
# `google_connections.kora_folder_id` (plus Meet transcripts). Nothing ever wrote
# that column, so the folder branch was dead for every user and documents added
# to Drive were invisible. These two endpoints are what populate it.
#
# A picker rather than auto-creation on connect: the app requests
# `drive.readonly`, which can LIST folders but cannot create one. Auto-creating
# would mean asking every user to re-consent to a write scope, for a folder they
# can make themselves in two seconds.


@router.get("/folders")
async def list_drive_folders(
    q: str | None = None,
    user: User = Depends(get_current_user),
):
    """Folders in the user's Drive, for choosing which one Kora watches.

    `q` filters by name (server-side, so large Drives stay usable).
    """
    creds = get_user_credentials(user.id)
    if not creds:
        raise HTTPException(status_code=400, detail="Google account not connected")

    from googleapiclient.discovery import build

    service = build("drive", "v3", credentials=creds)
    query = "mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    if q:
        # Escape single quotes — an apostrophe in a folder name would otherwise
        # terminate the query string and 400.
        query += f" and name contains '{q.replace(chr(39), chr(92) + chr(39))}'"

    try:
        # ALL_DRIVES_LIST: without it a Workspace user's shared-drive folders are
        # absent from this list, so they cannot pick the folder they meant to.
        result = (
            service.files().list(q=query, fields="files(id, name, modifiedTime)", orderBy="modifiedTime desc", pageSize=100, **ALL_DRIVES_LIST).execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not list Drive folders: {exc}") from exc

    selected = _current_folder_id(user.id)
    return camelize([{**f, "selected": f["id"] == selected} for f in result.get("files", [])])


@router.put("/folder")
async def set_drive_folder(
    body: dict,
    user: User = Depends(get_current_user),
):
    """Point Kora at a Drive folder. Pass {"folderId": null} to stop watching."""
    folder_id = (body or {}).get("folderId") or (body or {}).get("folder_id")

    if folder_id:
        creds = get_user_credentials(user.id)
        if not creds:
            raise HTTPException(status_code=400, detail="Google account not connected")

        from googleapiclient.discovery import build

        service = build("drive", "v3", credentials=creds)
        # Validate before storing: an unreachable or non-folder id would silently
        # sync nothing, which is the failure mode this endpoint exists to end.
        try:
            meta = service.files().get(fileId=folder_id, fields="id, name, mimeType, trashed", **ALL_DRIVES_GET).execute()
        except Exception as exc:
            raise HTTPException(status_code=404, detail="That folder isn't reachable with your Google connection") from exc
        if meta.get("mimeType") != "application/vnd.google-apps.folder":
            raise HTTPException(status_code=400, detail=f"'{meta.get('name')}' is a file, not a folder")
        if meta.get("trashed"):
            raise HTTPException(status_code=400, detail=f"'{meta.get('name')}' is in the trash")

    if not settings.SUPABASE_URL:
        raise HTTPException(status_code=503, detail="Storage backend not configured")

    from supabase import create_client

    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    db.table("google_connections").update({"kora_folder_id": folder_id}).eq("user_id", user.id).execute()

    return {"folderId": folder_id, "watching": bool(folder_id)}


def _current_folder_id(user_id: str) -> str | None:
    if not settings.SUPABASE_URL:
        return None
    try:
        from supabase import create_client

        db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
        rows = db.table("google_connections").select("kora_folder_id").eq("user_id", user_id).limit(1).execute().data
        return (rows or [{}])[0].get("kora_folder_id")
    except Exception:
        return None


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
