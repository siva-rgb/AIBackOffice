from __future__ import annotations

from datetime import date, timedelta

from .. import store
from . import agent_logger
from .vertex_ai import generate_with_retry, get_ai

# Cash-flow forecast (SKILL.md §5 Module 7 + modules.md#cashflow).
# Numeric projection is deterministic; the LLM adds risks/actions/assumptions.

# The LLM is asked for lists of risks/actions but is non-deterministic about
# item shape — it sometimes returns objects ({"risk": ..., "invoice": ...})
# instead of plain strings. The frontend renders these as React children, so a
# raw object crashes the page ("Objects are not valid as a React child"). Coerce
# every item to a readable string here, the one place all callers funnel through.
_TEXT_KEYS = ("risk", "action", "recommendation", "text", "description", "detail", "title", "summary", "message")


def _coerce_str(item: object) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        # Prefer a known human-readable field, then append remaining context.
        main = next((str(item[k]) for k in _TEXT_KEYS if item.get(k)), None)
        extras = [f"{k}: {v}" for k, v in item.items() if k not in _TEXT_KEYS and v not in (None, "")]
        if main:
            return f"{main} ({', '.join(extras)})" if extras else main
        return "; ".join(f"{k}: {v}" for k, v in item.items())
    return str(item)


def _as_str_list(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    return [_coerce_str(v) for v in value if v not in (None, "")]


# Payment probability by invoice age (modules.md#cashflow).
def _payment_probability(status: str, days_overdue: int) -> float:
    if status == "draft":
        return 0.0
    if days_overdue < 7:
        return 0.85
    if days_overdue < 14:
        return 0.6
    return 0.3


def compute_forecast(user_id: str, horizon_days: int = 90, with_insights: bool = True) -> dict:
    txns = store.list_transactions(user_id)
    invoices = store.list_invoices(user_id)
    today = date.today()

    # Baseline daily run-rate from the last 90 days.
    window_start = today - timedelta(days=90)
    recent = [t for t in txns if date.fromisoformat(t.date) >= window_start]
    income_90 = sum(abs(t.amount) for t in recent if t.type == "income")
    expense_90 = sum(abs(t.amount) for t in recent if t.type == "expense")
    daily_income = income_90 / 90
    daily_expense = expense_90 / 90

    # Starting balance proxy: net of all recorded transactions.
    current_balance = round(sum(t.amount for t in txns), 2)  # income positive, expense negative

    # Load payment patterns from supervisor memory to adjust expected collection dates.
    payment_patterns: dict = {}
    try:
        memory = store.get_manager_memory(user_id)
        payment_patterns = memory.get("paymentPatterns") or {}
    except Exception:
        pass

    # Expected income from open invoices, weighted by payment probability, mapped to due date.
    inflow_by_date: dict[str, float] = {}
    open_invoices = []
    for inv in invoices:
        if inv.status in ("paid", "cancelled"):
            continue
        d_over = (today - date.fromisoformat(inv.due_date)).days
        prob = _payment_probability(inv.status, d_over)
        if prob <= 0:
            continue
        # If we have a payment pattern for this client, shift expected payment date accordingly.
        pay_base = max(date.fromisoformat(inv.due_date), today)
        if inv.client_email and str(inv.client_email) in payment_patterns:
            avg_late = int(payment_patterns[str(inv.client_email)].get("avgDaysToPayment", 0))
            if avg_late > 0:
                # Shift expected payment forward by avg late days, capped at 90 days.
                pay_base = pay_base + timedelta(days=min(avg_late, 90))
        pay_date = pay_base.isoformat()
        inflow_by_date[pay_date] = inflow_by_date.get(pay_date, 0) + inv.total * prob
        open_invoices.append({"number": inv.invoice_number, "amount": inv.total, "dueDate": inv.due_date, "daysOverdue": max(0, d_over), "prob": prob})

    # Build cumulative scenarios across the horizon.
    forecast = []
    bal_exp = bal_opt = bal_con = current_balance
    for i in range(horizon_days + 1):
        d = (today + timedelta(days=i)).isoformat()
        invoice_inflow = inflow_by_date.get(d, 0)
        # daily deltas
        bal_exp += daily_income - daily_expense + invoice_inflow
        bal_opt += daily_income * 1.10 - daily_expense * 0.90 + invoice_inflow
        bal_con += daily_income * 0.75 - daily_expense * 1.15 + invoice_inflow * 0.8
        forecast.append(
            {
                "date": d,
                "expected": round(bal_exp, 2),
                "optimistic": round(bal_opt, 2),
                "conservative": round(bal_con, 2),
            }
        )

    # Danger detection (modules.md#cashflow danger zone).
    def first_negative(key: str, within: int) -> int | None:
        for i, p in enumerate(forecast[: within + 1]):
            if p[key] < 0:
                return i
        return None

    snapshot = {
        "current_balance": current_balance,
        "avg_monthly_income": round(daily_income * 30, 2),
        "avg_monthly_expenses": round(daily_expense * 30, 2),
        "open_invoices": open_invoices,
        "expected_balance_30d": forecast[min(30, horizon_days)]["expected"],
        "conservative_balance_14d": forecast[min(14, horizon_days)]["conservative"],
    }

    insights = {"key_risks": [], "recommended_actions": [], "confidence_score": 0.7, "assumptions": []}
    model_used = tokens = latency = cost = None
    if with_insights:
        try:
            from .playbook import assemble_context

            business_context = assemble_context(user_id, "forecast")
            if business_context:
                snapshot["business_context"] = business_context
        except Exception:
            pass
        ai = get_ai()
        try:
            call = generate_with_retry(lambda: ai.generate_cashflow_insights(snapshot))
            insights = call.data
            model_used, tokens, latency, cost = call.model_used, call.tokens_used, call.latency_ms, call.cost_usd
        except Exception as exc:  # graceful degradation
            insights["assumptions"] = ["AI insights unavailable; showing numeric projection only."]
            agent_logger.log_action(
                user_id=user_id,
                agent_type="cashflow_forecaster",
                action="Cash flow insight generation failed — numeric forecast served",
                input=snapshot,
                output={"error": str(exc)},
                status="error",
                error_message=str(exc),
                triggered_by="user",
                source_record_type="cashflow",
            )

    agent_logger.log_action(
        user_id=user_id,
        agent_type="cashflow_forecaster",
        action=f"Generated {horizon_days}-day cash flow forecast",
        input={"horizonDays": horizon_days, "snapshot": snapshot},
        output={"confidenceScore": insights.get("confidence_score"), "expectedBalance30d": snapshot["expected_balance_30d"]},
        model_used=model_used or "deterministic",
        tokens_used=tokens,
        latency_ms=latency,
        cost_usd=cost,
        triggered_by="user",
        source_record_type="cashflow",
    )

    return {
        "currentBalance": current_balance,
        "horizonDays": horizon_days,
        "forecast": forecast,
        "keyRisks": _as_str_list(insights.get("key_risks")),
        "recommendedActions": _as_str_list(insights.get("recommended_actions")),
        "confidenceScore": insights.get("confidence_score", 0.7),
        "assumptions": _as_str_list(insights.get("assumptions")),
        "dangerExpected30d": first_negative("expected", 30),
        "dangerConservative14d": first_negative("conservative", 14),
    }
