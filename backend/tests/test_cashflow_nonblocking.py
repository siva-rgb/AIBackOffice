"""The forecast request must not wait on the LLM.

`/api/cashflow/forecast` measured 12-26s against the deployed backend because it
made a synchronous Vertex call inside a GET the dashboard issues on load. The
numeric projection is deterministic and cheap; only the commentary was slow.

What must remain true:
  - the numbers are always computed fresh, never served stale from the cache;
  - a request never blocks on the model;
  - concurrent loads do not each fire their own Vertex call;
  - a failing model degrades to numbers-only rather than failing the request.
"""

from __future__ import annotations

import threading
import time

import pytest

from app.services import cashflow_agent as ca


@pytest.fixture(autouse=True)
def clean():
    ca.clear_insights_cache()
    yield
    ca.clear_insights_cache()


@pytest.fixture
def data(monkeypatch):
    """Minimal deterministic inputs so compute_forecast can run."""

    class T:
        def __init__(self, amount, ttype, d):
            self.amount, self.type, self.date = amount, ttype, d

    today = ca.date.today().isoformat()
    monkeypatch.setattr(ca.store, "list_transactions", lambda uid: [T(1000.0, "income", today), T(-200.0, "expense", today)])
    monkeypatch.setattr(ca.store, "list_invoices", lambda uid: [])
    monkeypatch.setattr(ca.agent_logger, "log_action", lambda **kw: None)


@pytest.fixture
def slow_model(monkeypatch):
    """A model that takes long enough that blocking would be obvious."""
    started = threading.Event()
    calls = {"n": 0}

    class Call:
        data = {"key_risks": ["late payer"], "recommended_actions": ["chase"], "confidence_score": 0.9, "assumptions": []}
        model_used, tokens_used, latency_ms, cost_usd = "gemini-2.5-flash", 10, 1200, 0.001

    def generate_with_retry(fn):
        calls["n"] += 1
        started.set()
        time.sleep(0.6)
        return Call()

    monkeypatch.setattr(ca, "generate_with_retry", generate_with_retry)
    monkeypatch.setattr(ca, "get_ai", lambda: object())
    return calls, started


class TestDoesNotBlock:
    def test_the_first_request_returns_without_waiting_for_the_model(self, data, slow_model):
        calls, _ = slow_model
        began = time.monotonic()
        result = ca.compute_forecast("u1", horizon_days=30)
        elapsed = time.monotonic() - began

        assert elapsed < 0.4, f"request waited {elapsed:.2f}s on the model"
        assert result["assumptions"] == [ca._PENDING_NOTE]

    def test_the_numbers_are_present_on_that_first_request(self, data, slow_model):
        """Degrading the commentary must not degrade the forecast itself."""
        result = ca.compute_forecast("u1", horizon_days=30)
        assert result["forecast"], "the numeric projection must still be returned"
        assert result["currentBalance"] == 800.0

    def test_insights_appear_on_a_later_request(self, data, slow_model):
        calls, started = slow_model
        ca.compute_forecast("u1", horizon_days=30)
        assert started.wait(timeout=5)
        time.sleep(0.8)  # let the background thread finish and cache

        result = ca.compute_forecast("u1", horizon_days=30)
        assert result["keyRisks"] == ["late payer"]


class TestDoesNotStampede:
    def test_concurrent_requests_trigger_one_model_call(self, data, slow_model):
        calls, _ = slow_model
        threads = [threading.Thread(target=lambda: ca.compute_forecast("u1", horizon_days=30)) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        time.sleep(0.9)
        assert calls["n"] == 1, f"{calls['n']} Vertex calls for one forecast"

    def test_different_horizons_are_cached_separately(self, data, slow_model):
        calls, _ = slow_model
        ca.compute_forecast("u1", horizon_days=30)
        ca.compute_forecast("u1", horizon_days=90)
        time.sleep(1.2)
        assert calls["n"] == 2


class TestDegradesSafely:
    def test_a_failing_model_does_not_fail_the_request(self, data, monkeypatch):
        def boom(fn):
            raise RuntimeError("vertex unavailable")

        monkeypatch.setattr(ca, "generate_with_retry", boom)
        monkeypatch.setattr(ca, "get_ai", lambda: object())

        result = ca.compute_forecast("u1", horizon_days=30)
        assert result["forecast"], "numbers must survive an LLM outage"
        time.sleep(0.3)
        assert ca._cached_insights(("u1", 30)) is None

    def test_with_insights_false_never_schedules_a_call(self, data, slow_model):
        calls, _ = slow_model
        ca.compute_forecast("u1", horizon_days=30, with_insights=False)
        time.sleep(0.3)
        assert calls["n"] == 0

    def test_expired_insights_are_regenerated(self, data, slow_model, monkeypatch):
        calls, started = slow_model
        ca.compute_forecast("u1", horizon_days=30)
        assert started.wait(timeout=5)
        time.sleep(0.8)

        key = ("u1", 30)
        expires, ins, meta = ca._insights_cache[key]
        ca._insights_cache[key] = (expires - 10_000, ins, meta)  # force expiry
        assert ca._cached_insights(key) is None
