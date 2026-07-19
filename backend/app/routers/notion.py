from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from fastapi.responses import RedirectResponse

from .. import store
from ..config import settings
from ..dependencies import get_current_user, verify_cron_secret
from ..models import CamelModel, User
from ..seed import DEMO_USER_ID
from ..services import notion_connector

router = APIRouter(prefix="/api/notion", tags=["notion"])


def _scheduler_user_id() -> str:
    if settings.KORA_DATA_BACKEND == "supabase":
        u = store.get_user_by_email(settings.DEMO_EMAIL)
        if u:
            return u.id
    return DEMO_USER_ID


class ProvisionRequest(CamelModel):
    parent_page_id: str | None = None


@router.get("/status")
async def notion_status(user: User = Depends(get_current_user)):
    """Connection + provisioning state for the settings UI."""
    return notion_connector.status(user.id)


@router.get("/connect")
async def notion_connect(user: User = Depends(get_current_user)):
    """Start the Notion OAuth flow (public integration). Returns the URL for the
    browser to visit; `state` carries the user id so the callback can attribute it."""
    url = notion_connector.oauth_authorize_url(state=user.id)
    if not url:
        raise HTTPException(
            status_code=400,
            detail="Notion OAuth is not configured. Set NOTION_OAUTH_CLIENT_ID/SECRET, "
                   "or use an internal integration via NOTION_API_KEY.",
        )
    return {"authorizeUrl": url}


@router.get("/callback")
async def notion_callback(code: str | None = None, state: str | None = None,
                          error: str | None = None):
    """OAuth redirect target. Notion sends the user back here with a code."""
    app_url = settings.NEXT_PUBLIC_APP_URL.rstrip("/")
    if error or not code or not state:
        return RedirectResponse(f"{app_url}/settings?notion=error")
    result = notion_connector.exchange_code(state, code)
    ok = "connected" if result.get("ok") else "error"
    return RedirectResponse(f"{app_url}/settings?notion={ok}")


@router.post("/provision")
async def notion_provision(payload: ProvisionRequest, user: User = Depends(get_current_user)):
    """Create the KORA-owned Tasks database in the connected workspace.
    Idempotent — returns the existing database if already provisioned."""
    result = notion_connector.provision_tasks_db(user.id, payload.parent_page_id)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Could not provision."))
    return result


@router.post("/sync")
async def notion_sync(user: User = Depends(get_current_user)):
    """Push canonical tasks to Notion, then pull back human edits."""
    result = notion_connector.sync(user.id)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Sync failed."))
    return result


@router.post("/run")
async def notion_run(
    background_tasks: BackgroundTasks,
    authorization: str | None = Header(default=None),
    is_cron: bool = Depends(verify_cron_secret),
):
    """Scheduled two-way sync. Scheduler path uses x-cron-secret."""
    if is_cron:
        background_tasks.add_task(notion_connector.sync, _scheduler_user_id())
        return {"status": "syncing", "trigger": "scheduler"}
    user = await get_current_user(authorization)
    background_tasks.add_task(notion_connector.sync, user.id)
    return {"status": "syncing", "trigger": "user"}


@router.delete("/disconnect", status_code=204)
async def notion_disconnect(user: User = Depends(get_current_user)):
    notion_connector.disconnect(user.id)
    return None
