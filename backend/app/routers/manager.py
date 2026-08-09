from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Header, Request

from ..dependencies import get_current_user, verify_cron_secret
from ..models import CamelModel, User
from ..seed import DEMO_USER_ID
from ..config import settings
from .. import store
from ..services import supervisor
from ..utils.rate_limit import check_rate_limit
from ..utils.security import PromptInjectionError, safe_sanitize, sanitize_prompt_input

router = APIRouter(prefix="/api/manager", tags=["manager"])


class ChatMessage(CamelModel):
    role: str
    content: str


class ChatRequest(CamelModel):
    message: str
    history: list[ChatMessage] = []


@router.get("")
async def get_manager(user: User = Depends(get_current_user)):
    """Cheap snapshot (no LLM): goal progress, cross-module stats, pending decisions."""
    return supervisor.manager_snapshot(user.id)


def _scheduler_user_id() -> str:
    if settings.KORA_DATA_BACKEND == "supabase":
        u = store.get_user_by_email(settings.DEMO_EMAIL)
        if u:
            return u.id
    return DEMO_USER_ID


@router.post("/run")
async def run_manager(
    request: Request,
    authorization: str | None = Header(default=None),
    is_cron: bool = Depends(verify_cron_secret),
):
    """Run a full supervisor pass: reconcile → assess → queue → briefing.
    Scheduler path uses x-cron-secret; user path requires auth."""
    if is_cron:
        uid = _scheduler_user_id()
        result = supervisor.run_supervisor(uid, triggered_by="scheduler")
        # Email the owner their daily digest (Gmail → Resend → no-op).
        try:
            from ..services import owner_notify

            owner_notify.send_daily_digest(uid, result)
        except Exception as exc:
            import logging

            logging.getLogger("kora").warning("daily digest email failed: %s", exc)
        return result
    user = await get_current_user(request, authorization)
    rl = check_rate_limit(f"ai:manager:{user.id}", max_requests=30, window_seconds=3600)
    if not rl.allowed:
        raise HTTPException(status_code=429, detail="Rate limit reached. Try again shortly.")
    return supervisor.run_supervisor(user.id, triggered_by="user")


@router.post("/chat")
async def chat(body: ChatRequest, user: User = Depends(get_current_user)):
    """Ask the AI business manager — grounded in the owner's live data."""
    rl = check_rate_limit(f"ai:chat:{user.id}", max_requests=60, window_seconds=3600)
    if not rl.allowed:
        raise HTTPException(status_code=429, detail="Rate limit reached. Try again shortly.")
    # M4 (LLM Input Sanitization): `body.message` is direct user input — reject
    # injection rather than redact. History is past messages — redact so a
    # poisoned past message doesn't 500 the user out of their conversation.
    try:
        msg = sanitize_prompt_input(body.message, max_len=2000)
    except PromptInjectionError:
        raise HTTPException(
            status_code=400,
            detail="That message couldn't be accepted. Please rephrase without embedded instructions.",
        )
    history = [{"role": m.role, "content": safe_sanitize(m.content or "", max_len=2000)} for m in body.history][-8:]
    return await supervisor.chat_agentic_async(user.id, msg, history)


@router.post("/tasks/{task_id}/approve")
async def approve(task_id: str, user: User = Depends(get_current_user)):
    from ..services.playbook import observe_decision, observe_email_edit

    task = store.get_manager_task(user.id, task_id)
    try:
        result = supervisor.approve_task(user.id, task_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Task not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if task:
        task_dict = task.model_dump(by_alias=False)
        try:
            observe_decision(user.id, task_dict, "approved")
            if task.kind == "send_email_gmail":
                original_body = (task.payload or {}).get("body_text", "")
                edited_body = (task.payload or {}).get("edited_body_text", original_body)
                client_id = (task.payload or {}).get("related_client_id")
                if edited_body and edited_body != original_body:
                    observe_email_edit(user.id, original_body, edited_body, client_id)
        except Exception:
            pass
    return result


@router.post("/tasks/{task_id}/dismiss")
async def dismiss(task_id: str, user: User = Depends(get_current_user)):
    from ..services.playbook import observe_decision

    task = store.get_manager_task(user.id, task_id)
    try:
        result = supervisor.dismiss_task(user.id, task_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Task not found")
    if task:
        try:
            observe_decision(user.id, task.model_dump(by_alias=False), "dismissed")
        except Exception:
            pass
    return result
