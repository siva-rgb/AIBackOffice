from __future__ import annotations

import base64
import html as _html
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from ..config import settings
from . import agent_logger
from .google_auth import get_user_credentials


def _db():
    from supabase import create_client
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)


def _text_to_html(text: str) -> str:
    """Minimal, injection-safe text→HTML for the alternative MIME part."""
    escaped = _html.escape(text or "")
    return (
        '<div style="white-space:pre-wrap;font-family:Arial,Helvetica,sans-serif;'
        'font-size:14px;line-height:1.5;color:#111">'
        + escaped.replace("\n", "<br>")
        + "</div>"
    )


def is_gmail_connected(user_id: str) -> bool:
    """True when the user has a usable (decryptable, refreshable) Google token."""
    try:
        return get_user_credentials(user_id) is not None
    except Exception:
        return False


def send_via_gmail(
    user_id: str,
    to_email: str,
    to_name: str,
    subject: str,
    body_text: str,
    body_html: str = "",
) -> str:
    """Send an email immediately through the user's connected Gmail and return the
    Gmail message id. Raises ValueError if Google isn't connected. Logging is left
    to the caller so the action can carry domain context (e.g. the invoice).
    Used by the invoice follow-up / demand-letter approval path — the human
    approval of the manager_task IS the HITL gate, so this sends directly."""
    creds = get_user_credentials(user_id)
    if not creds:
        raise ValueError("Google account not connected")

    from googleapiclient.discovery import build
    service = build("gmail", "v1", credentials=creds)

    msg = MIMEMultipart("alternative")
    msg["To"] = f"{to_name} <{to_email}>" if to_name else to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body_text or "", "plain"))
    msg.attach(MIMEText(body_html or _text_to_html(body_text or ""), "html"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    result = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    return result.get("id")


def queue_gmail_send(
    user_id: str,
    to_email: str,
    to_name: str,
    subject: str,
    body_html: str,
    body_text: str,
    context: str,
    related_client_id: str | None = None,
    related_meeting_id: str | None = None,
) -> None:
    """Insert a send_email_gmail manager_task for HITL approval. Never sends directly."""
    if not settings.SUPABASE_URL:
        return
    db = _db()
    conn_rows = db.table("google_connections").select("google_email").eq(
        "user_id", user_id).execute().data
    from_email = conn_rows[0]["google_email"] if conn_rows else "your Gmail"
    db.table("manager_tasks").insert({
        "user_id": user_id,
        "kind": "send_email_gmail",
        "title": f"Send email to {to_name}: {subject}",
        "rationale": context,
        "severity": "info",
        "status": "proposed",
        "payload": {
            "to_email": to_email, "to_name": to_name,
            "subject": subject, "body_html": body_html,
            "body_text": body_text, "from_email": from_email,
            "related_client_id": related_client_id,
            "related_meeting_id": related_meeting_id,
        },
        "source_record_type": "meeting" if related_meeting_id else "client",
        "source_record_id": related_meeting_id or related_client_id,
    }).execute()


def execute_gmail_send(user_id: str, task_payload: dict) -> bool:
    """Execute an approved send_email_gmail task. Called only from approve_task."""
    start = datetime.now(timezone.utc)
    creds = get_user_credentials(user_id)
    if not creds:
        raise ValueError("Google account not connected")

    from googleapiclient.discovery import build
    service = build("gmail", "v1", credentials=creds)

    msg = MIMEMultipart("alternative")
    msg["To"] = f"{task_payload['to_name']} <{task_payload['to_email']}>"
    msg["Subject"] = task_payload["subject"]
    msg.attach(MIMEText(task_payload.get("body_text", ""), "plain"))
    msg.attach(MIMEText(task_payload.get("body_html", ""), "html"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    result = service.users().messages().send(
        userId="me", body={"raw": raw}
    ).execute()

    latency_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
    agent_logger.log_action(
        user_id=user_id,
        agent_type="gmail_agent",
        action=f"Sent email to {task_payload['to_email']}: {task_payload['subject']}",
        input={"to": task_payload["to_email"], "subject": task_payload["subject"]},
        output={"gmailMessageId": result.get("id")},
        latency_ms=latency_ms,
        triggered_by="user",
        source_record_type="client",
        source_record_id=task_payload.get("related_client_id"),
    )
    return True
