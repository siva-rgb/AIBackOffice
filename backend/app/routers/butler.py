from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException

from .. import store
from ..config import settings
from ..dependencies import get_current_user, verify_cron_secret
from ..models import CaptureCreate, QuickCapture, User
from ..seed import DEMO_USER_ID
from ..services import butler
from ..utils.rate_limit import check_rate_limit
from ..utils.security import PromptInjectionError, sanitize_prompt_input

router = APIRouter(prefix="/api/butler", tags=["butler"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("")
async def get_butler(user: User = Depends(get_current_user)):
    """Cheap page-load snapshot (no LLM): memory, last briefing, headline stats."""
    return butler.butler_snapshot(user.id)


def _scheduler_user_id() -> str:
    if settings.KORA_DATA_BACKEND == "supabase":
        u = store.get_user_by_email(settings.DEMO_EMAIL)
        if u:
            return u.id
    return DEMO_USER_ID


@router.post("/run")
async def run_butler(
    authorization: str | None = Header(default=None),
    is_cron: bool = Depends(verify_cron_secret),
):
    """Generate the morning briefing. Scheduler path uses x-cron-secret; user path requires auth."""
    if is_cron:
        return butler.generate_morning_briefing(_scheduler_user_id(), triggered_by="scheduler")
    user = await get_current_user(authorization)
    rl = check_rate_limit(f"ai:butler:{user.id}", max_requests=30, window_seconds=3600)
    if not rl.allowed:
        raise HTTPException(status_code=429, detail="Rate limit reached. Try again shortly.")
    return butler.generate_morning_briefing(user.id, triggered_by="user")


# --- Quick capture ----------------------------------------------------------
@router.post("/captures")
async def submit_capture(body: CaptureCreate, user: User = Depends(get_current_user)):
    """Submit a freeform note. Sanitized, stored raw (never lost), then parsed
    inline into structured state. Injection attempts are rejected, not stored."""
    rl = check_rate_limit(f"butler:capture:{user.id}", max_requests=50, window_seconds=86400)
    if not rl.allowed:
        raise HTTPException(status_code=429, detail="Daily quick-capture limit reached.")
    try:
        safe_text = sanitize_prompt_input(body.text, max_len=2000)
    except PromptInjectionError:
        raise HTTPException(status_code=400, detail="That note couldn't be accepted. Please rephrase.")

    capture = QuickCapture(
        id=store.uid("cap"),
        user_id=user.id,
        raw_text=safe_text,
        source=body.source,
        parse_status="pending",
        created_at=_now(),
    )
    store.insert_capture(capture)
    updated = butler.parse_capture(user.id, capture.id, safe_text)
    return (updated or capture).model_dump(by_alias=True)


@router.get("/captures/review")
async def review_queue(user: User = Depends(get_current_user)):
    """Captures the AI wasn't confident about (low confidence or failed parse)."""
    return [c.model_dump(by_alias=True) for c in store.list_captures(user.id, requires_review=True)]


@router.get("/captures")
async def list_captures(user: User = Depends(get_current_user)):
    return [c.model_dump(by_alias=True) for c in store.list_captures(user.id)]


@router.post("/captures/{capture_id}/resolve")
async def resolve_capture(capture_id: str, user: User = Depends(get_current_user)):
    """Mark a flagged capture as reviewed (clears it from the review queue)."""
    updated = store.update_capture(user.id, capture_id, {"requires_review": False})
    if not updated:
        raise HTTPException(status_code=404, detail="Capture not found")
    return updated.model_dump(by_alias=True)
