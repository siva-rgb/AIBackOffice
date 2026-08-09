from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Header, Request
from fastapi.responses import StreamingResponse

from .. import store
from ..config import settings
from ..dependencies import get_current_user, verify_cron_secret
from ..models import (
    CreateInvoiceRequest,
    Invoice,
    LineItem,
    RecordPaymentRequest,
    UpdateInvoiceStatusRequest,
    User,
)
from ..seed import DEMO_USER_ID
from ..services.invoice_agent import generate_demand_letter, run_follow_up_agent
from ..utils.rate_limit import check_rate_limit

router = APIRouter(prefix="/api/invoices", tags=["invoices"])


def _queue_invoice_pdf(user_id: str, invoice_id: str) -> None:
    try:
        from ..services.invoice_pdf import generate_invoice_pdf

        generate_invoice_pdf(user_id, invoice_id)
    except Exception:
        pass


def _totals(items: list[LineItem], tax_rate: float):
    subtotal = round(sum(li.quantity * li.rate for li in items), 2)
    tax_amount = round(subtotal * tax_rate / 100, 2)
    return subtotal, tax_amount, round(subtotal + tax_amount, 2)


@router.get("", response_model=list[Invoice])
async def list_invoices(user: User = Depends(get_current_user)):
    return store.list_invoices(user.id)


@router.post("", response_model=Invoice, status_code=201)
async def create_invoice(
    body: CreateInvoiceRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
):
    items = [LineItem(description=li.description, quantity=li.quantity, rate=li.rate, amount=round(li.quantity * li.rate, 2)) for li in body.line_items]
    subtotal, tax_amount, total = _totals(items, body.tax_rate)

    # Auto-fill client email/address/tax_id from the stored client record when
    # available — so a new invoice starts with the client's CURRENT details.
    # Look up by client_id, else by case-insensitive client_name (Kora's link).
    client_address = body.client_address
    client_tax_id = body.client_tax_id
    client_email = body.client_email
    linked = None
    if body.client_id:
        linked = store.get_client(user.id, body.client_id)
    if not linked and body.client_name:
        _name = body.client_name.strip().lower()
        linked = next((c for c in store.list_clients(user.id) if (c.name or "").strip().lower() == _name), None)
    if linked:
        client_email = client_email or getattr(linked, "email", None)
        client_address = client_address or getattr(linked, "billing_address", None)
        client_tax_id = client_tax_id or getattr(linked, "tax_id", None)

    today = datetime.now(timezone.utc).date().isoformat()
    invoice = Invoice(
        id=store.uid("inv"),
        user_id=user.id,
        invoice_number=store.next_invoice_number(user.id),
        client_id=body.client_id,
        client_name=body.client_name,
        client_email=client_email,
        line_items=items,
        subtotal=subtotal,
        tax_rate=body.tax_rate,
        tax_amount=tax_amount,
        total=total,
        currency=body.currency,
        status="draft",
        due_date=body.due_date,
        notes=body.notes,
        invoice_date=body.invoice_date or today,
        payment_terms=body.payment_terms,
        payment_terms_days=body.payment_terms_days,
        client_address=client_address,
        client_tax_id=client_tax_id,
        po_number=body.po_number,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    saved = store.insert_invoice(invoice)

    background_tasks.add_task(_queue_invoice_pdf, user.id, saved.id)
    return saved


def _scheduler_user_id() -> str:
    """Resolve the user the scheduler runs for. In Supabase mode this is the
    demo user's real UUID; in mock mode the literal demo id."""
    if settings.KORA_DATA_BACKEND == "supabase":
        u = store.get_user_by_email(settings.DEMO_EMAIL)
        if u:
            return u.id
    return DEMO_USER_ID


@router.post("/follow-up")
async def run_follow_up(
    request: Request,
    authorization: str | None = Header(default=None),
    is_cron: bool = Depends(verify_cron_secret),
):
    # Scheduler path: a Cloud Run worker calls with x-cron-secret (no session).
    if is_cron:
        result = run_follow_up_agent(_scheduler_user_id(), "scheduler")
        return {"ok": True, "scanned": result.scanned, "sent": result.sent, "details": result.details}
    # User path (demo button): requires auth — pass the header through explicitly.
    user = await get_current_user(request, authorization)
    rl = check_rate_limit(f"ai:followup:{user.id}", max_requests=30, window_seconds=3600)
    if not rl.allowed:
        raise HTTPException(status_code=429, detail="Rate limit reached. Try again shortly.")
    result = run_follow_up_agent(user.id, "user")
    return {"ok": True, "scanned": result.scanned, "sent": result.sent, "details": result.details}


@router.post("/{invoice_id}/demand")
async def demand_letter(invoice_id: str, user: User = Depends(get_current_user)):
    """Draft a formal payment demand letter for an overdue invoice, grounded in
    the linked contract's payment terms when available (cross-module agent)."""
    rl = check_rate_limit(f"ai:demand:{user.id}", max_requests=20, window_seconds=3600)
    if not rl.allowed:
        raise HTTPException(status_code=429, detail="Rate limit reached. Try again shortly.")
    try:
        return generate_demand_letter(user.id, invoice_id, triggered_by="user")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{invoice_id}/send", response_model=Invoice)
async def send_invoice(invoice_id: str, user: User = Depends(get_current_user)):
    from ..services.email_service import send_invoice_email
    from ..services.invoice_pdf import generate_invoice_pdf
    from ..services.storage import get_signed_url, is_configured

    inv = store.get_invoice(user.id, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Not found")
    if inv.status == "paid":
        raise HTTPException(status_code=409, detail="Invoice already paid")
    if not inv.client_email:
        raise HTTPException(status_code=422, detail="Invoice has no client email")

    # Ensure PDF exists
    if not inv.pdf_path:
        try:
            generate_invoice_pdf(user.id, invoice_id)
            inv = store.get_invoice(user.id, invoice_id)
        except Exception:
            pass

    # Get a short-lived PDF download URL (if GCS configured)
    pdf_url: str | None = None
    if inv and inv.pdf_path and is_configured():
        try:
            pdf_url = get_signed_url(user.id, inv.pdf_path, expiry_minutes=72 * 60, filename_override=f"invoice-{inv.invoice_number}.pdf")
        except Exception:
            pass

    payment_link = inv.payment_link or f"https://pay.stripe.com/demo/{inv.invoice_number}"

    user_obj = store.get_user(user.id)
    sender_name = ""
    if user_obj and user_obj.profile:
        p = user_obj.profile
        sender_name = getattr(p, "business_name", None) or getattr(p, "name", None) or user_obj.email

    message_id = send_invoice_email(
        user_id=user.id,
        invoice_id=invoice_id,
        invoice_number=inv.invoice_number,
        client_name=inv.client_name,
        client_email=inv.client_email,
        sender_name=sender_name,
        amount=inv.total,
        currency=inv.currency or "USD",
        due_date=inv.due_date,
        payment_link=payment_link,
        pdf_url=pdf_url,
        notes=inv.notes,
    )

    return store.update_invoice(
        user.id,
        invoice_id,
        {
            "status": "sent",
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "payment_link": payment_link,
            **({"email_message_id": message_id} if message_id else {}),
        },
    )


@router.post("/{invoice_id}/pdf")
async def generate_pdf(
    invoice_id: str,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
):
    """Queue PDF generation (or regeneration) — non-blocking (M8.3)."""
    inv = store.get_invoice(user.id, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Not found")
    background_tasks.add_task(_queue_invoice_pdf, user.id, invoice_id)
    return {"status": "queued", "invoiceId": invoice_id}


@router.get("/{invoice_id}/pdf/download")
async def download_pdf(invoice_id: str, user: User = Depends(get_current_user)):
    """Return a short-lived signed URL for the invoice PDF, or stream bytes when
    GCS is not configured."""
    from ..services.invoice_pdf import generate_invoice_pdf, get_invoice_pdf_bytes
    from ..services.storage import get_signed_url, is_configured

    inv = store.get_invoice(user.id, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Not found")

    if is_configured():
        if not inv.pdf_path:
            generate_invoice_pdf(user.id, invoice_id)
            inv = store.get_invoice(user.id, invoice_id)
        try:
            url = get_signed_url(
                user.id,
                inv.pdf_path,
                expiry_minutes=15,
                filename_override=f"invoice-{inv.invoice_number}.pdf",
            )
            return {"url": url, "expires_in_minutes": 15}
        except FileNotFoundError:
            # GCS object missing — regenerate
            generate_invoice_pdf(user.id, invoice_id)
            inv = store.get_invoice(user.id, invoice_id)
            url = get_signed_url(
                user.id,
                inv.pdf_path,
                expiry_minutes=15,
                filename_override=f"invoice-{inv.invoice_number}.pdf",
            )
            return {"url": url, "expires_in_minutes": 15}
    else:
        # Stream PDF bytes directly
        pdf_bytes = get_invoice_pdf_bytes(user.id, invoice_id)
        return StreamingResponse(
            iter([pdf_bytes]),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="invoice-{inv.invoice_number}.pdf"'},
        )


@router.patch("/{invoice_id}", response_model=Invoice)
async def update_invoice_status(invoice_id: str, body: UpdateInvoiceStatusRequest, user: User = Depends(get_current_user)):
    inv = store.get_invoice(user.id, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Not found")
    patch = {"status": body.status}
    if body.status == "paid":
        patch["paid_at"] = datetime.now(timezone.utc).isoformat()
    return store.update_invoice(user.id, invoice_id, patch)


@router.post("/{invoice_id}/payment", response_model=Invoice)
async def record_payment(invoice_id: str, body: RecordPaymentRequest, user: User = Depends(get_current_user)):
    """Record a (partial) payment against an invoice. Marks it paid when amount_paid >= total."""
    inv = store.get_invoice(user.id, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Not found")
    if inv.status in ("paid", "cancelled"):
        raise HTTPException(status_code=409, detail="Invoice is already paid or cancelled")
    current_paid = float(inv.amount_paid or 0)
    new_paid = round(current_paid + body.amount, 2)
    patch: dict = {"amount_paid": new_paid}
    if new_paid >= float(inv.total):
        patch["status"] = "paid"
        patch["paid_at"] = datetime.now(timezone.utc).isoformat()
    return store.update_invoice(user.id, invoice_id, patch)
