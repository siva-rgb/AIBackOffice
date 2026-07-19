from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

from .. import store
from ..dependencies import get_current_user
from ..models import Invoice, LineItem, Retainer, RetainerCreate, User
from ..services import agent_logger, butler
from ..utils.security import safe_sanitize

router = APIRouter(prefix="/api/retainers", tags=["retainers"])

_CYCLE_DAYS = {"weekly": 7, "monthly": 30, "quarterly": 91, "annual": 365}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _advance(d: date, cycle: str) -> date:
    return d + timedelta(days=_CYCLE_DAYS.get(cycle, 30))


@router.get("")
async def list_retainers(status: str | None = None, user: User = Depends(get_current_user)):
    rows = store.list_retainers(user.id, status=status)
    out = []
    for r in rows:
        row = r.model_dump(by_alias=True)
        if r.client_id:
            c = store.get_client(user.id, r.client_id)
            row["clientName"] = c.name if c else None
        out.append(row)
    return out


@router.post("")
async def create_retainer(body: RetainerCreate, user: User = Depends(get_current_user)):
    client_id = body.client_id
    if client_id and not store.get_client(user.id, client_id):
        raise HTTPException(status_code=404, detail="Client not found")
    try:
        start = date.fromisoformat(body.start_date)
    except ValueError:
        raise HTTPException(status_code=422, detail="start_date must be YYYY-MM-DD")
    next_inv = start if start >= date.today() else date.today()

    retainer = Retainer(
        id=store.uid("ret"), user_id=user.id, client_id=client_id,
        title=safe_sanitize(body.title, max_len=200), amount=body.amount, currency=body.currency,
        billing_cycle=body.billing_cycle, start_date=body.start_date, end_date=body.end_date,
        next_invoice_date=next_inv.isoformat(),
        renewal_date=(body.end_date or None), status="active", auto_invoice=body.auto_invoice,
        created_at=_now(),
    )
    store.insert_retainer(retainer)
    if client_id:
        butler.touch_client(user.id, client_id)
    return retainer.model_dump(by_alias=True)


@router.patch("/{retainer_id}")
async def update_retainer(retainer_id: str, patch: dict, user: User = Depends(get_current_user)):
    allowed = {k: v for k, v in patch.items() if k in ("status", "auto_invoice", "amount", "end_date")}
    updated = store.update_retainer(user.id, retainer_id, allowed)
    if not updated:
        raise HTTPException(status_code=404, detail="Retainer not found")
    return updated.model_dump(by_alias=True)


@router.post("/{retainer_id}/invoice")
async def create_retainer_invoice(retainer_id: str, user: User = Depends(get_current_user)):
    """Create the next draft invoice for a retainer now, and advance its schedule.
    (Kora has no worker runtime — this is the on-demand equivalent of the daily
    retainer-invoicer worker; the owner reviews the draft before sending.)"""
    r = store.get_retainer(user.id, retainer_id)
    if not r:
        raise HTTPException(status_code=404, detail="Retainer not found")
    if r.status != "active":
        raise HTTPException(status_code=400, detail=f"Retainer is {r.status} — not billable.")

    client_name, client_email = "Client", ""
    if r.client_id:
        c = store.get_client(user.id, r.client_id)
        if c:
            client_name, client_email = c.name, (c.email or "")

    invoice = Invoice(
        id=store.uid("inv"), user_id=user.id, invoice_number=store.next_invoice_number(user.id),
        client_name=client_name, client_email=client_email or "billing@example.com",
        line_items=[LineItem(description=r.title, quantity=1, rate=r.amount, amount=r.amount)],
        subtotal=r.amount, tax_rate=0, tax_amount=0, total=r.amount, currency=r.currency,
        status="draft", due_date=(date.today() + timedelta(days=14)).isoformat(),
        notes=f"Auto-created from retainer ({r.billing_cycle}).", created_at=_now(),
    )
    store.insert_invoice(invoice)

    try:
        nxt = _advance(date.fromisoformat(r.next_invoice_date or date.today().isoformat()), r.billing_cycle)
        store.update_retainer(user.id, r.id, {"next_invoice_date": nxt.isoformat()})
    except Exception:
        pass

    agent_logger.log_action(
        user_id=user.id, agent_type="butler",
        action=f"Created retainer invoice for {client_name} ({r.title})",
        input={"retainerId": r.id}, output={"invoiceId": invoice.id, "amount": r.amount},
        triggered_by="user", source_record_type="retainer", source_record_id=r.id)
    if r.client_id:
        butler.touch_client(user.id, r.client_id)
    return {"invoiceId": invoice.id, "invoiceNumber": invoice.invoice_number}
