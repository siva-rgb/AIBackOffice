from __future__ import annotations

import base64
import json

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request

from .. import store
from ..config import settings
from ..dependencies import get_current_user, verify_cron_secret
from ..models import CamelModel, User
from ..seed import DEMO_USER_ID
from ..services.gmail_intel import (
    handle_push_notification,
    register_gmail_watch,
    renew_watch_if_configured,
    sync_client_email_intel,
)

router = APIRouter(prefix="/api/gmail", tags=["gmail"])


class DraftRequest(CamelModel):
    context: str = "follow up"
    tone: str = "professional"


def _scheduler_user_id() -> str:
    if settings.KORA_DATA_BACKEND == "supabase":
        u = store.get_user_by_email(settings.DEMO_EMAIL)
        if u:
            return u.id
    return DEMO_USER_ID


@router.post("/sync")
async def sync_email_intel(
    background_tasks: BackgroundTasks,
    force: bool = False,
    user: User = Depends(get_current_user),
):
    """Manually trigger Gmail intelligence sync for all active clients."""
    background_tasks.add_task(sync_client_email_intel, user.id, force)
    return {"status": "syncing"}


@router.post("/run")
async def run_email_intel(
    background_tasks: BackgroundTasks,
    authorization: str | None = Header(default=None),
    is_cron: bool = Depends(verify_cron_secret),
):
    """Daily scheduled Gmail intel sync. Scheduler path uses x-cron-secret; a
    user path (auth) also works for a manual full refresh."""
    if is_cron:
        uid = _scheduler_user_id()
        background_tasks.add_task(sync_client_email_intel, uid, True)
        # Keep the Gmail push watch alive (expires ~7 days). No-op if push unset.
        background_tasks.add_task(renew_watch_if_configured, uid)
        return {"status": "syncing", "trigger": "scheduler"}
    user = await get_current_user(authorization)
    background_tasks.add_task(sync_client_email_intel, user.id, True)
    return {"status": "syncing", "trigger": "user"}


@router.post("/watch")
async def start_gmail_watch(user: User = Depends(get_current_user)):
    """Register a Gmail real-time push watch for this user (Pub/Sub). Requires
    GMAIL_PUBSUB_TOPIC configured + a public /api/gmail/push endpoint."""
    if not settings.GMAIL_PUBSUB_TOPIC:
        raise HTTPException(503, "Real-time push not configured (GMAIL_PUBSUB_TOPIC missing)")
    try:
        return register_gmail_watch(user.id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/push")
async def gmail_push(request: Request, background_tasks: BackgroundTasks):
    """Pub/Sub push endpoint for Gmail watch notifications. No auth — Google calls
    this directly. The message payload is `{emailAddress, historyId}` (base64).
    We resolve the mailbox to a user and refresh their intel in the background."""
    try:
        envelope = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid push payload")

    message = (envelope or {}).get("message", {})
    data_b64 = message.get("data")
    if not data_b64:
        return {"status": "ignored"}
    try:
        decoded = base64.urlsafe_b64decode(data_b64).decode("utf-8")
        payload = json.loads(decoded)
    except Exception:
        raise HTTPException(400, "Undecodable push data")

    email_address = payload.get("emailAddress")
    if email_address:
        background_tasks.add_task(handle_push_notification, email_address)
    return {"status": "ok"}


@router.get("/intel")
async def get_email_intel(
    client_id: str | None = None,
    user: User = Depends(get_current_user),
):
    """Return cached email intelligence, optionally filtered to one client (used
    by the per-client Email tab)."""
    if not settings.SUPABASE_URL:
        return []
    from supabase import create_client
    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    from ..utils.casing import camelize
    q = db.table("email_intel_cache").select(
        "client_name, client_id, sentiment, relationship_health, "
        "summary, action_needed, action_description, last_contact_days, "
        "last_contact_direction, commitments_pending, open_questions, processed_at"
    ).eq("user_id", user.id)
    if client_id:
        q = q.eq("client_id", client_id)
    return camelize(q.order("last_contact_days").execute().data)


@router.post("/draft/{client_id}")
async def draft_email(
    client_id: str,
    body: DraftRequest,
    user: User = Depends(get_current_user),
):
    """Generate an email draft to a client and queue for HITL approval."""
    if not settings.SUPABASE_URL:
        raise HTTPException(503, "Supabase not configured")
    from supabase import create_client
    from ..services.gmail_agent import queue_gmail_send
    from ..services.vertex_ai import generate_with_retry, get_ai

    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    client_rows = db.table("clients").select(
        "name, email, what_we_do"
    ).eq("id", client_id).eq("user_id", user.id).single().execute().data
    if not client_rows:
        raise HTTPException(404, "Client not found")

    cache = db.table("email_intel_cache").select(
        "summary, commitments_pending, open_questions"
    ).eq("user_id", user.id).eq("client_id", client_id).execute().data
    email_ctx = cache[0] if cache else {}

    import json
    prompt = f"""Draft a professional email on behalf of a business owner.
RECIPIENT: {client_rows['name']} ({client_rows.get('email', '')})
RELATIONSHIP CONTEXT: {client_rows.get('what_we_do', '')}
EMAIL HISTORY SUMMARY: {email_ctx.get('summary', 'No history')}
PENDING COMMITMENTS: {json.dumps(email_ctx.get('commitments_pending', []))}
PURPOSE: {body.context}
TONE: {body.tone}

Return JSON: {{"subject": "...", "body_text": "...", "body_html": "..."}}
Rules: address client by first name, single clear call to action, under 150 words."""

    ai = get_ai()
    call = generate_with_retry(lambda: ai.generate_email_draft({"prompt": prompt}))
    raw = call.data if isinstance(call.data, str) else json.dumps(call.data)
    try:
        draft = json.loads(raw.replace("```json", "").replace("```", "").strip())
    except Exception:
        draft = {"subject": "Follow-up", "body_text": raw[:500], "body_html": raw[:500]}
    try:
        from ..services.validation import validate_email_draft
        from .. import store
        invoices = store.list_invoices(user.id)
        known_amounts = [float(inv.total) for inv in invoices if inv.client_id == client_id and inv.total]
        draft = validate_email_draft(draft, client_rows.get("name", ""), known_amounts, user.id)
    except Exception:
        pass

    if client_rows.get("email"):
        queue_gmail_send(
            user_id=user.id,
            to_email=client_rows["email"],
            to_name=client_rows["name"],
            subject=draft.get("subject", "Follow-up"),
            body_html=draft.get("body_html", ""),
            body_text=draft.get("body_text", ""),
            context=f"{body.context} — tone: {body.tone}",
            related_client_id=client_id,
        )

    return draft
