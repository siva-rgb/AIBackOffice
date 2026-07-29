from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from statistics import median

from ..models import AgentLog

# Pure functions over a list[AgentLog] — no I/O, no globals. The /dashboard
# endpoint (M11.3) calls these; the original /stats endpoint also still works
# (returns the subset of keys it always did).


def compute_agent_stats(logs: list[AgentLog]) -> dict:
    """The original stats surface (M6). Kept for backward-compat with the
    existing /api/agents/log/stats consumers — the dashboard endpoint layers
    additional keys on top via `compute_dashboard_stats`.
    """
    now = datetime.now(timezone.utc)
    day = 86_400
    by_type: dict[str, int] = {}
    by_trigger: dict[str, int] = {}
    today = week = success = latency_count = 0
    latency_sum = 0
    cost = 0.0

    for log_entry in logs:
        by_type[log_entry.agent_type] = by_type.get(log_entry.agent_type, 0) + 1
        by_trigger[log_entry.triggered_by] = (
            by_trigger.get(log_entry.triggered_by, 0) + 1
        )
        try:
            age = (now - datetime.fromisoformat(log_entry.created_at)).total_seconds()
        except ValueError:
            age = day * 999
        if age < day:
            today += 1
        if age < 7 * day:
            week += 1
        if log_entry.status == "success":
            success += 1
        if log_entry.latency_ms is not None:
            latency_sum += log_entry.latency_ms
            latency_count += 1
        cost += log_entry.cost_usd or 0

    return {
        "total": len(logs),
        "today": today,
        "thisWeek": week,
        "byType": by_type,
        "byTrigger": by_trigger,
        "successRate": round((success / len(logs)) * 100, 1) if logs else 100.0,
        "avgLatencyMs": round(latency_sum / latency_count) if latency_count else 0,
        "totalCostUsd": round(cost, 4),
    }


def _percentile(values: list[int], pct: float) -> int:
    """Linear-interpolated percentile over an unsorted integer list.

    Returns 0 when `values` is empty so the dashboard never blows up on a
    fresh tenant.
    """
    if not values:
        return 0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * pct
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return int(round(s[f] + (s[c] - s[f]) * (k - f)))


def _parse_iso(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def compute_dashboard_stats(logs: list[AgentLog], *, window_days: int = 14) -> dict:
    """The richer KPI surface for M11.3.

    Returns every key `compute_agent_stats` returned, plus:

      * p50LatencyMs / p95LatencyMs / totalTokens
      * costByModel — USD per model name (model_used)
      * topErrors   — top-3 actions whose status != "success", with counts
      * daily       — last `window_days` days, oldest-first: date/count/cost/errors
      * window_days — echoed back so the frontend can confirm what it asked for
    """
    base = compute_agent_stats(logs)
    latencies: list[int] = []
    tokens_total = 0
    cost_by_model: dict[str, float] = {}
    error_actions: Counter[str] = Counter()

    # Bucket logs by ISO date for the daily series.
    today = datetime.now(timezone.utc).date()
    cutoff_date = today - timedelta(days=window_days - 1)
    daily_buckets: dict[str, dict[str, str | float | int]] = {
        (cutoff_date + timedelta(days=i)).isoformat(): {
            "date": (cutoff_date + timedelta(days=i)).isoformat(),
            "count": 0,
            "cost": 0.0,
            "errors": 0,
        }
        for i in range(window_days)
    }

    for log_entry in logs:
        if log_entry.latency_ms is not None:
            latencies.append(log_entry.latency_ms)
        if log_entry.tokens_used is not None:
            tokens_total += log_entry.tokens_used
        # cost_by_model: only count when a model is named
        if log_entry.cost_usd:
            model = log_entry.model_used or "unknown"
            cost_by_model[model] = cost_by_model.get(model, 0.0) + float(
                log_entry.cost_usd
            )
        if log_entry.status != "success":
            error_actions[log_entry.action] += 1
        # Daily bucketing
        ts = _parse_iso(log_entry.created_at)
        if ts is None:
            continue
        d = ts.date().isoformat()
        bucket = daily_buckets.get(d)
        if bucket is None:
            continue
        bucket["count"] = int(bucket["count"]) + 1
        if log_entry.cost_usd:
            bucket["cost"] = float(bucket["cost"]) + float(log_entry.cost_usd)
        if log_entry.status != "success":
            bucket["errors"] = int(bucket["errors"]) + 1

    # Round cost for display
    cost_by_model = {k: round(v, 4) for k, v in sorted(cost_by_model.items())}
    for b in daily_buckets.values():
        b["cost"] = round(float(b["cost"]), 4)
    daily = [
        daily_buckets[(cutoff_date + timedelta(days=i)).isoformat()]
        for i in range(window_days)
    ]
    top_errors = [
        {"action": action, "count": count}
        for action, count in error_actions.most_common(3)
    ]

    base.update(
        {
            "p50LatencyMs": int(median(latencies)) if latencies else 0,
            "p95LatencyMs": _percentile(latencies, 0.95),
            "totalTokens": tokens_total,
            "costByModel": cost_by_model,
            "topErrors": top_errors,
            "daily": daily,
            "window_days": window_days,
        }
    )
    return base
