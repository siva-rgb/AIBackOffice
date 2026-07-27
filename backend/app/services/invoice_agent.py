from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from .. import store
from ..models import Contract
from ..utils.security import safe_sanitize
from . import agent_logger
from .cross_module import on_invoice_demand_sent, reconcile_payments
from .vertex_ai import generate_with_retry, get_ai

# Follow-up cadence after due date (SKILL.md modules.md#invoices):
#   attempt 1 (gentle) at +3 days, 2 (firm) at +7, 3 (final) at +14.
# No more auto follow-ups after +21 days.
_SCHEDULE = {1: 3, 2: 7, 3: 14}
_MAX_AUTO_DAYS = 21
_LABELS = {1: "gentle reminder", 2: "firm follow-up", 3: "final notice"}


@dataclass
class FollowUpRunResult:
    scanned: int = 0
    sent: int = 0
    details: list[dict] = field(default_factory=list)


def _days_overdue(due_date: str) -> int:
    return (date.today() - date.fromisoformat(due_date)).days


def _writing_brief(user) -> str:
    """Compact brand-voice/positioning brief so follow-up & demand emails match
    the owner's brand. Returns "" for day-1 users (safe to always include)."""
    if not user:
        return ""
    from .profile_context import build_profile_brief

    return build_profile_brief(
        getattr(user, "profile", None),
        "email_draft",
        business_name=getattr(user, "business_name", None),
        max_chars=400,
    )


# --- Contract grounding (cross-module intelligence) -------------------------
def find_payment_clause(content_md: str | None) -> str | None:
    """Extract the Payment section from a generated contract's Markdown so the
    follow-up / demand agents can quote the actual agreed terms."""
    if not content_md:
        return None
    # Match a heading whose text mentions payment, capture until the next heading.
    m = re.search(
        r"^#{1,6}\s*[\d.\s]*[^\n]*\bpayment\b[^\n]*\n(?P<body>.*?)(?=\n#{1,6}\s|\Z)",
        content_md,
        re.I | re.M | re.S,
    )
    if not m:
        return None
    body = m.group("body")
    # Strip markdown emphasis/bullets and collapse whitespace.
    body = re.sub(r"[*_`>#]+", "", body)
    body = re.sub(r"^\s*[-•]\s*", "", body, flags=re.M)
    body = re.sub(r"\s+", " ", body).strip()
    if len(body) > 600:
        body = body[:597].rsplit(" ", 1)[0] + "…"
    return body or None


def contract_context(user_id: str, contract_id: str | None) -> dict:
    """Build the contract fields the email/letter agents accept. Empty dict when
    there's no linked contract or no extractable payment clause."""
    if not contract_id:
        return {}
    contract: Contract | None = store.get_contract(user_id, contract_id)
    if not contract:
        return {}
    clause = find_payment_clause(contract.content_md)
    if not clause:
        return {}
    label = (contract.title or (contract.type or "agreement").replace("_", " ")).strip()
    ctx = {
        "contract_payment_clause": clause,
        "contract_reference": f"the {label}",
        "contract_type": (contract.type or "agreement").replace("_", " "),
    }
    if contract.signed_at:
        ctx["contract_date"] = contract.signed_at[:10]
    return ctx


def _due_attempt(follow_up_count: int, days_overdue: int) -> int | None:
    if days_overdue > _MAX_AUTO_DAYS:
        return None
    nxt = follow_up_count + 1
    if nxt > 3:
        return None
    return nxt if days_overdue >= _SCHEDULE[nxt] else None


def run_follow_up_agent(user_id: str, triggered_by: str = "scheduler") -> FollowUpRunResult:
    user = store.get_user(user_id)
    ai = get_ai()
    # Reconcile incoming payments FIRST so we never chase an invoice the client
    # has already paid (the status flips to 'paid' and drops out of the scan).
    try:
        reconcile_payments(user_id, triggered_by=triggered_by)
    except Exception as exc:  # reconciliation must not block dunning
        print(f"[follow-up] reconciliation skipped: {exc}")
    invoices = [i for i in store.list_invoices(user_id) if i.status in ("sent", "overdue")]
    result = FollowUpRunResult(scanned=len(invoices))

    for inv in invoices:
        days = _days_overdue(inv.due_date)
        if days < 0:
            continue
        attempt = _due_attempt(inv.follow_up_count, days)
        if not attempt:
            continue

        params = {
            "attempt": attempt,
            "business_name": user.business_name if user else "Your business",
            "client_name": safe_sanitize(inv.client_name),
            "invoice_number": inv.invoice_number,
            "currency": inv.currency,
            "amount": inv.total,
            "due_date": inv.due_date,
            "days_overdue": days,
            "payment_link": inv.payment_link,
        }
        # On the final notice, ground the email in the linked contract's terms.
        if attempt == 3:
            params.update(contract_context(user_id, inv.contract_id))
        call = generate_with_retry(lambda: ai.draft_follow_up_email(params))

        store.update_invoice(
            user_id,
            inv.id,
            {
                "status": "overdue",
                "follow_up_count": inv.follow_up_count + 1,
                "last_follow_up_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        agent_logger.log_action(
            user_id=user_id,
            agent_type="invoice_follow_up",
            action=f"Sent {_LABELS[attempt]} for {inv.invoice_number} to {inv.client_name}",
            input={"invoiceNumber": inv.invoice_number, "clientEmail": inv.client_email, "daysOverdue": days, "attempt": attempt},
            output={"subject": call.data["subject"], "body": call.data["body"], "delivered": True},
            model_used=call.model_used,
            tokens_used=call.tokens_used,
            latency_ms=call.latency_ms,
            cost_usd=call.cost_usd,
            triggered_by=triggered_by,
            source_record_type="invoice",
            source_record_id=inv.id,
        )

        result.sent += 1
        result.details.append(
            {
                "invoiceNumber": inv.invoice_number,
                "attempt": attempt,
                "subject": call.data["subject"],
            }
        )

    return result


def _current_client_email(user_id: str, inv) -> str | None:
    """Resolve the recipient email, preferring the linked client's CURRENT email
    (matched by client name — Kora has no invoice→client FK) over the invoice's
    stored snapshot. This way, editing a client's email updates where future
    demands/follow-ups are sent, instead of using the address frozen on the
    invoice at creation time."""
    try:
        name = (getattr(inv, "client_name", "") or "").strip().lower()
        if name:
            for c in store.list_clients(user_id):
                if (c.name or "").strip().lower() == name and c.email:
                    return c.email
    except Exception:
        pass
    return getattr(inv, "client_email", None)


def _maybe_send(user_id: str, inv, subject: str, body: str, deliver: bool):
    """Deliver a drafted invoice email to the client through the connected Gmail
    when ``deliver`` is True. Returns (delivered, gmail_message_id, note). Never
    raises — any failure (not connected, no client email, API error) degrades to
    draft-only with an explanatory note, so approving a task never hard-fails."""
    if not deliver:
        return False, None, None
    to_email = _current_client_email(user_id, inv)
    if not to_email:
        return False, None, "No client email on file — drafted only (not sent)."
    try:
        from .gmail_agent import is_gmail_connected, send_via_gmail

        if not is_gmail_connected(user_id):
            return False, None, ("Google account not connected — drafted only. " "Connect Gmail in Settings to send.")
        msg_id = send_via_gmail(user_id, to_email, inv.client_name, subject, body)
        return True, msg_id, f"Sent to {to_email} via Gmail."
    except Exception as exc:
        return False, None, f"Send failed — drafted only ({exc})."


def send_follow_up_for(user_id: str, invoice_id: str, triggered_by: str = "user", deliver: bool = False) -> dict:
    """Send a single follow-up for one invoice (used when the owner approves a
    supervisor task). Drafts the next-attempt email, grounds the final notice in
    the contract, advances the cadence, and logs it. When ``deliver`` is True the
    drafted email is actually sent to the client via the connected Gmail."""
    user = store.get_user(user_id)
    inv = store.get_invoice(user_id, invoice_id)
    if not inv:
        raise ValueError("Invoice not found")
    if inv.status in ("paid", "cancelled", "draft"):
        raise ValueError("Invoice is not awaiting payment")

    days = max(0, _days_overdue(inv.due_date))
    attempt = min(inv.follow_up_count + 1, 3)
    params = {
        "attempt": attempt,
        "business_name": user.business_name if user else "Your business",
        "client_name": safe_sanitize(inv.client_name),
        "invoice_number": inv.invoice_number,
        "currency": inv.currency,
        "amount": inv.total,
        "due_date": inv.due_date,
        "days_overdue": days,
        "payment_link": inv.payment_link,
    }
    if attempt == 3:
        params.update(contract_context(user_id, inv.contract_id))
    params["business_context"] = _writing_brief(user)
    call = generate_with_retry(lambda: ai_draft_follow_up(params))

    delivered, gmail_msg_id, delivery_note = _maybe_send(
        user_id,
        inv,
        call.data["subject"],
        call.data["body"],
        deliver,
    )
    verb = "Sent" if delivered else "Drafted"

    store.update_invoice(
        user_id,
        inv.id,
        {
            "status": "overdue",
            "follow_up_count": inv.follow_up_count + 1,
            "last_follow_up_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    agent_logger.log_action(
        user_id=user_id,
        agent_type="invoice_follow_up",
        action=f"{verb} {_LABELS[attempt]} for {inv.invoice_number} to {inv.client_name}",
        input={
            "invoiceNumber": inv.invoice_number,
            "clientEmail": inv.client_email,
            "daysOverdue": days,
            "attempt": attempt,
            "approvedBySupervisor": True,
        },
        output={"subject": call.data["subject"], "body": call.data["body"], "delivered": delivered, "gmailMessageId": gmail_msg_id},
        model_used=call.model_used,
        tokens_used=call.tokens_used,
        latency_ms=call.latency_ms,
        cost_usd=call.cost_usd,
        triggered_by=triggered_by,
        source_record_type="invoice",
        source_record_id=inv.id,
    )
    return {
        "subject": call.data["subject"],
        "body": call.data["body"],
        "attempt": attempt,
        "delivered": delivered,
        "gmailMessageId": gmail_msg_id,
        "note": delivery_note or f"{_LABELS[attempt].capitalize()} for {inv.invoice_number} drafted (not sent).",
    }


def ai_draft_follow_up(params: dict):
    return get_ai().draft_follow_up_email(params)


def generate_demand_letter(user_id: str, invoice_id: str, triggered_by: str = "user", deliver: bool = False) -> dict:
    """Cross-module killer feature: draft a formal payment demand for an overdue
    invoice, grounded in the linked contract's payment clause when one exists.

    When ``deliver`` is True (the owner approved the manager task), the drafted
    letter is actually emailed to the client via the connected Gmail. Otherwise it
    is draft-only (preview button / bulk paths) — so nothing is sent by surprise."""
    user = store.get_user(user_id)
    inv = store.get_invoice(user_id, invoice_id)
    if not inv:
        raise ValueError("Invoice not found")
    if inv.status in ("paid", "cancelled", "draft"):
        raise ValueError("Demand letters are only for sent or overdue invoices")

    days = _days_overdue(inv.due_date)
    ctx = contract_context(user_id, inv.contract_id)

    params = {
        "business_name": (user.business_name if user else None) or "Your business",
        "business_email": user.email if user else None,
        "client_name": safe_sanitize(inv.client_name),
        "client_email": inv.client_email,
        "invoice_number": inv.invoice_number,
        "invoice_date": (inv.sent_at or inv.created_at or "")[:10] or None,
        "due_date": inv.due_date,
        "currency": inv.currency,
        "amount": inv.total,
        "days_overdue": max(0, days),
        "follow_up_count": inv.follow_up_count,
        "today": date.today().isoformat(),
        "business_context": _writing_brief(user),
        **ctx,
    }

    ai = get_ai()
    call = generate_with_retry(lambda: ai.generate_payment_demand(params))
    grounded = bool(ctx)

    # Delivery — only when the owner approved the action (deliver=True).
    delivered, gmail_msg_id, delivery_note = _maybe_send(
        user_id,
        inv,
        call.data["subject"],
        call.data["body"],
        deliver,
    )
    verb = "Sent" if delivered else "Drafted"
    kind = "contract-grounded payment demand" if grounded else "payment demand"

    agent_logger.log_action(
        user_id=user_id,
        # Logged as cross_module when contract-grounded — this is the agent
        # reading a contract to act on an invoice (the killer feature).
        agent_type="cross_module" if grounded else "invoice_follow_up",
        action=f"{verb} {kind} for {inv.invoice_number} ({inv.client_name})",
        input={"invoiceNumber": inv.invoice_number, "daysOverdue": max(0, days), "contractGrounded": grounded, "contractId": inv.contract_id},
        output={"subject": call.data["subject"], "body": call.data["body"], "delivered": delivered, "gmailMessageId": gmail_msg_id},
        model_used=call.model_used,
        tokens_used=call.tokens_used,
        latency_ms=call.latency_ms,
        cost_usd=call.cost_usd,
        triggered_by="cross_module" if grounded else triggered_by,
        source_record_type="invoice",
        source_record_id=inv.id,
    )

    # Chain: update escalation state so supervisor knows demand was sent.
    try:
        on_invoice_demand_sent(user_id, inv.id, inv.invoice_number)
    except Exception as exc:
        print(f"[invoice_agent] escalation chain after demand failed: {exc}")

    return {
        "subject": call.data["subject"],
        "body": call.data["body"],
        "contractGrounded": grounded,
        "contractClause": ctx.get("contract_payment_clause"),
        "daysOverdue": max(0, days),
        "delivered": delivered,
        "gmailMessageId": gmail_msg_id,
        "note": delivery_note or (f"Payment demand for {inv.invoice_number} drafted (not sent)."),
    }
