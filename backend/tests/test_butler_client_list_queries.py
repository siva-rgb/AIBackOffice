"""`list_clients_enriched` must stay O(1) in queries, not O(clients).

It used to call `_client_invoices` and `list_engagements` once per client, and
`_client_invoices` re-read the tenant's whole invoice list each time. Five
clients cost eleven round trips — five of them full-table — and the endpoint
measured ~7.6s against the deployed backend.

The query-count assertions are the point. A future edit that reintroduces a
per-client fetch would still return correct data and would pass any test that
only checked the output, so correctness alone cannot protect this.
"""

from __future__ import annotations

import pytest

from app.services import butler


class Rec:
    """Minimal stand-in exposing the attributes butler reads."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def model_dump(self, by_alias=False):
        return dict(self.__dict__)


@pytest.fixture
def store(monkeypatch):
    """Fake store that counts calls per function."""
    calls = {"clients": 0, "invoices": 0, "engagements": 0}

    clients = [Rec(id=f"c{i}", name=f"Client {i}", last_activity_at=None) for i in range(5)]
    invoices = [
        Rec(client_name="Client 0", total=100.0, status="paid", due_date="2026-01-01"),
        Rec(client_name="Client 0", total=50.0, status="sent", due_date="2999-01-01"),
        Rec(client_name="client 1", total=200.0, status="paid", due_date="2026-01-01"),
    ]
    engagements = [
        Rec(client_id="c0", status="active"),
        Rec(client_id="c0", status="completed"),
        Rec(client_id="c1", status="planning"),
    ]

    def list_clients(user_id, status=None):
        calls["clients"] += 1
        return clients

    def list_invoices(user_id):
        calls["invoices"] += 1
        return invoices

    def list_engagements(user_id, client_id=None):
        calls["engagements"] += 1
        assert client_id is None, "engagements must be fetched for the tenant, not per client"
        return engagements

    monkeypatch.setattr(butler.store, "list_clients", list_clients)
    monkeypatch.setattr(butler.store, "list_invoices", list_invoices)
    monkeypatch.setattr(butler.store, "list_engagements", list_engagements)
    return calls


class TestQueryCount:
    def test_five_clients_cost_three_queries(self, store):
        butler.list_clients_enriched("u1")
        assert store == {"clients": 1, "invoices": 1, "engagements": 1}

    def test_cost_does_not_grow_with_client_count(self, store, monkeypatch):
        """The regression this file exists for."""
        many = [Rec(id=f"c{i}", name=f"Client {i}", last_activity_at=None) for i in range(50)]
        monkeypatch.setattr(butler.store, "list_clients", lambda *a, **k: many)
        butler.list_clients_enriched("u1")
        assert store["invoices"] == 1
        assert store["engagements"] == 1

    def test_no_clients_skips_the_other_queries(self, store, monkeypatch):
        monkeypatch.setattr(butler.store, "list_clients", lambda *a, **k: [])
        assert butler.list_clients_enriched("u1") == []
        assert store["invoices"] == 0
        assert store["engagements"] == 0


class TestOutputUnchanged:
    def test_financials_are_grouped_to_the_right_client(self, store):
        rows = butler.list_clients_enriched("u1")
        by_name = {r["name"]: r for r in rows}
        assert by_name["Client 0"]["financials"]["invoiced"] == 150.0
        assert by_name["Client 0"]["financials"]["paid"] == 100.0
        assert by_name["Client 1"]["financials"]["invoiced"] == 200.0

    def test_client_matching_is_case_insensitive(self, store):
        """Invoice 3 is filed under 'client 1' but belongs to 'Client 1'."""
        rows = butler.list_clients_enriched("u1")
        assert {r["name"]: r for r in rows}["Client 1"]["financials"]["paid"] == 200.0

    def test_a_client_with_no_invoices_gets_zeroes_not_a_crash(self, store):
        rows = butler.list_clients_enriched("u1")
        assert {r["name"]: r for r in rows}["Client 4"]["financials"]["invoiced"] == 0

    def test_only_active_engagements_are_counted(self, store):
        rows = butler.list_clients_enriched("u1")
        by_name = {r["name"]: r for r in rows}
        assert by_name["Client 0"]["activeEngagementCount"] == 1  # 'completed' excluded
        assert by_name["Client 1"]["activeEngagementCount"] == 1  # 'planning' counts
        assert by_name["Client 2"]["activeEngagementCount"] == 0

    def test_every_client_is_returned(self, store):
        assert len(butler.list_clients_enriched("u1")) == 5
