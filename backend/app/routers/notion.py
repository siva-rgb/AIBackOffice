from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from fastapi.responses import RedirectResponse

from .. import store
from ..config import settings
from ..dependencies import get_current_user, verify_cron_secret
from ..models import CamelModel, User
from ..seed import DEMO_USER_ID
from ..services import notion_connector, notion_ingest

router = APIRouter(prefix="/api/notion", tags=["notion"])


def _scheduler_user_id() -> str:
    if settings.KORA_DATA_BACKEND == "supabase":
        u = store.get_user_by_email(settings.DEMO_EMAIL)
        if u:
            return u.id
    return DEMO_USER_ID


class SelectPagesRequest(CamelModel):
    page_ids: list[str] = []


@router.get("/status")
async def notion_status(user: User = Depends(get_current_user)):
    """Connection + ingest-selection state for the settings UI."""
    return notion_connector.status(user.id)


@router.get("/connect")
async def notion_connect(user: User = Depends(get_current_user)):
    """Start the Notion OAuth flow (public integration). Returns the URL for the
    browser to visit; `state` carries the user id so the callback can attribute it."""
    url = notion_connector.oauth_authorize_url(state=user.id)
    if not url:
        raise HTTPException(
            status_code=400,
            detail="Notion OAuth is not configured. Set NOTION_OAUTH_CLIENT_ID/SECRET, " "or use an internal integration via NOTION_API_KEY.",
        )
    return {"authorizeUrl": url}


@router.get("/callback")
async def notion_callback(code: str | None = None, state: str | None = None, error: str | None = None):
    """OAuth redirect target. Notion sends the user back here with a code."""
    app_url = settings.NEXT_PUBLIC_APP_URL.rstrip("/")
    if error or not code or not state:
        return RedirectResponse(f"{app_url}/settings?notion=error")
    result = notion_connector.exchange_code(state, code)
    ok = "connected" if result.get("ok") else "error"
    return RedirectResponse(f"{app_url}/settings?notion={ok}")


@router.get("/pages")
async def notion_pages(user: User = Depends(get_current_user)):
    """Pages this user granted access to — the picker for what Kora may READ."""
    result = notion_connector.list_parent_pages(user.id)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Could not list pages."))
    return result


@router.post("/select")
async def notion_select(payload: SelectPagesRequest, user: User = Depends(get_current_user)):
    """Save which pages Kora may read. Read-only selection — writes nothing to Notion."""
    return notion_connector.set_ingest_pages(user.id, payload.page_ids)


@router.post("/run")
async def notion_run(
    background_tasks: BackgroundTasks,
    authorization: str | None = Header(default=None),
    is_cron: bool = Depends(verify_cron_secret),
):
    """Ingest the selected Notion pages into semantic memory. One-way, read-only.
    Scheduler path uses x-cron-secret; the user path runs it for their own account."""
    if is_cron:
        background_tasks.add_task(notion_ingest.ingest, _scheduler_user_id())
        return {"status": "ingesting", "trigger": "scheduler"}
    user = await get_current_user(authorization)
    result = notion_ingest.ingest(user.id)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Ingest failed."))
    return result


@router.delete("/disconnect", status_code=204)
async def notion_disconnect(user: User = Depends(get_current_user)):
    # Revoking Notion also revokes what Kora learned from it.
    notion_ingest.purge(user.id)
    notion_connector.disconnect(user.id)
    return None
