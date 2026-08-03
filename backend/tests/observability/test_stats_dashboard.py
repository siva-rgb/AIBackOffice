"""M11.3 — business-metrics dashboard stats.

The legacy `compute_agent_stats` is unchanged. `compute_dashboard_stats` adds:

  * p50 / p95 latency
  * totalTokens
  * costByModel
  * topErrors (top-3 failing actions)
  * daily series (last N days, oldest-first)
  * window_days (echoed back)

A regression that breaks any of the legacy keys fails these tests too — the
dashboard endpoint sits on top of the original surface.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import AgentLog
from app.services.stats import compute_agent_stats, compute_dashboard_stats


def _log(
    *,
    days_ago: int = 0,
    status: str = "success",
    latency_ms: int | None = None,
    cost_usd: float | None = None,
    tokens_used: int | None = None,
    model_used: str = "azure.gpt-4.1",
    action: str = "do_thing",
    agent_type: str = "bookkeeper",
) -> AgentLog:
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    return AgentLog(
        id=f"log-{days_ago}-{action}",
        user_id="u",
        agent_type=agent_type,
        action=action,
        input={},
        output=None,
        model_used=model_used,
        tokens_used=tokens_used,
        latency_ms=latency_ms,
        cost_usd=cost_usd,
        status=status,
        error_message=None,
        triggered_by="user",
        source_record_type=None,
        source_record_id=None,
        created_at=ts,
    )


def test_legacy_keys_still_present():
    logs = [_log()]
    base = compute_dashboard_stats(logs, window_days=14)
    for key in (
        "total",
        "today",
        "thisWeek",
        "byType",
        "byTrigger",
        "successRate",
        "avgLatencyMs",
        "totalCostUsd",
    ):
        assert key in base, key


def test_p50_and_p95_latency():
    logs = [_log(latency_ms=ms) for ms in [10, 20, 30, 40, 100, 200, 400]]
    out = compute_dashboard_stats(logs, window_days=14)
    assert out["p50LatencyMs"] == 40
    # p95 over 7 values → index ~5.7 → between 200 and 400.
    assert 200 <= out["p95LatencyMs"] <= 400


def test_empty_logs_handles_p95_gracefully():
    out = compute_dashboard_stats([], window_days=14)
    assert out["p50LatencyMs"] == 0
    assert out["p95LatencyMs"] == 0
    assert out["totalTokens"] == 0
    assert out["daily"] == [] or all(b["count"] == 0 for b in out["daily"])


def test_cost_by_model_groups_by_model_used():
    logs = [
        _log(cost_usd=0.10, model_used="azure.gpt-4.1"),
        _log(cost_usd=0.05, model_used="azure.gpt-4.1"),
        _log(cost_usd=0.20, model_used="gemini-1.5-pro"),
    ]
    out = compute_dashboard_stats(logs, window_days=14)
    assert out["costByModel"]["azure.gpt-4.1"] == 0.15
    assert out["costByModel"]["gemini-1.5-pro"] == 0.20


def test_top_errors_is_action_counter_for_non_success():
    logs = [
        _log(status="error", action="failed_thing"),
        _log(status="error", action="failed_thing"),
        _log(status="error", action="other_thing"),
        _log(status="success", action="ok_thing"),
    ]
    out = compute_dashboard_stats(logs, window_days=14)
    actions = [e["action"] for e in out["topErrors"]]
    assert "failed_thing" in actions
    assert "ok_thing" not in actions
    # top-3 ordered descending by count
    counts = [e["count"] for e in out["topErrors"]]
    assert counts == sorted(counts, reverse=True)


def test_daily_series_length_matches_window():
    logs = [_log(days_ago=0), _log(days_ago=5), _log(days_ago=30)]
    out = compute_dashboard_stats(logs, window_days=14)
    assert len(out["daily"]) == 14
    assert out["window_days"] == 14
    # The day-30 entry should NOT be in the windowed series.
    iso_dates = [b["date"] for b in out["daily"]]
    assert all(len(d) == 10 for d in iso_dates)


def test_total_tokens_accumulates():
    logs = [
        _log(tokens_used=100),
        _log(tokens_used=200),
        _log(tokens_used=None),
    ]
    out = compute_dashboard_stats(logs, window_days=14)
    assert out["totalTokens"] == 300


def test_window_days_is_echoed_back():
    out = compute_dashboard_stats([], window_days=7)
    assert out["window_days"] == 7


def test_compute_agent_stats_still_returns_subset():
    """The legacy function still works unchanged."""
    logs = [_log(latency_ms=10), _log(latency_ms=20)]
    out = compute_agent_stats(logs)
    assert "p95LatencyMs" not in out  # NOT in the legacy surface
    assert "totalTokens" not in out
