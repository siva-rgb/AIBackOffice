"""
Resend-backed email delivery for invoices, follow-ups, and morning digests.
Gracefully degrades (logs but doesn't raise) when RESEND_API_KEY is not set.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from . import agent_logger

EMAIL_FROM = {
    "transactional": "Kora <hello@mail.kora.app>",
    "invoices": "Kora Invoices <invoices@mail.kora.app>",
    "alerts": "Kora <alerts@mail.kora.app>",
}

_DEFAULT_FROM_EMAIL = os.environ.get("FROM_EMAIL", EMAIL_FROM["invoices"])


def _resend_client():
    """Return resend module if API key is configured, else None."""
    api_key = os.environ.get("RESEND_API_KEY", "")
    if not api_key:
        return None
    try:
        import resend  # type: ignore
        resend.api_key = api_key
        return resend
    except ImportError:
        return None


def send_invoice_email(
    *,
    user_id: str,
    invoice_id: str,
    invoice_number: str,
    client_name: str,
    client_email: str,
    sender_name: str,
    amount: float,
    currency: str,
    due_date: str | None,
    payment_link: str | None,
    pdf_url: str | None = None,
    notes: str | None = None,
) -> str | None:
    """Send an invoice to the client via Resend. Returns message_id or None."""
    start = datetime.now(timezone.utc)
    sym = _currency_sym(currency)

    due_line = f"<p>Payment is due by <strong>{due_date}</strong>.</p>" if due_date else ""
    pay_btn = (
        f'<p><a href="{payment_link}" style="background:#2f6fed;color:#fff;padding:10px 20px;'
        f'text-decoration:none;border-radius:6px;font-weight:bold;display:inline-block;">'
        f"Pay Now</a></p>"
    ) if payment_link else ""
    pdf_link = (
        f'<p><a href="{pdf_url}">Download PDF</a></p>'
    ) if pdf_url else ""

    html = f"""
<html><body style="font-family:sans-serif;color:#14171f;max-width:600px;margin:auto">
  <h2 style="color:#2f6fed">Invoice #{invoice_number}</h2>
  <p>Hi {client_name},</p>
  <p>Please find your invoice from <strong>{sender_name}</strong> for
     <strong>{sym}{amount:,.2f}</strong> attached.</p>
  {due_line}
  {pay_btn}
  {pdf_link}
  {"<p>" + notes + "</p>" if notes else ""}
  <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0">
  <p style="color:#73798a;font-size:12px">Sent via Kora (kora.app)</p>
</body></html>
"""

    message_id = _send(
        from_addr=_DEFAULT_FROM_EMAIL,
        to=[client_email],
        subject=f"Invoice #{invoice_number} from {sender_name} — {sym}{amount:,.2f}",
        html=html,
    )

    latency_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
    agent_logger.log_action(
        user_id=user_id,
        agent_type="email_delivery",
        action=f"Sent invoice #{invoice_number} to {client_email}",
        input={"invoice_id": invoice_id, "to": client_email},
        output={"message_id": message_id, "delivered": message_id is not None},
        latency_ms=latency_ms,
        triggered_by="user",
        source_record_type="invoice",
        source_record_id=invoice_id,
    )
    return message_id


def send_follow_up_email(
    *,
    user_id: str,
    invoice_id: str,
    invoice_number: str,
    client_name: str,
    client_email: str,
    sender_name: str,
    amount: float,
    currency: str,
    due_date: str | None,
    days_overdue: int,
    payment_link: str | None,
    body_text: str,
) -> str | None:
    """Send an AI-drafted follow-up. Returns message_id or None."""
    start = datetime.now(timezone.utc)
    sym = _currency_sym(currency)

    pay_btn = (
        f'<p><a href="{payment_link}" style="background:#2f6fed;color:#fff;padding:10px 20px;'
        f'text-decoration:none;border-radius:6px;font-weight:bold;display:inline-block;">'
        f"Pay Now</a></p>"
    ) if payment_link else ""

    html = f"""
<html><body style="font-family:sans-serif;color:#14171f;max-width:600px;margin:auto">
  <h2 style="color:#c72e2e">Payment Reminder — Invoice #{invoice_number}</h2>
  <p>{body_text.replace(chr(10), "<br/>")}</p>
  {pay_btn}
  <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0">
  <p style="color:#73798a;font-size:12px">Sent via Kora (kora.app)</p>
</body></html>
"""

    overdue_label = f"{days_overdue}d overdue" if days_overdue > 0 else "due soon"
    message_id = _send(
        from_addr=_DEFAULT_FROM_EMAIL,
        to=[client_email],
        subject=f"Payment reminder — Invoice #{invoice_number} ({overdue_label})",
        html=html,
    )

    latency_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
    agent_logger.log_action(
        user_id=user_id,
        agent_type="invoice_follow_up",
        action=f"Sent follow-up for invoice #{invoice_number} ({overdue_label})",
        input={"invoice_id": invoice_id, "days_overdue": days_overdue, "to": client_email},
        output={"message_id": message_id, "delivered": message_id is not None},
        latency_ms=latency_ms,
        triggered_by="scheduler",
        source_record_type="invoice",
        source_record_id=invoice_id,
    )
    return message_id


def send_morning_digest(
    *,
    user_id: str,
    user_email: str,
    user_name: str,
    overdue_count: int,
    overdue_total: float,
    due_soon_count: int,
    currency: str,
    digest_html: str,
) -> str | None:
    """Send the morning digest to the freelancer. Returns message_id or None."""
    start = datetime.now(timezone.utc)
    sym = _currency_sym(currency)
    subject = (
        f"Your morning digest — {overdue_count} overdue ({sym}{overdue_total:,.2f})"
        if overdue_count
        else f"Your morning digest — {due_soon_count} due soon"
    )

    html = f"""
<html><body style="font-family:sans-serif;color:#14171f;max-width:600px;margin:auto">
  <h2 style="color:#2f6fed">Good morning, {user_name} 👋</h2>
  {digest_html}
  <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0">
  <p style="color:#73798a;font-size:12px">Kora back-office digest · <a href="https://kora.app">kora.app</a></p>
</body></html>
"""

    message_id = _send(
        from_addr=EMAIL_FROM["alerts"],
        to=[user_email],
        subject=subject,
        html=html,
    )

    latency_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
    agent_logger.log_action(
        user_id=user_id,
        agent_type="morning_digest",
        action=f"Sent morning digest ({overdue_count} overdue, {due_soon_count} due soon)",
        input={"overdue_count": overdue_count, "due_soon_count": due_soon_count},
        output={"message_id": message_id, "delivered": message_id is not None},
        latency_ms=latency_ms,
        triggered_by="scheduler",
    )
    return message_id


def _send(*, from_addr: str, to: list[str], subject: str, html: str) -> str | None:
    """Dispatch via Resend. Returns message_id on success, None when not configured."""
    r = _resend_client()
    if r is None:
        return None
    try:
        resp = r.Emails.send({
            "from": from_addr,
            "to": to,
            "subject": subject,
            "html": html,
        })
        return resp.get("id") if isinstance(resp, dict) else getattr(resp, "id", None)
    except Exception:
        return None


def _currency_sym(currency: str) -> str:
    return {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹", "CAD": "CA$", "AUD": "A$"}.get(currency, currency + " ")
