from __future__ import annotations

import json
from datetime import datetime, timezone

from .. import store
from ..config import settings
from ..models import Alert, ManagerTask
from . import agent_logger, llm
from .bookkeeper import recategorize_uncategorized
from .cashflow_agent import compute_forecast
from .cost import estimate_cost_usd
from .cross_module import on_reconciliation_done, on_supervisor_run, reconcile_payments
from .invoice_agent import _days_overdue, _due_attempt, generate_demand_letter, send_follow_up_for
from .vertex_ai import generate_with_retry, get_ai

# Supervisor / "AI business manager" (artifacts/supervisor-design.md). A goal-aware
# orchestration layer over the point agents: gather cross-module state → assess →
# run safe actions → queue client-facing/irreversible ones for approval → brief.
# Hybrid by design: deterministic gathering/assessment, one LLM call for the briefing.

_FOLLOWUP_LABELS = {1: "gentle reminder", 2: "firm follow-up", 3: "final notice"}
_DEMAND_DAYS = 14  # escalate to a demand letter at/after this overdue age…
_DEMAND_MIN_FOLLOWUPS = 2  # …once this many reminders have already gone out
_WRITEOFF_DAYS = 60  # propose writing off bad debt after this overdue age + full cycle


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _month_income(txns) -> float:
    ym = datetime.now(timezone.utc).date().isoformat()[:7]
    return round(sum(abs(t.amount) for t in txns if t.type == "income" and t.date[:7] == ym), 2)


# --- 1. Gather cross-module state -------------------------------------------
def gather_state(user_id: str) -> dict:
    user = store.get_user(user_id)
    profile = user.profile if user else None
    txns = store.list_transactions(user_id)
    invoices = store.list_invoices(user_id)
    contracts = store.list_contracts(user_id)
    try:
        fc = compute_forecast(user_id, with_insights=False)  # deterministic, no LLM
    except Exception:
        fc = {}

    overdue = [i for i in invoices if i.status == "overdue" or (i.status in ("sent", "viewed") and _days_overdue(i.due_date) > 0)]
    uncategorized = sum(
        1
        for t in txns
        if (not t.ai_categorized) or (t.ai_confidence is not None and t.ai_confidence < 0.7) or (t.category in (None, "other_income", "other_expense"))
    )
    return {
        "user": user,
        "profile": profile,
        "currency": (user.currency if user else "USD"),
        "invoices": invoices,
        "open_invoices": [i for i in invoices if i.status in ("sent", "viewed", "overdue")],
        "overdue": overdue,
        "overdue_total": round(sum(i.total for i in overdue), 2),
        "contracts": contracts,
        "unsigned_contracts": [c for c in contracts if c.status in ("draft", "sent")],
        "month_income": _month_income(txns),
        "monthly_goal": (profile.monthly_revenue_goal if profile else None),
        "financial_goals": (profile.financial_goals if profile else None),
        "cash_danger_days": fc.get("dangerConservative14d") if fc else None,
        "current_balance": fc.get("currentBalance") if fc else None,
        "uncategorized_count": uncategorized,
        "client_context": _gather_client_context(user_id),
        "meeting_context": _gather_meeting_context(user_id),
    }


def _gather_meeting_context(user_id: str) -> dict:
    """Calendar + meeting action-item context for the supervisor (additive,
    best-effort — never blocks a run if Google/DB is unavailable)."""
    ctx = {
        "todays_client_meetings": [],
        "unlogged_meetings_count": 0,
        "open_action_items": 0,
        "overdue_action_items": 0,
    }
    try:
        from .calendar_intel import get_todays_meetings_with_clients, get_unlogged_past_meetings

        todays = get_todays_meetings_with_clients(user_id)
        ctx["todays_client_meetings"] = [e.get("title") for e in todays if e.get("is_client_meeting")][:5]
        ctx["unlogged_meetings_count"] = len(get_unlogged_past_meetings(user_id))
    except Exception:
        pass
    try:
        if settings.SUPABASE_URL:
            from supabase import create_client

            db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
            today_iso = datetime.now(timezone.utc).date().isoformat()
            items = db.table("meeting_action_items").select("due_date").eq("user_id", user_id).eq("status", "open").execute().data or []
            ctx["open_action_items"] = len(items)
            ctx["overdue_action_items"] = sum(1 for a in items if a.get("due_date") and a["due_date"] < today_iso)
    except Exception:
        pass
    return ctx


def _gather_client_context(user_id: str) -> dict:
    """Butler client/engagement context for the supervisor (additive, best-effort)."""
    try:
        clients = store.list_clients(user_id)
    except Exception:
        return {"total_clients": 0, "at_risk_clients": [], "silent_clients": [], "needs_attention": 0}
    at_risk = [c for c in clients if (c.health_score or 100) < 55]

    def _silent(c) -> bool:
        if not c.last_activity_at:
            return False
        try:
            dt = datetime.fromisoformat(c.last_activity_at.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - dt).days > 21
        except ValueError:
            return False

    silent = [c for c in clients if _silent(c)]
    return {
        "total_clients": len(clients),
        "at_risk_clients": [{"name": c.name, "health": c.health_score} for c in at_risk[:5]],
        "silent_clients": [c.name for c in silent[:5]],
        "needs_attention": len(at_risk) + len(silent),
    }


# --- 2. Assess → candidate proposals (deterministic rules) ------------------
def assess(state: dict) -> list[dict]:
    cur = state["currency"]
    proposals: list[dict] = []
    for inv in state["overdue"]:
        days = max(0, _days_overdue(inv.due_date))
        # Very stale after a full follow-up cycle → propose writing it off.
        if days >= _WRITEOFF_DAYS and inv.follow_up_count >= 3:
            proposals.append(
                {
                    "kind": "writeoff_invoice",
                    "severity": "warning",
                    "title": f"Write off — {inv.invoice_number} ({inv.client_name})",
                    "rationale": (
                        f"{inv.invoice_number} for {cur} {inv.total:,.2f} is {days} days overdue after "
                        "3 reminders. Consider writing it off as bad debt to clean up your books."
                    ),
                    "payload": {"invoiceId": inv.id, "invoiceNumber": inv.invoice_number, "amount": inv.total},
                    "source_record_type": "invoice",
                    "source_record_id": inv.id,
                }
            )
            continue
        # Escalate to a formal demand once seriously overdue with prior reminders.
        if days >= _DEMAND_DAYS and inv.follow_up_count >= _DEMAND_MIN_FOLLOWUPS:
            proposals.append(
                {
                    "kind": "send_demand",
                    "severity": "critical",
                    "title": f"Send payment demand — {inv.invoice_number} ({inv.client_name})",
                    "rationale": (
                        f"{inv.invoice_number} for {cur} {inv.total:,.2f} is {days} days overdue "
                        f"with {inv.follow_up_count} reminders already sent. A formal demand letter "
                        "is the appropriate next step."
                    ),
                    "payload": {"invoiceId": inv.id, "invoiceNumber": inv.invoice_number, "amount": inv.total},
                    "source_record_type": "invoice",
                    "source_record_id": inv.id,
                }
            )
            continue
        attempt = _due_attempt(inv.follow_up_count, days)
        if attempt:
            label = _FOLLOWUP_LABELS[attempt]
            proposals.append(
                {
                    "kind": "send_followup",
                    "severity": "warning",
                    "title": f"Send {label} — {inv.invoice_number} ({inv.client_name})",
                    "rationale": (
                        f"{inv.invoice_number} for {cur} {inv.total:,.2f} is {days} days overdue; " f"a {label} is due (attempt {attempt} of 3)."
                    ),
                    "payload": {"invoiceId": inv.id, "invoiceNumber": inv.invoice_number, "attempt": attempt},
                    "source_record_type": "invoice",
                    "source_record_id": inv.id,
                }
            )
    return proposals


def _stats(state: dict) -> dict:
    return {
        "overdueCount": len(state["overdue"]),
        "overdueTotal": state["overdue_total"],
        "openInvoices": len(state["open_invoices"]),
        "unsignedContracts": len(state["unsigned_contracts"]),
        "cashDangerDays": state["cash_danger_days"],
        "currentBalance": state["current_balance"],
        "currency": state["currency"],
    }


def _goal_progress(state: dict) -> dict:
    return {"monthIncome": state["month_income"], "monthlyGoal": state["monthly_goal"]}


def _advisories(state: dict) -> list[dict]:
    """Non-actionable heads-up findings the manager surfaces (no approval needed)."""
    adv: list[dict] = []
    if state["cash_danger_days"] is not None:
        adv.append(
            {
                "kind": "cash_danger",
                "severity": "critical",
                "title": "Cash flow projected negative",
                "detail": f"Your conservative projection dips below zero in ~{state['cash_danger_days']} days.",
            }
        )
    n = len(state["unsigned_contracts"])
    if n:
        adv.append(
            {
                "kind": "unsigned_contracts",
                "severity": "info",
                "title": f"{n} contract{'s' if n > 1 else ''} awaiting signature",
                "detail": "Unsigned contracts delay milestone invoicing.",
            }
        )
    uc = state.get("uncategorized_count", 0)
    if uc:
        adv.append(
            {
                "kind": "uncategorized_txns",
                "severity": "info",
                "title": f"{uc} transaction{'s' if uc > 1 else ''} flagged for review",
                "detail": "Some transactions are uncategorized or low-confidence — tidy them for an accurate P&L.",
            }
        )
    cc = state.get("client_context") or {}
    if cc.get("at_risk_clients"):
        names = ", ".join(c["name"] for c in cc["at_risk_clients"])
        adv.append(
            {
                "kind": "at_risk_clients",
                "severity": "warning",
                "title": f"{len(cc['at_risk_clients'])} client relationship(s) need attention",
                "detail": f"Health is low for: {names}. Open the Butler to see why.",
            }
        )
    if cc.get("silent_clients"):
        adv.append(
            {
                "kind": "silent_clients",
                "severity": "info",
                "title": f"{len(cc['silent_clients'])} client(s) have gone quiet",
                "detail": f"No activity logged in 21+ days for: {', '.join(cc['silent_clients'])}.",
            }
        )
    mc = state.get("meeting_context") or {}
    if mc.get("todays_client_meetings"):
        names = ", ".join(mc["todays_client_meetings"])
        adv.append(
            {
                "kind": "todays_meetings",
                "severity": "info",
                "title": f"{len(mc['todays_client_meetings'])} client meeting(s) today",
                "detail": f"On your calendar today: {names}.",
            }
        )
    if mc.get("overdue_action_items"):
        adv.append(
            {
                "kind": "overdue_action_items",
                "severity": "warning",
                "title": f"{mc['overdue_action_items']} meeting action item(s) overdue",
                "detail": "Commitments from past meetings are past their due date — clear them from the Meetings page.",
            }
        )
    if mc.get("unlogged_meetings_count"):
        adv.append(
            {
                "kind": "unlogged_meetings",
                "severity": "info",
                "title": f"{mc['unlogged_meetings_count']} past meeting(s) not logged",
                "detail": "Upload a transcript or add a quick note so Kora can extract decisions and follow-ups.",
            }
        )
    return adv


# --- 3+4. Run: reconcile (safe) → queue proposals → brief -------------------
def run_supervisor(user_id: str, triggered_by: str = "user") -> dict:
    """m4-lint: store-only — supervisor state is from store; user_text reaches
    this function only via manager /chat which sanitizes in routers/manager.py."""
    auto_actions: list[str] = []
    failed_steps: list[str] = []

    # Keep the relationship graph fresh (best-effort) so the briefing + chat can
    # traverse it. Cheap for small per-user graphs; never blocks the run.
    try:
        from .graph_memory import sync_graph

        sync_graph(user_id)
    except Exception as exc:
        print(f"[supervisor] graph sync skipped: {exc}")

    # Safe, reversible action first: reconcile payments (paid invoices drop out
    # of the overdue set before we propose chasing them).
    recon: dict = {"matched": 0, "ambiguous": 0}
    try:
        recon = reconcile_payments(user_id, triggered_by="cross_module")
        if recon.get("matched"):
            auto_actions.append(f"Reconciled {recon['matched']} payment(s) → invoice(s) marked paid")
        if recon.get("ambiguous"):
            auto_actions.append(f"Flagged {recon['ambiguous']} payment(s) needing review")
    except Exception as exc:
        print(f"[supervisor] reconcile skipped: {exc}")
        failed_steps.append("payment_reconciliation")

    # Chain: if payments were reconciled, refresh cashflow forecast immediately.
    try:
        on_reconciliation_done(user_id, recon)
    except Exception as exc:
        print(f"[supervisor] post-reconcile chain failed: {exc}")

    # Safe, reversible: categorize any transactions that were never categorized.
    try:
        n_cat = recategorize_uncategorized(user_id)
        if n_cat:
            auto_actions.append(f"Categorized {n_cat} uncategorized transaction(s)")
    except Exception as exc:
        print(f"[supervisor] recategorize skipped: {exc}")
        failed_steps.append("transaction_categorization")

    try:
        state = gather_state(user_id)
    except Exception as exc:
        print(f"[supervisor] gather_state failed: {exc}")
        failed_steps.append("state_gather")
        # Return a minimal degraded response — rule-based steps above still ran.
        return {
            "briefing": {
                "statusLine": "Supervisor partially unavailable — some data could not be loaded.",
                "summary": "One or more data sources failed to load. The actions above (if any) were still applied.",
                "priorities": [],
            },
            "goalProgress": {"monthIncome": 0, "monthlyGoal": None},
            "stats": {},
            "autoActions": auto_actions,
            "advisories": [],
            "pendingTasks": [],
            "ranAt": _now(),
            "partialFailure": True,
            "failedSteps": failed_steps,
        }

    auto_actions.append("Refreshed the 90-day cash-flow forecast")

    # Queue client-facing / irreversible proposals (idempotent).
    proposals = assess(state)
    new_tasks = 0
    for p in proposals:
        if store.find_open_manager_task(user_id, p["kind"], p["source_record_id"]):
            continue
        store.insert_manager_task(
            ManagerTask(
                id=store.uid("task"),
                user_id=user_id,
                kind=p["kind"],
                title=p["title"],
                rationale=p["rationale"],
                severity=p["severity"],
                status="proposed",
                payload=p["payload"],
                source_record_type=p["source_record_type"],
                source_record_id=p["source_record_id"],
                created_at=_now(),
            )
        )
        new_tasks += 1

    pending = store.list_manager_tasks(user_id, status="proposed")
    advisories = _advisories(state)

    # Surface a critical cash-flow warning as an alert too (deduped).
    if state["cash_danger_days"] is not None and not store.alert_fired_recently(user_id, "cashflow_danger", within_days=3):
        _body = f"Conservative projection turns negative in ~{state['cash_danger_days']} days."
        try:
            store.insert_alert(
                Alert(
                    id=store.uid("alert"),
                    user_id=user_id,
                    type="cashflow_danger",
                    severity="critical",
                    title="Cash flow projected negative",
                    body=_body,
                    action_label="View forecast",
                    action_url="/cashflow",
                    read=False,
                    created_at=_now(),
                )
            )
        except Exception:
            pass
        # Email the owner (fresh alert only — the dedup guard above ensures this).
        try:
            from . import owner_notify

            owner_notify.notify_critical_alert(user_id, title="Cash flow projected negative", body=_body, action_url="/cashflow")
        except Exception:
            pass

    # Continuity: read escalation state + previous summary for this briefing.
    prev_memory = {}
    try:
        prev_memory = store.get_manager_memory(user_id)
    except Exception:
        pass

    escalation_state: dict = prev_memory.get("escalationState") or {}
    payment_patterns: dict = prev_memory.get("paymentPatterns") or {}

    # Update escalation state from the proposals we just assessed.
    for p in proposals:
        src_id = p.get("source_record_id", "")
        if not src_id:
            continue
        if p["kind"] == "send_followup":
            cur = escalation_state.get(src_id, {})
            escalation_state[src_id] = {
                "followupsSent": cur.get("followupsSent", 0) + 1,
                "lastAction": "soft_followup",
                "next": "demand",
                "updatedAt": _now(),
            }
        elif p["kind"] == "send_demand":
            cur = escalation_state.get(src_id, {})
            escalation_state[src_id] = {
                "followupsSent": cur.get("followupsSent", 0),
                "lastAction": "demand",
                "next": "writeoff",
                "updatedAt": _now(),
            }
        elif p["kind"] == "writeoff_invoice":
            escalation_state[src_id] = {
                "lastAction": "writeoff_proposed",
                "next": "done",
                "updatedAt": _now(),
            }

    # Update payment patterns from recently reconciled invoices.
    try:
        paid_invoices = [i for i in store.list_invoices(user_id) if i.status == "paid" and i.paid_at and i.sent_at]
        for inv in paid_invoices:
            if not inv.client_id:
                continue
            try:
                sent_d = datetime.fromisoformat(inv.sent_at.replace("Z", "+00:00")).date()
                paid_d = datetime.fromisoformat(inv.paid_at.replace("Z", "+00:00")).date()
                days_to_pay = (paid_d - sent_d).days
                if days_to_pay < 0:
                    continue
                cid = str(inv.client_id)
                existing = payment_patterns.get(cid, {"avgDaysToPayment": days_to_pay, "sampleSize": 0})
                n = existing["sampleSize"] + 1
                avg = round((existing["avgDaysToPayment"] * existing["sampleSize"] + days_to_pay) / n, 1)
                payment_patterns[cid] = {"avgDaysToPayment": avg, "sampleSize": n, "clientName": inv.client_name}
            except Exception:
                pass
    except Exception:
        pass

    # One LLM call: the manager's briefing.
    profile = state["profile"]
    payload = {
        "business_name": (state["user"].business_name if state["user"] else None),
        "business_type": (profile.business_type if profile else None),
        "month_income": state["month_income"],
        "monthly_revenue_goal": state["monthly_goal"],
        "financial_goals": state["financial_goals"],
        "overdue_count": len(state["overdue"]),
        "overdue_total": state["overdue_total"],
        "open_count": len(state["open_invoices"]),
        "cash_danger_days": state["cash_danger_days"],
        "current_balance": state["current_balance"],
        "unsigned_contracts": len(state["unsigned_contracts"]),
        "uncategorized_count": state.get("uncategorized_count", 0),
        "client_context": state.get("client_context"),
        "meeting_context": state.get("meeting_context"),
        "advisories": [{"title": a["title"], "severity": a["severity"]} for a in advisories],
        "auto_actions": auto_actions,
        "pending_count": len(pending),
        "previous_summary": prev_memory.get("lastSummary"),
        "escalation_context": [{"invoiceId": k, **v} for k, v in list(escalation_state.items())[-5:] if v.get("lastAction")],
        "slow_payers": [
            {"clientName": v["clientName"], "avgDaysToPayment": v["avgDaysToPayment"]}
            for v in payment_patterns.values()
            if v.get("avgDaysToPayment", 0) > 14
        ][:3],
        "top_overdue": [
            {"invoiceNumber": i.invoice_number, "client": i.client_name, "total": i.total, "daysOverdue": max(0, _days_overdue(i.due_date))}
            for i in sorted(state["overdue"], key=lambda x: x.total, reverse=True)[:5]
        ],
    }
    try:
        from .playbook import assemble_context

        business_context = assemble_context(user_id, "briefing")
        if business_context:
            payload["business_context"] = business_context
    except Exception:
        pass
    ai = get_ai()
    model_used = tokens = latency = cost = None
    try:
        call = generate_with_retry(lambda: ai.compose_manager_briefing(payload))
        briefing = call.data
        model_used, tokens, latency, cost = call.model_used, call.tokens_used, call.latency_ms, call.cost_usd
    except Exception as exc:
        briefing = {
            "status_line": "Briefing unavailable — rule-based tasks still queued below.",
            "summary": "Manager briefing could not be generated right now. All rule-based actions above were applied.",
            "priorities": [],
        }
        failed_steps.append("llm_briefing")
        print(f"[supervisor] briefing failed: {exc}")
    try:
        from .validation import validate_briefing

        briefing = validate_briefing(briefing, state, user_id)
    except Exception:
        pass

    agent_logger.log_action(
        user_id=user_id,
        agent_type="cross_module",
        action=f"Supervisor run — {len(auto_actions)} auto action(s), {new_tasks} new decision(s) queued",
        input={"triggeredBy": triggered_by, "monthIncome": state["month_income"], "monthlyGoal": state["monthly_goal"]},
        output={"autoActions": auto_actions, "newTasks": new_tasks, "pending": len(pending), "statusLine": briefing.get("status_line")},
        model_used=model_used or "deterministic",
        tokens_used=tokens,
        latency_ms=latency,
        cost_usd=cost,
        triggered_by=triggered_by,
        source_record_type="supervisor",
    )

    briefing_out = {
        "statusLine": briefing.get("status_line", ""),
        "summary": briefing.get("summary", ""),
        "priorities": _as_str_list(briefing.get("priorities")),
    }
    ran_at = _now()

    # Persist continuity (manager memory) — best-effort.
    try:
        store.set_manager_memory(
            user_id,
            {
                "lastBriefing": briefing_out,
                "lastSummary": briefing_out["summary"],
                "lastRunAt": ran_at,
                "lastStats": _stats(state),
                "lastGoalProgress": _goal_progress(state),
                "lastAdvisories": advisories,
                # Cross-run escalation memory (Gap 2)
                "escalationState": escalation_state,
                "paymentPatterns": payment_patterns,
            },
        )
    except Exception as exc:
        print(f"[supervisor] manager memory not saved: {exc}")

    # Chain: push supervisor advisories to butler memory so morning briefing includes them.
    try:
        on_supervisor_run(user_id, advisories, briefing_out.get("statusLine", ""))
    except Exception as exc:
        print(f"[supervisor] post-run butler chain failed: {exc}")

    result = {
        "briefing": briefing_out,
        "goalProgress": _goal_progress(state),
        "stats": _stats(state),
        "autoActions": auto_actions,
        "advisories": advisories,
        "pendingTasks": [t.model_dump(by_alias=True) for t in pending],
        "ranAt": ran_at,
    }
    if failed_steps:
        result["partialFailure"] = True
        result["failedSteps"] = failed_steps
    return result


def _as_str_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    out = []
    for v in value:
        if isinstance(v, str) and v.strip():
            out.append(v.strip())
        elif isinstance(v, dict):
            out.append("; ".join(f"{x}" for x in v.values() if x))
    return out


# --- GET (cheap, no LLM): current manager snapshot --------------------------
def manager_snapshot(user_id: str) -> dict:
    state = gather_state(user_id)
    pending = store.list_manager_tasks(user_id, status="proposed")
    try:
        memory = store.get_manager_memory(user_id)
    except Exception:
        memory = {}
    return {
        "goalProgress": _goal_progress(state),
        "stats": _stats(state),
        "advisories": _advisories(state),
        "pendingTasks": [t.model_dump(by_alias=True) for t in pending],
        "lastBriefing": memory.get("lastBriefing"),
        "lastRunAt": memory.get("lastRunAt"),
    }


# --- Approve / dismiss a queued decision ------------------------------------
def approve_task(user_id: str, task_id: str) -> dict:
    task = store.get_manager_task(user_id, task_id)
    if not task:
        raise LookupError("Task not found")
    if task.status != "proposed":
        return {"task": task.model_dump(by_alias=True), "result": {"note": f"Already {task.status}"}}

    inv_id = (task.payload or {}).get("invoiceId")
    try:
        if task.kind == "send_followup":
            # Human approved → actually email the client via their connected Gmail.
            result = send_follow_up_for(user_id, inv_id, triggered_by="user", deliver=True)
        elif task.kind == "send_demand":
            result = generate_demand_letter(user_id, inv_id, triggered_by="user", deliver=True)
        elif task.kind == "writeoff_invoice":
            inv = store.get_invoice(user_id, inv_id)
            if not inv:
                raise ValueError("Invoice not found")
            store.update_invoice(user_id, inv_id, {"status": "cancelled"})
            agent_logger.log_action(
                user_id=user_id,
                agent_type="cross_module",
                action=f"Wrote off {inv.invoice_number} ({inv.client_name}) as bad debt",
                input={"invoiceNumber": inv.invoice_number, "amount": inv.total},
                output={"status": "cancelled"},
                triggered_by="user",
                source_record_type="invoice",
                source_record_id=inv.id,
            )
            result = {"note": f"{inv.invoice_number} written off (cancelled)."}
        elif task.kind == "send_proposal":
            prop_id = (task.payload or {}).get("proposalId")
            prop = store.get_proposal(user_id, prop_id) if prop_id else None
            if not prop:
                raise ValueError("Proposal not found")
            store.update_proposal(user_id, prop_id, {"status": "sent", "sent_at": _now()})
            agent_logger.log_action(
                user_id=user_id,
                agent_type="butler",
                action=f"Sent proposal {prop.proposal_number or ''} ({prop.title})".strip(),
                input={"proposalId": prop_id},
                output={"status": "sent"},
                triggered_by="user",
                source_record_type="proposal",
                source_record_id=prop_id,
            )
            result = {"note": f"Proposal '{prop.title}' marked as sent."}
        elif task.kind in ("send_email_gmail", "send_meeting_followup"):
            from .gmail_agent import execute_gmail_send

            message_id = execute_gmail_send(user_id, task.payload or {})
            to = (task.payload or {}).get("to_email", "recipient")
            result = {"note": f"Sent to {to}.", "gmailMessageId": message_id}
        elif task.kind == "create_calendar_event":
            from .calendar_agent import execute_calendar_event

            cal_result = execute_calendar_event(user_id, task.payload or {})
            result = {"note": f"Calendar event created. Meet link: {cal_result.get('meet_link', 'N/A')}."}
        elif task.kind == "review_contract":
            # A contract/agreement detected in Drive — download it and run the reviewer.
            payload = task.payload or {}
            file_id = payload.get("driveFileId")
            if not file_id:
                raise ValueError("No Drive file linked to this review task")
            from .drive_intel import download_drive_file_text
            from .contract_agent import review_contract

            text = download_drive_file_text(user_id, file_id, payload.get("mimeType", ""))
            if not (text or "").strip():
                raise ValueError("Could not read the document text")
            user = store.get_user(user_id)
            review = review_contract(user, text=text, source="drive", title=payload.get("fileName") or "Drive document")
            risk = getattr(review, "overall_risk", None) or (review.get("overallRisk") if isinstance(review, dict) else None)
            result = {
                "note": f"Reviewed '{payload.get('fileName', 'document')}' — {risk or 'done'} risk.",
                "review": review.model_dump(by_alias=True) if hasattr(review, "model_dump") else review,
            }
        else:
            result = {"note": "No executor for this task kind."}
    except ValueError as exc:
        store.update_manager_task(user_id, task_id, {"status": "failed", "resolved_at": _now()})
        raise ValueError(str(exc))

    updated = store.update_manager_task(user_id, task_id, {"status": "done", "resolved_at": _now()})
    return {"task": updated.model_dump(by_alias=True) if updated else None, "result": result}


def _compact_context(state: dict) -> dict:
    profile = state["profile"]
    return {
        "currency": state["currency"],
        "business_type": (profile.business_type if profile else None),
        "month_income": state["month_income"],
        "monthly_goal": state["monthly_goal"],
        "financial_goals": state["financial_goals"],
        "overdue_total": state["overdue_total"],
        "open_invoices_count": len(state["open_invoices"]),
        "contracts_count": len(state["contracts"]),
        "cash_danger_days": state["cash_danger_days"],
        "current_balance": state["current_balance"],
        "total_clients": (state.get("client_context") or {}).get("total_clients"),
        "clients_needing_attention": (state.get("client_context") or {}).get("at_risk_clients"),
        "silent_clients": (state.get("client_context") or {}).get("silent_clients"),
        "todays_client_meetings": (state.get("meeting_context") or {}).get("todays_client_meetings"),
        "open_action_items": (state.get("meeting_context") or {}).get("open_action_items"),
        "overdue": [
            {"number": i.invoice_number, "client": i.client_name, "total": i.total, "daysOverdue": max(0, _days_overdue(i.due_date))}
            for i in sorted(state["overdue"], key=lambda x: x.total, reverse=True)[:8]
        ],
    }


def chat(user_id: str, message: str, history: list[dict] | None = None) -> dict:
    """Conversational manager: answers grounded in the owner's live data and
    suggests actions (which still flow through the safe approval/run paths).

    m4-lint: no-sanitize — caller (`routers/manager.py`) already runs
    sanitize_prompt_input on the user message and safe_sanitize on each
    history entry before this function is invoked; both `message` and
    `history[*].content` are sanitized at the router boundary."""
    state = gather_state(user_id)
    payload = {
        "message": message,
        "history": history or [],
        "business_name": (state["user"].business_name if state["user"] else None),
        "business_type": (state["profile"].business_type if state["profile"] else None),
        "context": _compact_context(state),
    }
    ai = get_ai()
    model_used = tokens = latency = cost = None
    try:
        call = generate_with_retry(lambda: ai.chat_reply(payload))
        data = call.data if isinstance(call.data, dict) else {"reply": str(call.data)}
        model_used, tokens, latency, cost = call.model_used, call.tokens_used, call.latency_ms, call.cost_usd
    except Exception as exc:
        data = {"reply": "Sorry — I couldn't reach the manager just now. Please try again.", "suggested_actions": []}
        print(f"[supervisor] chat failed: {exc}")

    reply = str(data.get("reply", "")).strip()
    actions = [
        {"label": str(a.get("label", "")).strip(), "kind": str(a.get("kind", "")).strip()}
        for a in (data.get("suggested_actions") or [])
        if isinstance(a, dict) and a.get("label") and a.get("kind")
    ][:4]

    agent_logger.log_action(
        user_id=user_id,
        agent_type="chat",
        action=f"Manager chat: {message[:80]}",
        input={"message": message[:500]},
        output={"reply": reply[:500], "suggestedActions": actions},
        model_used=model_used or "deterministic",
        tokens_used=tokens,
        latency_ms=latency,
        cost_usd=cost,
        triggered_by="user",
        source_record_type="supervisor",
    )
    return {"reply": reply, "suggestedActions": actions}


def dismiss_task(user_id: str, task_id: str) -> dict:
    task = store.get_manager_task(user_id, task_id)
    if not task:
        raise LookupError("Task not found")
    updated = store.update_manager_task(user_id, task_id, {"status": "dismissed", "resolved_at": _now()})
    return {"task": updated.model_dump(by_alias=True) if updated else None}


# ===========================================================================
# Phase 2b — agentic tool-calling manager
# ===========================================================================
# The manager is given tools and decides which to call. SAFE boundary preserved:
# read tools auto-run; client-facing / money actions only QUEUE for approval
# (propose_*), never send. Falls back to the suggestion-based chat() if the
# gateway doesn't support tool-calling or the mock provider is active.


def _find_invoice_by_number(user_id: str, number: str):
    target = (number or "").strip().upper()
    return next((i for i in store.list_invoices(user_id) if i.invoice_number.upper() == target), None)


def _tool_financial_summary(user_id: str, args: dict) -> dict:
    s = gather_state(user_id)
    return {
        "currency": s["currency"],
        "monthIncome": s["month_income"],
        "monthlyGoal": s["monthly_goal"],
        "financialGoals": s["financial_goals"],
        "overdueCount": len(s["overdue"]),
        "overdueTotal": s["overdue_total"],
        "openInvoices": len(s["open_invoices"]),
        "cashDangerDays": s["cash_danger_days"],
        "currentBalance": s["current_balance"],
    }


def _tool_list_overdue(user_id: str, args: dict) -> dict:
    s = gather_state(user_id)
    return {
        "overdue": [
            {
                "number": i.invoice_number,
                "client": i.client_name,
                "total": i.total,
                "daysOverdue": max(0, _days_overdue(i.due_date)),
                "followUps": i.follow_up_count,
                "contractLinked": bool(i.contract_id),
            }
            for i in sorted(s["overdue"], key=lambda x: x.total, reverse=True)
        ]
    }


def _tool_list_contracts(user_id: str, args: dict) -> dict:
    return {"contracts": [{"title": c.title, "type": c.type, "status": c.status, "client": c.client_name} for c in store.list_contracts(user_id)]}


def _tool_cashflow(user_id: str, args: dict) -> dict:
    s = gather_state(user_id)
    return {"cashDangerDays": s["cash_danger_days"], "currentBalance": s["current_balance"], "currency": s["currency"]}


def _tool_list_clients(user_id: str, args: dict) -> dict:
    clients = store.list_clients(user_id)
    return {
        "totalClients": len(clients),
        "activeClients": sum(1 for c in clients if c.status == "active"),
        "clients": [{"name": c.name, "status": c.status, "health": c.health_score, "email": c.email} for c in clients],
    }


_TASK_VERBS = {"send_followup": "Send follow-up", "send_demand": "Send payment demand", "writeoff_invoice": "Write off"}


def _queue_invoice_task(user_id: str, number: str, kind: str, severity: str) -> dict:
    inv = _find_invoice_by_number(user_id, number)
    if not inv:
        return {"error": f"No invoice '{number}' found."}
    if inv.status in ("paid", "cancelled", "draft"):
        return {"error": f"{inv.invoice_number} is {inv.status} — not eligible."}
    if store.find_open_manager_task(user_id, kind, inv.id):
        return {"queued": True, "new": False, "note": f"Already awaiting your approval for {inv.invoice_number}."}
    verb = _TASK_VERBS.get(kind, "Action")
    try:
        store.insert_manager_task(
            ManagerTask(
                id=store.uid("task"),
                user_id=user_id,
                kind=kind,
                title=f"{verb} — {inv.invoice_number} ({inv.client_name})",
                rationale="Proposed by the manager chat at your request.",
                severity=severity,
                status="proposed",
                payload={"invoiceId": inv.id, "invoiceNumber": inv.invoice_number},
                source_record_type="invoice",
                source_record_id=inv.id,
                created_at=_now(),
            )
        )
    except Exception as exc:  # e.g. manager_tasks table not migrated yet
        return {"error": f"Couldn't queue the action (storage): {str(exc)[:100]}"}
    return {"queued": True, "new": True, "title": f"{verb} for {inv.invoice_number}"}


def _tool_propose_follow_up(user_id: str, args: dict) -> dict:
    return _queue_invoice_task(user_id, args.get("invoice_number", ""), "send_followup", "warning")


def _tool_propose_demand(user_id: str, args: dict) -> dict:
    return _queue_invoice_task(user_id, args.get("invoice_number", ""), "send_demand", "critical")


def _tool_propose_writeoff(user_id: str, args: dict) -> dict:
    return _queue_invoice_task(user_id, args.get("invoice_number", ""), "writeoff_invoice", "warning")


def _tool_run_review(user_id: str, args: dict) -> dict:
    r = run_supervisor(user_id, triggered_by="user")
    return {"autoActions": r["autoActions"], "pendingDecisions": len(r["pendingTasks"]), "statusLine": r["briefing"]["statusLine"]}


def _tool_query_graph(user_id: str, args: dict) -> dict:
    """Traverse the relationship graph for one client — everything linked to them
    (invoices, contracts, engagements, proposals, retainers, learned facts)."""
    name = (args.get("client_name") or "").strip()
    if not name:
        return {"error": "Provide a client_name."}
    from .graph_memory import query_subgraph, sync_graph

    res = query_subgraph(user_id, name)
    if not res.get("found"):
        # Graph may be stale/never built — rebuild once, then retry.
        try:
            sync_graph(user_id)
            res = query_subgraph(user_id, name)
        except Exception:
            pass
    return res


def _tool_recall_memory(user_id: str, args: dict) -> dict:
    """Semantic recall over the agent's durable memory — surfaces relevant PAST
    context (learned facts, email/meeting summaries, preferences) by meaning, for
    planning/decisions. Hybrid-ranked; degrades to lexical when embeddings are off."""
    query = (args.get("query") or "").strip()
    if not query:
        return {"error": "Provide a query describing what past context you need."}
    from .memory_recall import recall

    hits = recall(user_id, query, k=6)
    return {
        "memories": [{"content": h["content"], "kind": h.get("kind"), "source": h.get("source"), "score": h.get("_score")} for h in hits]
        or "No relevant past context found."
    }


def _tool_list_tasks(user_id: str, args: dict) -> dict:
    """Open client work from the task ledger — what's outstanding, overdue, blocked."""
    from .task_ledger import OPEN_STATUSES, is_overdue, stats as task_stats

    status = (args.get("status") or "").strip() or None
    client_name = (args.get("client_name") or "").strip()

    client_id = None
    if client_name:
        target = client_name.lower()
        match = next((c for c in store.list_clients(user_id) if (c.name or "").lower() == target), None)
        if not match:
            return {"error": f"No client '{client_name}' found."}
        client_id = match.id

    tasks = store.list_tasks(
        user_id,
        client_id=client_id,
        status=status,
        statuses=None if status else OPEN_STATUSES,
    )
    return {
        "summary": task_stats(user_id),
        "tasks": [
            {
                "title": t.title,
                "status": t.status,
                "priority": t.priority,
                "dueDate": t.due_date,
                "owner": t.owner,
                "source": t.source,
                "overdue": is_overdue(t),
            }
            for t in tasks[:25]
        ],
    }


def _tool_propose_task(user_id: str, args: dict) -> dict:
    """Create a task in the ledger. Safe/reversible (internal tracking only, it
    never contacts the client), so it runs directly rather than queueing."""
    title = (args.get("title") or "").strip()
    if not title:
        return {"error": "Provide a task title."}
    client_id = None
    client_name = (args.get("client_name") or "").strip()
    if client_name:
        target = client_name.lower()
        match = next((c for c in store.list_clients(user_id) if (c.name or "").lower() == target), None)
        client_id = match.id if match else None
    from .task_ledger import create_task

    t = create_task(
        user_id,
        {
            "title": title,
            "client_id": client_id,
            "due_date": args.get("due_date"),
            "priority": args.get("priority") or "medium",
            "owner": "me",
            "source": "agent",
        },
    )
    return {"created": True, "title": t.title, "status": t.status, "dueDate": t.due_date}


_HANDLERS = {
    "get_financial_summary": _tool_financial_summary,
    "list_overdue_invoices": _tool_list_overdue,
    "list_contracts": _tool_list_contracts,
    "get_cashflow": _tool_cashflow,
    "list_clients": _tool_list_clients,
    "propose_follow_up": _tool_propose_follow_up,
    "propose_payment_demand": _tool_propose_demand,
    "propose_write_off": _tool_propose_writeoff,
    "run_full_review": _tool_run_review,
    "query_graph": _tool_query_graph,
    "recall_memory": _tool_recall_memory,
    "list_tasks": _tool_list_tasks,
    "propose_task": _tool_propose_task,
}

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_financial_summary",
            "description": "Month income, goal progress, overdue totals, cash danger, balance.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_overdue_invoices",
            "description": "Overdue invoices with amounts, days overdue, prior follow-ups, contract link.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_contracts",
            "description": "The owner's contracts and their status.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_cashflow",
            "description": "Cash-flow danger window and current balance.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_clients",
            "description": (
                "The owner's clients — total count, plus each client's name, status "
                "(active/prospect/inactive), health score, and email. Use this for ANY question "
                "about clients or how many clients the owner has."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_follow_up",
            "description": (
                "Queue a follow-up email to a client for an overdue invoice FOR THE OWNER'S " "APPROVAL. Does NOT send it. Provide the invoice number."
            ),
            "parameters": {"type": "object", "properties": {"invoice_number": {"type": "string"}}, "required": ["invoice_number"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_payment_demand",
            "description": (
                "Queue a formal payment-demand letter for a seriously overdue invoice FOR THE "
                "OWNER'S APPROVAL. Does NOT send it. Provide the invoice number."
            ),
            "parameters": {"type": "object", "properties": {"invoice_number": {"type": "string"}}, "required": ["invoice_number"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_write_off",
            "description": (
                "Queue writing off a very stale, uncollectable invoice as bad debt FOR THE "
                "OWNER'S APPROVAL (does not cancel it directly). Provide the invoice number."
            ),
            "parameters": {"type": "object", "properties": {"invoice_number": {"type": "string"}}, "required": ["invoice_number"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_full_review",
            "description": "Run a full review now: reconcile payments, refresh forecast, queue approvals.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_graph",
            "description": (
                "Traverse the relationship memory for ONE client — everything linked to them: "
                "invoices (issued/paid), contracts, engagements, proposals, retainers and learned "
                "facts. Use this for relationship questions like 'what has <client> been involved in?' "
                "or 'what's our history with <client>?'."
            ),
            "parameters": {"type": "object", "properties": {"client_name": {"type": "string"}}, "required": ["client_name"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall_memory",
            "description": (
                "Semantic recall over your durable memory of PAST context — learned facts, "
                "email/meeting summaries, commitments, preferences and prior decisions — ranked by "
                "relevance to a free-text query. Use this when a decision needs history that isn't a "
                "specific client or invoice, e.g. 'have we handled a late-payment dispute like this "
                "before?', 'what did the client say about scope?', 'past context on pricing pushback'."
            ),
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": (
                "Open client WORK from the task ledger — what's outstanding, overdue or "
                "blocked, with due dates and owners. Use for 'what's on my plate?', "
                "'what's overdue?', 'what's blocked?', or what's outstanding for a client. "
                "Optionally filter by client_name or status "
                "(todo|in_progress|blocked|done|cancelled)."
            ),
            "parameters": {"type": "object", "properties": {"client_name": {"type": "string"}, "status": {"type": "string"}}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_task",
            "description": (
                "Add a task to the owner's ledger so a piece of work is tracked and can't be "
                "missed. Internal tracking only — it never contacts the client, so it is "
                "applied directly. Provide a title; optionally client_name, due_date "
                "(YYYY-MM-DD) and priority (low|medium|high|urgent)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "client_name": {"type": "string"},
                    "due_date": {"type": "string"},
                    "priority": {"type": "string"},
                },
                "required": ["title"],
            },
        },
    },
]


def _agentic_available() -> bool:
    try:
        return llm.is_configured() and get_ai().__class__.__name__ == "RealLLMProvider"
    except Exception:
        return False


def chat_agentic(user_id: str, message: str, history: list[dict] | None = None) -> dict:
    """Tool-calling manager. Falls back to suggestion-based chat() when tool-calling
    isn't available (mock provider / gateway without function-calling)."""
    if not _agentic_available():
        return {**chat(user_id, message, history), "queued": 0}

    user = store.get_user(user_id)
    profile = user.profile if user else None
    biz = (user.business_name if user else None) or "the owner"
    btype = (profile.business_type if profile else None) or "small business"
    system = (
        f"You are Kora, the AI business manager for {biz} ({btype}). Use your tools to GROUND every "
        "answer in the owner's real, live data — call read tools (get_financial_summary, "
        "list_overdue_invoices, list_contracts, get_cashflow, list_clients) before stating numbers. "
        "For any question about clients or their count, call list_clients — never guess. For questions "
        "about a specific client's history or what they've been involved in, call query_graph. When a "
        "question or decision needs relevant PAST context that isn't a specific client or invoice (prior "
        "situations, what was said/agreed, recurring issues), call recall_memory with a descriptive query. "
        "For anything about outstanding WORK — what's on their plate, overdue, blocked, or still owed to a "
        "client — call list_tasks; use propose_task to make sure a piece of work gets tracked. "
        "Speak concisely in the second person with the actual figures. "
        "IMPORTANT SAFETY RULE: you may NEVER send a client email or move money directly. To act on an "
        "overdue invoice, call propose_follow_up or propose_payment_demand — these only QUEUE the action "
        "for the owner's approval. After queuing, tell the owner it's waiting for their approval. You may "
        "call run_full_review to reconcile payments and queue approvals. Not financial advice."
    )
    messages: list[dict] = [{"role": "system", "content": system}]
    for m in (history or [])[-8:]:
        messages.append({"role": "user" if m.get("role") == "user" else "assistant", "content": m.get("content", "")})
    messages.append({"role": "user", "content": message})

    tools_used: list[str] = []
    queued = 0
    in_tok = out_tok = 0
    model = None
    reply = ""
    try:
        for _ in range(5):
            turn = llm.chat_messages(messages, tools=_TOOLS, temperature=0.3, max_tokens=800)
            in_tok += turn.input_tokens
            out_tok += turn.output_tokens
            model = turn.model
            if not turn.tool_calls:
                reply = (turn.content or "").strip()
                break
            messages.append(
                {
                    "role": "assistant",
                    "content": turn.content or "",
                    "tool_calls": [
                        {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                        for tc in turn.tool_calls
                    ],
                }
            )
            for tc in turn.tool_calls:
                name = tc.function.name
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except Exception:
                    args = {}
                handler = _HANDLERS.get(name)
                result = handler(user_id, args) if handler else {"error": "unknown tool"}
                if result.get("new"):
                    queued += 1
                tools_used.append(name)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result, default=str)})
        else:
            reply = "I pulled the details together but ran out of steps — please ask once more."
    except Exception as exc:
        print(f"[supervisor] agentic chat failed, falling back: {exc}")
        return {**chat(user_id, message, history), "queued": 0}

    if not reply:
        reply = "Done."
    agent_logger.log_action(
        user_id=user_id,
        agent_type="chat",
        action=f"Manager chat (agentic): {message[:80]}",
        input={"message": message[:500], "toolsUsed": tools_used},
        output={"reply": reply[:500], "queued": queued},
        model_used=model or settings.MODEL_NAME,
        tokens_used=in_tok + out_tok,
        cost_usd=estimate_cost_usd(in_tok, out_tok),
        triggered_by="user",
        source_record_type="supervisor",
    )
    return {"reply": reply, "suggestedActions": [], "queued": queued, "toolsUsed": tools_used}
