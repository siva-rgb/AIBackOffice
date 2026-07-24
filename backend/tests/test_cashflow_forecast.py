"""Regression cover for the cash-flow forecast (M6).

Pins the **2026-05-30 string-coercion fix**: the LLM is asked for lists of
risks/actions but sometimes returns objects instead of strings, and the frontend
renders them as React children — a raw object crashes the page with "Objects are
not valid as a React child". `_as_str_list` must flatten every item to a
readable string. Also pins that the numeric projection is deterministic and
degrades without the LLM.
"""
from __future__ import annotations

from app.models import Transaction
from app.services import cashflow_agent as CF


def test_coerce_str_flattens_objects_the_llm_returns():
    # A plain string passes through.
    assert CF._coerce_str("Client X may pay late") == "Client X may pay late"
    # A dict with a known text field is rendered readably, not as "{...}".
    out = CF._coerce_str({"risk": "Invoice 12 overdue", "invoice": "INV-12"})
    assert "Invoice 12 overdue" in out and "INV-12" in out
    assert "{" not in out
    # A dict with no known field still becomes a string, never an object.
    out2 = CF._coerce_str({"foo": "bar", "baz": 3})
    assert isinstance(out2, str) and "bar" in out2


def test_as_str_list_never_yields_a_non_string():
    mixed = ["a plain risk", {"action": "Chase INV-9"}, {"unknown": "shape"}, None, ""]
    result = CF._as_str_list(mixed)
    assert all(isinstance(x, str) for x in result), "a non-string leaked to the React layer"
    assert "" not in result and None not in result
    # None/empty dropped; the three real items survive.
    assert len(result) == 3


def test_as_str_list_wraps_a_bare_value():
    assert CF._as_str_list("solo") == ["solo"]
    assert CF._as_str_list(None) == []


def test_forecast_numeric_projection_is_deterministic(user_id, monkeypatch):
    """No LLM on the numeric path; the same ledger yields the same forecast."""
    now = "2026-06-01T00:00:00+00:00"
    txns = [
        Transaction(id="t1", user_id=user_id, date="2026-05-15", description="Paid",
                    amount=3000.0, type="income", category="sales", created_at=now),
        Transaction(id="t2", user_id=user_id, date="2026-05-20", description="Rent",
                    amount=-1000.0, type="expense", category="office", created_at=now),
    ]
    monkeypatch.setattr(CF.store, "list_transactions", lambda uid: txns)
    monkeypatch.setattr(CF.store, "list_invoices", lambda uid: [])

    a = CF.compute_forecast(user_id, horizon_days=30, with_insights=False)
    b = CF.compute_forecast(user_id, horizon_days=30, with_insights=False)
    assert a["forecast"] == b["forecast"]
    assert a["currentBalance"] == 2000.0            # 3000 income - 1000 expense
    # Insight lists are always string lists even when empty.
    assert a["keyRisks"] == [] and a["recommendedActions"] == []
    assert len(a["forecast"]) == 31                 # horizon + today
