"""
Owner notifications — email the business owner (not clients): the daily digest
and critical alerts.

Delivery order: the owner's connected Gmail first (zero extra setup), then Resend
as a fallback, else a graceful no-op. Never raises into the caller.
"""
from __future__ import annotations

import html as _html

from .. import store
from . import agent_logger


def _text_to_html(text: str) -> str:
    esc = _html.escape(text or "")
    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;'
        'line-height:1.6;color:#14171f;max-width:600px">'
        + esc.replace("\n", "<br>")
        + "</div>"
    )


def _pref(user, key: str, default: bool = True) -> bool:
    """Read an owner notification preference from the profile (dict or model),
    defaulting to on so existing users keep getting emails until they opt out."""
    prof = getattr(user, "profile", None) if user else None
    if prof is None:
        return default
    if isinstance(prof, dict):
        val = prof.get(key)
    else:
        val = getattr(prof, key, None)
    return default if val is None else bool(val)


def _log(user_id: str, category: str, subject: str, to_email: str, via: str, msg_id) -> None:
    try:
        agent_logger.log_action(
            user_id=user_id,
            agent_type="email_delivery",
            action=f"Emailed owner ({category}): {subject}",
            input={"to": to_email, "category": category},
            output={"via": via, "messageId": msg_id, "delivered": bool(msg_id)},
            triggered_by="scheduler",
        )
    except Exception:
        pass


def send_owner_email(user_id: str, subject: str, body_text: str,
                     body_html: str = "", category: str = "notification") -> dict:
    """Email the owner. Gmail → Resend → no-op. Returns a small status dict."""
    user = store.get_user(user_id)
    to_email = getattr(user, "email", None) if user else None
    to_name = (getattr(user, "full_name", None) if user else None) or ""
    if not to_email:
        return {"sent": False, "reason": "no owner email on file"}

    html = body_html or _text_to_html(body_text)

    # 1) Owner's connected Gmail (sends to their own inbox).
    try:
        from .gmail_agent import is_gmail_connected, send_via_gmail
        if is_gmail_connected(user_id):
            msg_id = send_via_gmail(user_id, to_email, to_name, subject, body_text, html)
            _log(user_id, category, subject, to_email, "gmail", msg_id)
            return {"sent": True, "via": "gmail", "id": msg_id}
    except Exception as exc:
        print(f"[owner-notify] gmail send failed: {exc}")

    # 2) Resend fallback.
    try:
        from .email_service import EMAIL_FROM, _send
        msg_id = _send(from_addr=EMAIL_FROM["alerts"], to=[to_email], subject=subject, html=html)
        if msg_id:
            _log(user_id, category, subject, to_email, "resend", msg_id)
            return {"sent": True, "via": "resend", "id": msg_id}
    except Exception as exc:
        print(f"[owner-notify] resend send failed: {exc}")

    return {"sent": False, "reason": "no delivery channel (connect Gmail or set RESEND_API_KEY)"}


def send_daily_digest(user_id: str, result: dict) -> dict:
    """Email the owner their Manager daily digest, composed from a run_supervisor result."""
    if not _pref(store.get_user(user_id), "notify_daily_digest"):
        return {"sent": False, "reason": "daily digest disabled by owner"}
    b = (result or {}).get("briefing") or {}
    status = b.get("statusLine") or "Here's your business snapshot."
    summary = b.get("summary") or ""
    priorities = b.get("priorities") or []
    auto = (result or {}).get("autoActions") or []
    pending = (result or {}).get("pendingTasks") or []

    lines = [status, ""]
    if summary:
        lines += [summary, ""]
    if priorities:
        lines.append("Top priorities:")
        for p in priorities[:5]:
            lines.append(f"- {p.get('title') if isinstance(p, dict) else p}")
        lines.append("")
    if auto:
        lines.append(f"Handled automatically: {len(auto)} item(s).")
    if pending:
        lines.append(f"Awaiting your approval: {len(pending)} item(s) — open Kora to review.")

    text = "\n".join(lines).strip()
    return send_owner_email(user_id, "Your Kora daily digest", text, category="daily_digest")


def notify_critical_alert(user_id: str, *, title: str, body: str, action_url: str | None = None) -> dict:
    """Email the owner about a fresh critical alert. Callers already dedupe the
    underlying alert, so this only fires when a new one is raised."""
    if not _pref(store.get_user(user_id), "notify_critical_alerts"):
        return {"sent": False, "reason": "critical alerts disabled by owner"}
    text = f"{title}\n\n{body}"
    if action_url:
        text += f"\n\nOpen Kora: {action_url}"
    return send_owner_email(user_id, f"⚠️ Kora: {title}", text, category="critical_alert")
