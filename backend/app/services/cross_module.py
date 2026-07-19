from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

from .. import store
from ..models import Alert, Contract, Invoice, LineItem, Transaction
from . import agent_logger

# ---------------------------------------------------------------------------
# Cross-module chaining triggers (Gap 1 — agent-to-agent chaining)
# ---------------------------------------------------------------------------
# These functions fire automatically after specific events so agents pass
# results to each other without user intervention.
#
# on_reconciliation_done()  — after payments reconcile → refresh cashflow
# on_supervisor_run()       — after supervisor runs → share advisories with butler
# on_invoice_demand_sent()  — demand sent → update escalation state in memory

# Cross-module intelligence (SKILL.md §5 Module 6). When a contract is signed,
# Kora reads its payment schedule and auto-creates the matching invoices, then
# alerts the user — zero manual input. Logged with triggered_by='cross_module'.


def on_contract_signed(user_id: str, contract: Contract) -> list[Invoice]:
    milestones = (contract.terms or {}).get("milestones") or []
    created: list[Invoice] = []
    today = date.today()

    for m in milestones:
        amount = float(m.get("amount", 0) or 0)
        if amount <= 0:
            continue
        due = (today + timedelta(days=int(m.get("due_in_days", 14)))).isoformat()
        label = m.get("label", "Milestone payment")
        inv = Invoice(
            id=store.uid("inv"),
            user_id=user_id,
            invoice_number=store.next_invoice_number(user_id),
            client_name=contract.client_name,
            client_email=contract.client_email or "",
            line_items=[LineItem(description=f"{contract.title or 'Contract'} — {label}",
                                 quantity=1, rate=amount, amount=amount)],
            subtotal=amount, tax_rate=0, tax_amount=0, total=amount,
            currency="USD", status="draft", due_date=due,
            contract_id=contract.id,
            notes=f"Auto-created from signed contract {contract.id}",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        store.insert_invoice(inv)
        created.append(inv)

    if created:
        store.insert_alert(Alert(
            id=store.uid("alert"), user_id=user_id, type="contract_signed", severity="info",
            title="Contract signed — invoices created",
            body=f"Contract signed with {contract.client_name}. Kora created {len(created)} "
                 f"invoice(s) matching your payment schedule.",
            action_label="View invoices", action_url="/invoices", read=False,
            created_at=datetime.now(timezone.utc).isoformat(),
        ))

    # Task ledger — the invoices above cover the money owed; these cover the
    # WORK owed, so delivery milestones are tracked too. Best-effort.
    try:
        from .task_ledger import auto_capture_from_contract
        matched = next((c for c in store.list_clients(user_id)
                        if (c.name or "").strip().lower()
                        == (contract.client_name or "").strip().lower()), None)
        auto_capture_from_contract(user_id, contract, matched.id if matched else None)
    except Exception as exc:
        print(f"[cross_module] contract task capture skipped: {exc}")

    agent_logger.log_action(
        user_id=user_id,
        agent_type="cross_module",
        action=f"Contract signed with {contract.client_name} → created {len(created)} invoice(s)",
        input={"contractId": contract.id, "milestones": milestones},
        output={"invoiceNumbers": [i.invoice_number for i in created],
                "total": sum(i.total for i in created)},
        triggered_by="cross_module",
        source_record_type="contract",
        source_record_id=contract.id,
    )
    return created


# ---------------------------------------------------------------------------
# Payment reconciliation (bookkeeping → invoices)
# ---------------------------------------------------------------------------
# When an income transaction lands in bookkeeping, try to match it to an open
# invoice so a paid invoice is marked paid and its follow-up cadence stops —
# the inverse cross-module flow. CONSERVATIVE by design: auto-mark paid only on
# a strong match (exact amount + client-name token). Ambiguous matches (e.g. two
# open invoices of the same amount for the same client) are never auto-applied;
# they raise a "needs review" alert for the human to resolve.

_NAME_NOISE = {"inc", "llc", "corp", "co", "ltd", "limited", "the",
               "studio", "agency", "group", "company", "and"}


def _tokens(s: str) -> list[str]:
    return [w for w in re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).split() if w]


def _amount_eq(a: float, b: float) -> bool:
    return abs(round(a, 2) - round(b, 2)) < 0.01


def _client_matches(client_name: str, description: str) -> bool:
    """True when a distinctive token of the invoice's client appears in the
    transaction description (e.g. client 'Harbor Co' in 'TRANSFER FROM HARBOR CO')."""
    desc = set(_tokens(description))
    if not desc:
        return False
    strong = [w for w in _tokens(client_name) if len(w) >= 4 and w not in _NAME_NOISE]
    if not strong:  # client name is all short/noise words — fall back, still require a hit
        strong = [w for w in _tokens(client_name) if w not in _NAME_NOISE] or _tokens(client_name)
    return any(w in desc for w in strong)


def _used_transaction_ids(user_id: str) -> set[str]:
    """Transaction ids already consumed by a prior reconciliation run (matched or
    flagged), so the scheduler's full re-scan never double-applies a payment."""
    used: set[str] = set()
    for log in store.list_agent_logs(user_id):
        if log.agent_type != "cross_module" or not isinstance(log.output, dict):
            continue
        tid = log.output.get("reconciledTransactionId")
        if tid:
            used.add(tid)
    return used


def _txn_date_to_iso(d: str) -> str:
    return d if "T" in d else f"{d}T00:00:00+00:00"


def _paid_after_sent(txn: Transaction, inv: Invoice) -> bool:
    """A payment can only settle an invoice if it arrived on/after the invoice
    was sent. Transactions predating the invoice are unrelated income."""
    if not inv.sent_at:
        return True  # can't disprove — don't block the match
    return txn.date[:10] >= inv.sent_at[:10]


def reconcile_payments(
    user_id: str,
    transactions: list[Transaction] | None = None,
    triggered_by: str = "scheduler",
) -> dict:
    """Match income transactions to open invoices. Returns a summary dict."""
    open_invoices = [i for i in store.list_invoices(user_id)
                     if i.status in ("sent", "viewed", "overdue")]
    if not open_invoices:
        return {"matched": 0, "ambiguous": 0, "details": []}

    txns = transactions if transactions is not None else store.list_transactions(user_id)
    used = _used_transaction_ids(user_id)
    income = [t for t in txns if t.type == "income" and t.amount > 0 and t.id not in used]

    pool = list(open_invoices)
    matched: list[dict] = []
    ambiguous = 0

    for t in income:
        cands = [inv for inv in pool
                 if _amount_eq(t.amount, inv.total)
                 and _client_matches(inv.client_name, t.description)
                 and _paid_after_sent(t, inv)]

        if len(cands) == 1:
            inv = cands[0]
            pool.remove(inv)
            store.update_invoice(user_id, inv.id, {
                "status": "paid", "paid_at": _txn_date_to_iso(t.date),
            })
            try:
                from .playbook import observe_payment
                observe_payment(user_id, inv.model_dump(by_alias=False), {"date": t.date, "amount": t.amount, "description": t.description})
            except Exception:
                pass
            store.insert_alert(Alert(
                id=store.uid("alert"), user_id=user_id, type="payment_reconciled", severity="info",
                title="Payment received — invoice marked paid",
                body=f"A {inv.currency} {inv.total:,.2f} payment matched {inv.invoice_number} "
                     f"({inv.client_name}). Kora marked it paid and stopped follow-ups.",
                action_label="View invoices", action_url="/invoices", read=False,
                created_at=datetime.now(timezone.utc).isoformat(),
            ))
            agent_logger.log_action(
                user_id=user_id, agent_type="cross_module",
                action=f"Payment reconciled — marked {inv.invoice_number} paid ({inv.client_name})",
                input={"transactionId": t.id, "amount": t.amount, "description": t.description},
                output={"invoiceNumber": inv.invoice_number, "invoiceId": inv.id,
                        "reconciledTransactionId": t.id},
                triggered_by="cross_module", source_record_type="invoice", source_record_id=inv.id,
            )
            matched.append({"invoiceNumber": inv.invoice_number, "amount": inv.total,
                            "clientName": inv.client_name})

        elif len(cands) > 1:
            ambiguous += 1
            nums = ", ".join(c.invoice_number for c in cands)
            store.insert_alert(Alert(
                id=store.uid("alert"), user_id=user_id, type="payment_review", severity="warning",
                title="Payment needs review",
                body=f"A payment of {t.amount:,.2f} from \"{t.description[:60]}\" matches "
                     f"{len(cands)} open invoices ({nums}). Confirm which one it settles.",
                action_label="Review invoices", action_url="/invoices", read=False,
                created_at=datetime.now(timezone.utc).isoformat(),
            ))
            agent_logger.log_action(
                user_id=user_id, agent_type="cross_module", status="partial",
                action=f"Payment needs review — {t.amount:,.2f} matched {len(cands)} invoices",
                input={"transactionId": t.id, "amount": t.amount, "description": t.description},
                output={"candidates": [c.invoice_number for c in cands],
                        "reconciledTransactionId": t.id},
                triggered_by="cross_module", source_record_type="invoice",
            )

    return {"matched": len(matched), "ambiguous": ambiguous, "details": matched}


def on_reconciliation_done(user_id: str, reconcile_result: dict) -> None:
    """After payment reconciliation, trigger a cashflow forecast refresh so the
    next dashboard load reflects the newly marked-paid invoices immediately."""
    if not reconcile_result.get("matched"):
        return  # nothing changed — no need to refresh
    try:
        from .cashflow_agent import compute_forecast
        compute_forecast(user_id, with_insights=False)
        agent_logger.log_action(
            user_id=user_id, agent_type="cross_module",
            action=f"Post-reconciliation cashflow refresh triggered "
                   f"({reconcile_result['matched']} payment(s) matched)",
            input={"matched": reconcile_result["matched"]},
            output={"refreshed": True},
            triggered_by="cross_module", source_record_type="cashflow",
        )
    except Exception as exc:
        print(f"[cross_module] cashflow refresh after reconciliation failed: {exc}")


def on_supervisor_run(user_id: str, advisories: list[dict], status_line: str) -> None:
    """After the supervisor runs, push its key advisories into butler_memory so
    the morning briefing automatically includes the supervisor's latest findings."""
    if not advisories:
        return
    try:
        butler_mem = store.get_butler_memory(user_id)
    except Exception:
        butler_mem = {}
    try:
        store.set_butler_memory(user_id, {
            **butler_mem,
            "lastSupervisorAdvisories": [
                {"title": a["title"], "severity": a["severity"]}
                for a in advisories[:5]
            ],
            "lastSupervisorStatusLine": status_line,
            "lastSupervisorRunAt": datetime.now(timezone.utc).isoformat(),
        })
        agent_logger.log_action(
            user_id=user_id, agent_type="cross_module",
            action=f"Pushed {len(advisories)} supervisor advisory/ies to butler memory",
            input={"advisoryCount": len(advisories)},
            output={"statusLine": status_line},
            triggered_by="cross_module", source_record_type="butler",
        )
    except Exception as exc:
        print(f"[cross_module] supervisor→butler advisory push failed: {exc}")


def on_invoice_demand_sent(user_id: str, invoice_id: str, invoice_number: str) -> None:
    """After a demand letter is sent, update escalation state in manager_memory
    so the next supervisor run knows not to queue another demand for the same invoice."""
    try:
        mem = store.get_manager_memory(user_id)
    except Exception:
        mem = {}
    escalation: dict = mem.get("escalationState") or {}
    escalation[invoice_id] = {
        **(escalation.get(invoice_id) or {}),
        "lastAction": "demand_sent",
        "next": "writeoff_if_unpaid",
        "demandSentAt": datetime.now(timezone.utc).isoformat(),
    }
    try:
        store.set_manager_memory(user_id, {**mem, "escalationState": escalation})
        agent_logger.log_action(
            user_id=user_id, agent_type="cross_module",
            action=f"Updated escalation state after demand sent for {invoice_number}",
            input={"invoiceId": invoice_id, "invoiceNumber": invoice_number},
            output={"escalationState": escalation[invoice_id]},
            triggered_by="cross_module", source_record_type="invoice", source_record_id=invoice_id,
        )
    except Exception as exc:
        print(f"[cross_module] escalation state update after demand failed: {exc}")
