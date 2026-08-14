from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Header, Request

from .. import store
from ..dependencies import get_current_user, require_scheduler_user_id, verify_cron_secret
from pydantic import Field

from ..models import (
    CamelModel,
    Client,
    ClientCreate,
    ClientNote,
    ClientUpdate,
    Engagement,
    EngagementCreate,
    EngagementUpdate,
    NoteCreate,
    User,
)
from ..services import butler, pm_agent, rollup
from ..utils.security import safe_sanitize

router = APIRouter(prefix="/api/clients", tags=["clients"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("")
async def list_clients(status: str | None = None, user: User = Depends(get_current_user)):
    """Clients enriched with financials, active-engagement count, and last-activity age."""
    return butler.list_clients_enriched(user.id, status=status)


@router.post("")
async def create_client(body: ClientCreate, user: User = Depends(get_current_user)):
    client = Client(
        id=store.uid("cli"),
        user_id=user.id,
        name=safe_sanitize(body.name, max_len=200),
        email=body.email,
        contact_emails=[str(e).lower() for e in (body.contact_emails or [])],
        phone=body.phone,
        company=(safe_sanitize(body.company, max_len=200) if body.company else None),
        industry=body.industry,
        client_type=body.client_type,
        status=body.status,
        what_we_do=(safe_sanitize(body.what_we_do, max_len=500) if body.what_we_do else None),
        notes_md=(safe_sanitize(body.notes_md, max_len=5000) if body.notes_md else None),
        timezone=body.timezone,
        currency=body.currency,
        last_activity_at=_now(),
        created_at=_now(),
    )
    store.insert_client(client)
    return client.model_dump(by_alias=True)


@router.get("/{client_id}")
async def get_client(client_id: str, user: User = Depends(get_current_user)):
    detail = butler.get_client_detail(user.id, client_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Client not found")
    return detail


@router.patch("/{client_id}")
async def update_client(client_id: str, body: ClientUpdate, user: User = Depends(get_current_user)):
    data = body.model_dump(exclude_none=True, by_alias=False)
    for key in ("what_we_do", "notes_md", "company", "name"):
        if data.get(key):
            data[key] = safe_sanitize(data[key], max_len=5000)
    data["last_activity_at"] = _now()
    updated = store.update_client(user.id, client_id, data)
    if not updated:
        raise HTTPException(status_code=404, detail="Client not found")
    return updated.model_dump(by_alias=True)


@router.delete("/{client_id}")
async def delete_client(client_id: str, user: User = Depends(get_current_user)):
    ok = store.delete_client(user.id, client_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Client not found")
    return {"deleted": True}


@router.post("/{client_id}/health")
async def refresh_health(client_id: str, user: User = Depends(get_current_user)):
    c = store.get_client(user.id, client_id)
    if not c:
        raise HTTPException(status_code=404, detail="Client not found")
    return butler.compute_client_health(user.id, c, persist=True)


@router.get("/{client_id}/tree")
async def client_tree(client_id: str, user: User = Depends(get_current_user)):
    """Client → Project → Task with per-level roll-up health (M2, deterministic).

    Stories hang off each task via `GET /api/stories?client_id=`; the UI groups
    them by `taskId`. Zero LLM calls — pure arithmetic over the ledger.
    """
    if not store.get_client(user.id, client_id):
        raise HTTPException(status_code=404, detail="Client not found")
    return rollup.client_tree(user.id, client_id)


# --- Client view (M3 PM agent fan-out) --------------------------------------
@router.get("/{client_id}/view")
async def get_client_view(client_id: str, user: User = Depends(get_current_user)):
    """The agent-composed one-pager. Serves cache — never triggers an LLM call.

    A cold client (no cache yet) gets a deterministic, number-safe shell flagged
    `stale: true`, so opening the page can never surprise-bill the user.
    """
    view = pm_agent.get_client_view(user.id, client_id)
    if view is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return view


@router.post("/{client_id}/view/refresh")
async def refresh_client_view(client_id: str, user: User = Depends(get_current_user)):
    """Recompose the view via the analyst fan-out, then cache it."""
    view = pm_agent.compose_client_view(user.id, client_id)
    if view is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return view


@router.post("/views/refresh-all")
async def refresh_all_client_views(
    request: Request,
    authorization: str | None = Header(default=None),
    is_cron: bool = Depends(verify_cron_secret),
):
    """Nightly recompose of every client's view. Scheduler path uses
    x-cron-secret; a signed-in user may refresh their own set."""
    if is_cron:
        return pm_agent.refresh_all_views(require_scheduler_user_id())
    user = await get_current_user(request, authorization)
    return pm_agent.refresh_all_views(user.id)


# --- Engagements ------------------------------------------------------------
@router.get("/{client_id}/engagements")
async def list_engagements(client_id: str, user: User = Depends(get_current_user)):
    return [e.model_dump(by_alias=True) for e in store.list_engagements(user.id, client_id)]


@router.post("/{client_id}/engagements")
async def create_engagement(client_id: str, body: EngagementCreate, user: User = Depends(get_current_user)):
    if not store.get_client(user.id, client_id):
        raise HTTPException(status_code=404, detail="Client not found")
    eng = Engagement(
        id=store.uid("eng"),
        user_id=user.id,
        client_id=client_id,
        title=safe_sanitize(body.title, max_len=200),
        description_md=(safe_sanitize(body.description_md, max_len=2000) if body.description_md else None),
        engagement_type=body.engagement_type,
        status=body.status,
        start_date=body.start_date,
        target_end_date=body.target_end_date,
        budget=body.budget,
        budget_currency=body.budget_currency,
        contract_id=body.contract_id,
        created_at=_now(),
        updated_at=_now(),
    )
    store.insert_engagement(eng)
    butler.touch_client(user.id, client_id)
    return eng.model_dump(by_alias=True)


@router.patch("/{client_id}/engagements/{engagement_id}")
async def update_engagement(client_id: str, engagement_id: str, body: EngagementUpdate, user: User = Depends(get_current_user)):
    data = body.model_dump(exclude_none=True, by_alias=False)
    if data.get("description_md"):
        data["description_md"] = safe_sanitize(data["description_md"], max_len=2000)
    if data.get("title"):
        data["title"] = safe_sanitize(data["title"], max_len=200)
    data["updated_at"] = _now()
    updated = store.update_engagement(user.id, engagement_id, data)
    if not updated:
        raise HTTPException(status_code=404, detail="Engagement not found")
    butler.touch_client(user.id, client_id)
    return updated.model_dump(by_alias=True)


# --- Notes ------------------------------------------------------------------
@router.get("/{client_id}/notes")
async def list_notes(client_id: str, user: User = Depends(get_current_user)):
    return [n.model_dump(by_alias=True) for n in store.list_client_notes(user.id, client_id)]


@router.post("/{client_id}/notes")
async def create_note(client_id: str, body: NoteCreate, user: User = Depends(get_current_user)):
    if not store.get_client(user.id, client_id):
        raise HTTPException(status_code=404, detail="Client not found")
    note = ClientNote(
        id=store.uid("note"),
        user_id=user.id,
        client_id=client_id,
        engagement_id=body.engagement_id,
        note_type=body.note_type,
        content_md=safe_sanitize(body.content_md, max_len=5000),
        is_ai_generated=False,
        created_at=_now(),
    )
    store.insert_client_note(note)
    butler.touch_client(user.id, client_id)
    return note.model_dump(by_alias=True)


# --- Butler communication (HITL) --------------------------------------------
class ComposeRequest(CamelModel):
    intent: str = Field(min_length=3, max_length=2000)
    tone: str = Field(default="professional", max_length=50)


class QueueEmailRequest(CamelModel):
    subject: str = Field(min_length=1, max_length=300)
    body_text: str = Field(min_length=1, max_length=20000)
    body_html: str = Field(default="", max_length=50000)


@router.post("/{client_id}/compose")
async def compose_client_email(client_id: str, body: ComposeRequest, user: User = Depends(get_current_user)):
    """Butler drafts an email to this client (brand voice + relationship history).
    Returns the draft for review — does NOT send."""
    from ..services.butler_comms import draft_client_email

    try:
        return draft_client_email(user.id, client_id, safe_sanitize(body.intent, max_len=2000), body.tone)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/{client_id}/queue-email")
async def queue_client_email_endpoint(client_id: str, body: QueueEmailRequest, user: User = Depends(get_current_user)):
    """Queue a (possibly edited) draft for the owner's approval. Sends via Gmail
    only after approval in the Business Manager."""
    from ..services.butler_comms import queue_client_email

    try:
        return queue_client_email(user.id, client_id, body.subject, body.body_text, body.body_html)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
