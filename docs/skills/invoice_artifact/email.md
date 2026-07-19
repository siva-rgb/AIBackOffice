# Invoice Enhancements — Email Sending Reference

Wire the Resend SDK so invoices and follow-ups actually get delivered.
This makes the autonomous agent story real.

---

## Resend email service

```python
# backend/app/services/email_service.py
"""
Email sending via Resend SDK.
All emails are logged to agent_logs.
Never send without logging. Never send from a no-reply address.
"""
import os
import resend
from datetime import datetime
from app.services.agent_logger import log_agent_action
from app.models import AgentType

# Initialize Resend
resend.api_key = os.environ.get("RESEND_API_KEY", "")

# Sender addresses — use a dedicated subdomain for deliverability
# Set up DNS records (SPF, DKIM, DMARC) on mail.kora.app before sending
EMAIL_FROM = {
    "transactional": "Kora <hello@mail.kora.app>",
    "invoices": "Kora Invoices <invoices@mail.kora.app>",
    "alerts": "Kora <alerts@mail.kora.app>",
}


async def send_invoice_email(
    user_id: str,
    invoice: dict,
    user_profile: dict,
    pdf_signed_url: str = None,
) -> dict:
    """
    Send an invoice email to the client with optional PDF attachment.
    Returns {success: bool, message_id: str|None, error: str|None}.
    """
    start = datetime.utcnow()

    client_email = invoice.get("client_email")
    if not client_email:
        return {"success": False, "error": "No client email on invoice"}

    client_name = invoice.get("client_name", "")
    invoice_number = invoice.get("invoice_number", "")
    currency = invoice.get("currency", "USD")
    symbol = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹"}.get(currency, currency + " ")
    total = invoice.get("total", 0)
    due_date = invoice.get("due_date", "")
    sender_name = user_profile.get("business_name") or user_profile.get("full_name", "")

    subject = f"Invoice #{invoice_number} from {sender_name} — {symbol}{total:,.2f}"

    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #111; font-weight: 400;">Invoice #{invoice_number}</h2>
        <p>Hi {client_name.split()[0] if client_name else 'there'},</p>
        <p>Please find your invoice from <strong>{sender_name}</strong>.</p>

        <div style="background: #f8f9fa; border-radius: 8px; padding: 20px; margin: 20px 0;">
            <table style="width: 100%; font-size: 14px;">
                <tr>
                    <td style="color: #666;">Invoice number</td>
                    <td style="text-align: right; font-weight: 500;">#{invoice_number}</td>
                </tr>
                <tr>
                    <td style="color: #666;">Amount due</td>
                    <td style="text-align: right; font-weight: 600; font-size: 18px;">{symbol}{total:,.2f}</td>
                </tr>
                <tr>
                    <td style="color: #666;">Due date</td>
                    <td style="text-align: right;">{due_date}</td>
                </tr>
                {f'<tr><td style="color: #666;">Payment terms</td><td style="text-align: right;">{invoice.get("payment_terms", "")}</td></tr>' if invoice.get("payment_terms") else ''}
            </table>
        </div>

        {f'<p><a href="{pdf_signed_url}" style="display:inline-block;padding:10px 24px;background:#111;color:#fff;text-decoration:none;border-radius:6px;">Download Invoice PDF</a></p>' if pdf_signed_url else ''}

        <p style="color: #666; font-size: 13px;">
            If you have any questions, reply directly to this email.
        </p>
        <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">
        <p style="color: #999; font-size: 11px;">
            Sent by {sender_name} via <a href="https://kora.app" style="color: #999;">Kora</a>
        </p>
    </div>
    """

    text_body = f"""Invoice #{invoice_number} from {sender_name}

Amount due: {symbol}{total:,.2f}
Due date: {due_date}
{f'Payment terms: {invoice.get("payment_terms", "")}' if invoice.get("payment_terms") else ''}

{f'Download PDF: {pdf_signed_url}' if pdf_signed_url else ''}

If you have any questions, reply directly to this email.
"""

    try:
        response = resend.Emails.send({
            "from": EMAIL_FROM["invoices"],
            "to": [client_email],
            "subject": subject,
            "html": html_body,
            "text": text_body,
            "reply_to": user_profile.get("email", ""),
        })

        message_id = response.get("id") if isinstance(response, dict) else getattr(response, "id", None)
        latency_ms = int((datetime.utcnow() - start).total_seconds() * 1000)

        log_agent_action(
            user_id=user_id,
            agent_type=AgentType.invoice_follow_up,
            action=f"Sent invoice #{invoice_number} to {client_email}",
            input_data={"invoice_id": invoice.get("id"), "to": client_email},
            output_data={"message_id": message_id, "delivered": True},
            latency_ms=latency_ms,
            triggered_by="user",
        )

        return {"success": True, "message_id": message_id}

    except Exception as e:
        latency_ms = int((datetime.utcnow() - start).total_seconds() * 1000)
        log_agent_action(
            user_id=user_id,
            agent_type=AgentType.invoice_follow_up,
            action=f"Failed to send invoice #{invoice_number} to {client_email}",
            input_data={"invoice_id": invoice.get("id"), "to": client_email},
            output_data={"error": str(e)},
            latency_ms=latency_ms,
            triggered_by="user",
            status="error",
        )
        return {"success": False, "error": str(e)}


async def send_follow_up_email(
    user_id: str,
    invoice: dict,
    follow_up_stage: int,   # 1 = day 3, 2 = day 7, 3 = day 14
    email_body_html: str,   # AI-generated follow-up body
    email_body_text: str,
    email_subject: str,
    user_profile: dict,
) -> dict:
    """
    Send an AI-drafted follow-up email for an overdue invoice.
    Called from the invoice follow-up agent after HITL approval.
    """
    start = datetime.utcnow()

    client_email = invoice.get("client_email")
    if not client_email:
        return {"success": False, "error": "No client email"}

    try:
        response = resend.Emails.send({
            "from": EMAIL_FROM["invoices"],
            "to": [client_email],
            "subject": email_subject,
            "html": email_body_html,
            "text": email_body_text,
            "reply_to": user_profile.get("email", ""),
        })

        message_id = response.get("id") if isinstance(response, dict) else getattr(response, "id", None)
        latency_ms = int((datetime.utcnow() - start).total_seconds() * 1000)

        log_agent_action(
            user_id=user_id,
            agent_type=AgentType.invoice_follow_up,
            action=f"Sent follow-up #{follow_up_stage} for invoice #{invoice.get('invoice_number', '')} to {client_email}",
            input_data={
                "invoice_id": invoice.get("id"),
                "to": client_email,
                "follow_up_stage": follow_up_stage,
            },
            output_data={"message_id": message_id, "delivered": True},
            latency_ms=latency_ms,
            triggered_by="scheduler",
        )

        # Update invoice follow-up tracking
        from app import store
        store.update_invoice(user_id, invoice["id"], {
            "follow_up_count": follow_up_stage,
            "last_follow_up_at": datetime.utcnow().isoformat(),
        })

        return {"success": True, "message_id": message_id}

    except Exception as e:
        latency_ms = int((datetime.utcnow() - start).total_seconds() * 1000)
        log_agent_action(
            user_id=user_id,
            agent_type=AgentType.invoice_follow_up,
            action=f"Follow-up email failed for invoice #{invoice.get('invoice_number', '')}",
            input_data={"invoice_id": invoice.get("id")},
            output_data={"error": str(e)},
            latency_ms=latency_ms,
            triggered_by="scheduler",
            status="error",
        )
        return {"success": False, "error": str(e)}


async def send_morning_digest(
    user_id: str,
    user_email: str,
    briefing: dict,
    user_name: str = "",
) -> dict:
    """Send the morning briefing as an email digest."""
    headline = briefing.get("headline", "Your morning briefing is ready.")
    summary = briefing.get("two_sentence_summary", "")
    focus = briefing.get("focus_today", [])

    focus_html = "".join(f"<li>{item}</li>" for item in focus) if focus else ""

    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #111; font-weight: 400;">Good morning{f', {user_name.split()[0]}' if user_name else ''}</h2>
        <p style="font-size: 16px; line-height: 1.6;"><strong>{headline}</strong></p>
        <p style="color: #444; line-height: 1.6;">{summary}</p>
        {f'<h3 style="font-size: 14px; color: #666;">Focus today</h3><ol style="color: #333;">{focus_html}</ol>' if focus_html else ''}
        <p style="margin-top: 30px;">
            <a href="https://kora.app/kora" style="display:inline-block;padding:10px 24px;background:#111;color:#fff;text-decoration:none;border-radius:6px;">Open Kora</a>
        </p>
        <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">
        <p style="color: #999; font-size: 11px;">
            Your AI business partner — <a href="https://kora.app" style="color: #999;">kora.app</a>
        </p>
    </div>
    """

    try:
        response = resend.Emails.send({
            "from": EMAIL_FROM["alerts"],
            "to": [user_email],
            "subject": f"Kora: {headline[:80]}",
            "html": html_body,
        })
        message_id = response.get("id") if isinstance(response, dict) else getattr(response, "id", None)
        return {"success": True, "message_id": message_id}
    except Exception as e:
        return {"success": False, "error": str(e)}
```

---

## Wire into invoice router

```python
# In routers/invoices.py — add a send endpoint:

@router.post("/{invoice_id}/send")
async def send_invoice(invoice_id: str, user=Depends(get_current_user)):
    """Generate PDF (if needed) + email the invoice to the client."""
    from app.services.invoice_pdf import generate_invoice_pdf
    from app.services.email_service import send_invoice_email
    from app.services.storage import get_signed_url

    invoice = store.get_invoice(user["id"], invoice_id)
    if not invoice:
        raise HTTPException(404, "Invoice not found")

    user_data = store.get_user(user["id"])
    profile = user_data.get("profile") or {}

    # Generate PDF if not already done
    pdf_path = invoice.get("pdf_path")
    if not pdf_path:
        pdf_path = await generate_invoice_pdf(user["id"], invoice_id)

    # Get a signed URL for the PDF download link in the email
    try:
        pdf_url = get_signed_url(
            user["id"], pdf_path,
            expiry_minutes=72 * 60,  # 72 hours for email link
            filename_override=f"invoice-{invoice.get('invoice_number', '')}.pdf",
        )
    except Exception:
        pdf_url = None

    # Send the email
    result = await send_invoice_email(
        user_id=user["id"],
        invoice=invoice,
        user_profile={**profile, "email": user_data.get("email", "")},
        pdf_signed_url=pdf_url,
    )

    if result["success"]:
        # Update invoice status + store email ID
        store.update_invoice(user["id"], invoice_id, {
            "status": "sent",
            "sent_at": datetime.utcnow().isoformat(),
            "email_message_id": result.get("message_id"),
        })

    return result
```

---

## Wire into follow-up agent

In the existing invoice follow-up logic (wherever AI-drafted follow-ups go through
HITL approval → then execute), replace the "log but don't send" pattern with actual sending:

```python
# In the follow-up execution handler (after user approves the manager_task):

from app.services.email_service import send_follow_up_email

# The task payload contains the AI-drafted email body
payload = task.get("payload", {})
invoice = store.get_invoice(user_id, payload["invoice_id"])
user_data = store.get_user(user_id)
profile = user_data.get("profile") or {}

result = await send_follow_up_email(
    user_id=user_id,
    invoice=invoice,
    follow_up_stage=payload.get("follow_up_stage", 1),
    email_body_html=payload.get("email_html", ""),
    email_body_text=payload.get("email_text", ""),
    email_subject=payload.get("subject", ""),
    user_profile={**profile, "email": user_data.get("email", "")},
)
```

---

## Environment variables

```bash
# Add to .env:
RESEND_API_KEY=re_xxxxxxxxxxxx           # from resend.com dashboard
FROM_EMAIL=hello@mail.kora.app           # your verified sending domain

# Pip dependency (should already be in requirements.txt):
# resend>=2.0.0
```

---

## DNS records (must set up before first send)

Add these to your domain registrar (Cloudflare, Namecheap, etc.)
on the subdomain `mail.kora.app`:

```
SPF:   TXT record on mail.kora.app → v=spf1 include:_spf.resend.com ~all
DKIM:  TXT record (generated in Resend dashboard → Domain settings)
DMARC: TXT record on _dmarc.mail.kora.app → v=DMARC1; p=quarantine; rua=mailto:dmarc@kora.app; pct=100
```

Verify in Resend dashboard before sending. Without these, emails land in spam.
