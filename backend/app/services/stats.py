from __future__ import annotations

from datetime import datetime, timezone

from ..models import AgentLog


def compute_agent_stats(logs: list[AgentLog]) -> dict:
    now = datetime.now(timezone.utc)
    day = 86_400
    by_type: dict[str, int] = {}
    by_trigger: dict[str, int] = {}
    today = week = success = latency_count = 0
    latency_sum = 0
    cost = 0.0

    for log_entry in logs:
        by_type[log_entry.agent_type] = by_type.get(log_entry.agent_type, 0) + 1
        by_trigger[log_entry.triggered_by] = by_trigger.get(log_entry.triggered_by, 0) + 1
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
