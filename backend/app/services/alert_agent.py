from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from .. import store
from ..models import Alert
from . import agent_logger
from .cashflow_agent import compute_forecast
from .vertex_ai import generate_with_retry, get_ai

# Daily digest / proactive alerts agent (SKILL.md §5 Module 4 + modules.md#alerts).
# Builds a financial snapshot, asks the LLM for alerts, dedupes, and inserts them.

_VALID_SEVERITY = {"info", "warning", "critical"}


def run_digest(user_id: str, triggered_by: str = "user") -> dict:
    txns = store.list_transactions(user_id)
    invoices = store.list_invoices(user_id)
    today = date.today()
    month_ago = today - timedelta(days=30)

    recent = [t for t in txns if date.fromisoformat(t.date) >= month_ago]
    income_30 = sum(abs(t.amount) for t in recent if t.type == "income")
    expense_30 = sum(abs(t.amount) for t in recent if t.type == "expense")

    overdue = [i for i in invoices if i.status == "overdue"]
    open_inv = [i for i in invoices if i.status in ("sent", "overdue", "viewed")]
    untagged = sum(1 for t in txns if t.type == "expense" and not t.tax_deductible)

    fc = compute_forecast(user_id, horizon_days=30, with_insights=False)

    snapshot = {
        "open_invoice_count": len(open_inv),
        "open_invoice_total": round(sum(i.total for i in open_inv), 2),
        "overdue_count": len(overdue),
        "overdue_total": round(sum(i.total for i in overdue), 2),
        "income_30d": round(income_30, 2),
        "expenses_30d": round(expense_30, 2),
        "projected_balance_30d": fc["forecast"][30]["expected"] if len(fc["forecast"]) > 30 else None,
        "projected_balance_14d": fc["forecast"][14]["conservative"] if len(fc["forecast"]) > 14 else None,
        "untagged_deductibles": untagged,
        "days_until_quarter_end": _days_to_quarter_end(today),
    }

    ai = get_ai()
    try:
        call = generate_with_retry(lambda: ai.generate_alerts(snapshot))
        raw_alerts = call.data if isinstance(call.data, list) else []
        model_used, tokens, latency, cost, status = (
            call.model_used, call.tokens_used, call.latency_ms, call.cost_usd, "success")
    except Exception as exc:
        raw_alerts, model_used, tokens, latency, cost, status = [], "deterministic", None, None, None, "error"
        agent_logger.log_action(
            user_id=user_id, agent_type="alert_generator",
            action="Daily digest failed", input=snapshot, output={"error": str(exc)},
            status="error", error_message=str(exc), triggered_by=triggered_by)

    created: list[Alert] = []
    for a in raw_alerts:
        a_type = str(a.get("type", "alert"))
        if store.alert_fired_recently(user_id, a_type, within_days=7) and a_type != "cashflow_critical":
            continue
        sev = a.get("severity", "info")
        if sev not in _VALID_SEVERITY:
            sev = "info"
        alert = Alert(
            id=store.uid("alert"), user_id=user_id, type=a_type, severity=sev,
            title=str(a.get("title", "Alert"))[:120], body=str(a.get("body", ""))[:400],
            action_label=a.get("action_label"), action_url=a.get("action_url"),
            read=False, created_at=datetime.now(timezone.utc).isoformat(),
        )
        store.insert_alert(alert)
        created.append(alert)

    agent_logger.log_action(
        user_id=user_id, agent_type="alert_generator",
        action=f"Generated daily digest — {len(created)} new alert(s)",
        input={"snapshot": snapshot},
        output={"alerts": [a.type for a in created]},
        model_used=model_used, tokens_used=tokens, latency_ms=latency, cost_usd=cost,
        status=status if status == "error" else "success", triggered_by=triggered_by,
    )
    return {"created": len(created), "alerts": [a.model_dump(by_alias=True) for a in created]}


def _days_to_quarter_end(d: date) -> int:
    q_end_month = ((d.month - 1) // 3 + 1) * 3
    if q_end_month == 12:
        end = date(d.year, 12, 31)
    else:
        end = date(d.year, q_end_month + 1, 1) - timedelta(days=1)
    return (end - d).days
