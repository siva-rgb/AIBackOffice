"""One client's memories must never reach another client's email draft.

`_recall_context` feeds the prompt for an email addressed *to* a client. Its
fallback used to drop the `client_id` filter entirely when the scoped recall came
back empty — which is exactly the situation for a brand-new client. Another
client's rates, complaints or contract terms could be pulled straight into the
draft. The fallback now keeps only untagged, business-wide rows.

Not a tenant boundary (it is all one user's data), so the review-before-send gate
still stands behind it — but "the owner will notice" is a thin control, and an
empty recall is when the model most wants to borrow context.
"""

from __future__ import annotations

import pytest

from app.services.butler_comms import _recall_context

UID = "user-1"
THIS_CLIENT = "client-a"
OTHER_CLIENT = "client-b"


def mem(content: str, client_id: str | None) -> dict:
    return {"content": content, "client_id": client_id, "kind": "fact", "_score": 0.9}


@pytest.fixture
def fake_recall(monkeypatch):
    """Record calls and serve canned rows, honouring the client_id filter."""
    rows: list[dict] = []
    calls: list[dict] = []

    def _recall(user_id, query, *, k=6, client_id=None, **kw):
        calls.append({"client_id": client_id, "k": k})
        matching = [r for r in rows if client_id is None or r.get("client_id") == client_id]
        return matching[:k]

    monkeypatch.setattr("app.services.memory_recall.recall", _recall)
    return type("Ctl", (), {"rows": rows, "calls": calls})()


class TestScopedRecall:
    def test_uses_this_clients_memories(self, fake_recall):
        fake_recall.rows.append(mem("Prefers a Monday check-in.", THIS_CLIENT))
        out = _recall_context(UID, THIS_CLIENT, "Acme", "chase invoice")
        assert "Monday check-in" in out

    def test_scoped_call_passes_the_client_id(self, fake_recall):
        fake_recall.rows.append(mem("Prefers a Monday check-in.", THIS_CLIENT))
        _recall_context(UID, THIS_CLIENT, "Acme", "chase invoice")
        assert fake_recall.calls[0]["client_id"] == THIS_CLIENT


class TestFallbackDoesNotLeak:
    def test_another_clients_memory_is_excluded(self, fake_recall):
        """The regression: no rows for this client, so the filter was dropped."""
        fake_recall.rows.append(mem("Northwind negotiated the rate down to 60/hr.", OTHER_CLIENT))
        out = _recall_context(UID, THIS_CLIENT, "Acme", "propose new work")
        assert out == ""
        assert "60/hr" not in out

    def test_untagged_business_knowledge_still_comes_through(self, fake_recall):
        """The fallback keeps its point — general context is not client data."""
        fake_recall.rows.append(mem("We never discount below 20 percent.", None))
        out = _recall_context(UID, THIS_CLIENT, "Acme", "propose new work")
        assert "never discount" in out

    def test_mixed_rows_keep_only_the_untagged_ones(self, fake_recall):
        fake_recall.rows.extend(
            [
                mem("Northwind pays late every quarter.", OTHER_CLIENT),
                mem("Standard payment terms are net 14.", None),
            ]
        )
        out = _recall_context(UID, THIS_CLIENT, "Acme", "propose new work")
        assert "net 14" in out
        assert "Northwind" not in out

    def test_fallback_overfetches_so_filtering_still_yields_four(self, fake_recall):
        """Filtering happens after ranking; k=4 would often filter down to nothing."""
        fake_recall.rows.extend(mem(f"other-{i}", OTHER_CLIENT) for i in range(10))
        fake_recall.rows.extend(mem(f"general-{i}", None) for i in range(6))
        out = _recall_context(UID, THIS_CLIENT, "Acme", "propose new work")
        assert out.count("general-") == 4
        assert fake_recall.calls[1]["k"] > 4

    def test_recall_failure_degrades_to_empty(self, monkeypatch):
        def boom(*a, **kw):
            raise RuntimeError("embeddings offline")

        monkeypatch.setattr("app.services.memory_recall.recall", boom)
        assert _recall_context(UID, THIS_CLIENT, "Acme", "chase invoice") == ""
