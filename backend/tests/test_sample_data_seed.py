"""Sample-data seeding must be opt-in, idempotent, and unable to break onboarding.

A fresh tenant shows an evaluator nothing, so the evaluation deployment seeds
the sample business on onboarding completion. The risks that buys are all on the
safety side, and that is what these cover:

  - it must stay OFF for real users, who did not ask for invented invoices;
  - it must refuse a tenant that already holds data, so a re-sent
    `onboarding_completed` cannot duplicate a client list or bury real rows;
  - it must never raise, because it runs inside the onboarding request.
"""

from __future__ import annotations

import pytest

from app.services import sample_data


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(sample_data.settings, "SEED_SAMPLE_DATA_ON_SIGNUP", True)


@pytest.fixture
def empty_tenant(monkeypatch):
    """An empty tenant whose inserts all succeed; returns the recorded calls."""
    calls: dict[str, list] = {}

    monkeypatch.setattr(sample_data.store, "list_clients", lambda _uid, *a, **k: [])

    def insert_transactions(rows):
        calls.setdefault("transactions", []).extend(rows)
        return rows

    monkeypatch.setattr(sample_data.store, "insert_transactions", insert_transactions)

    def recorder(name):
        def _insert(row):
            calls.setdefault(name, []).append(row)
            return row

        return _insert

    for name, fn in [
        ("contracts", "insert_contract"),
        ("clients", "insert_client"),
        ("engagements", "insert_engagement"),
        ("client_notes", "insert_client_note"),
        ("proposals", "insert_proposal"),
        ("retainers", "insert_retainer"),
        ("invoices", "insert_invoice"),
        ("alerts", "insert_alert"),
        ("agent_logs", "insert_agent_log"),
    ]:
        monkeypatch.setattr(sample_data.store, fn, recorder(name))
    return calls


class TestOptIn:
    def test_disabled_by_default_does_nothing(self, monkeypatch):
        """The setting that protects real users' books."""
        monkeypatch.setattr(sample_data.settings, "SEED_SAMPLE_DATA_ON_SIGNUP", False)
        touched = []
        monkeypatch.setattr(sample_data.store, "list_clients", lambda *a, **k: touched.append(1) or [])

        assert sample_data.seed_sample_workspace("u1") is None
        assert not touched, "a disabled seeder must not even read the tenant"

    def test_enabled_seeds_an_empty_tenant(self, enabled, empty_tenant):
        counts = sample_data.seed_sample_workspace("u1")
        assert counts is not None
        assert counts["clients"] > 0
        assert counts["invoices"] > 0

    def test_rows_are_written_under_the_target_tenant(self, enabled, empty_tenant):
        """The seed must land in the signed-up tenant, not the demo tenant."""
        sample_data.seed_sample_workspace("tenant-42")
        for client in empty_tenant["clients"]:
            assert getattr(client, "user_id", None) == "tenant-42"


class TestIdempotence:
    def test_a_tenant_that_already_has_clients_is_left_alone(self, enabled, monkeypatch):
        monkeypatch.setattr(sample_data.store, "list_clients", lambda *a, **k: [{"id": "existing"}])
        inserted = []
        monkeypatch.setattr(sample_data.store, "insert_client", lambda row: inserted.append(row))

        assert sample_data.seed_sample_workspace("u1") is None
        assert not inserted, "existing data must never be seeded over"

    def test_a_second_call_does_not_duplicate(self, enabled, monkeypatch):
        """onboarding_completed can be re-sent; the second pass must be a no-op."""
        state = {"clients": []}
        monkeypatch.setattr(sample_data.store, "list_clients", lambda *a, **k: state["clients"])
        monkeypatch.setattr(sample_data.store, "insert_transactions", lambda rows: rows)
        for fn in (
            "insert_contract",
            "insert_engagement",
            "insert_client_note",
            "insert_proposal",
            "insert_retainer",
            "insert_invoice",
            "insert_alert",
            "insert_agent_log",
        ):
            monkeypatch.setattr(sample_data.store, fn, lambda row: row)
        monkeypatch.setattr(sample_data.store, "insert_client", lambda row: state["clients"].append(row))

        first = sample_data.seed_sample_workspace("u1")
        after_first = len(state["clients"])
        second = sample_data.seed_sample_workspace("u1")

        assert first is not None and second is None
        assert len(state["clients"]) == after_first


class TestNeverBreaksOnboarding:
    def test_an_unreadable_tenant_is_not_seeded(self, enabled, monkeypatch):
        """If we cannot confirm the tenant is empty, we must not write to it."""
        monkeypatch.setattr(sample_data.store, "list_clients", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("PGRST301")))
        inserted = []
        monkeypatch.setattr(sample_data.store, "insert_client", lambda row: inserted.append(row))

        assert sample_data.seed_sample_workspace("u1") is None
        assert not inserted

    def test_a_failing_table_does_not_lose_the_others(self, enabled, empty_tenant, monkeypatch):
        """A table whose migration is missing skips that group only."""
        monkeypatch.setattr(sample_data.store, "insert_retainer", lambda row: (_ for _ in ()).throw(RuntimeError("PGRST205 missing table")))

        counts = sample_data.seed_sample_workspace("u1")
        assert counts["retainers"] == 0
        assert counts["invoices"] > 0, "later groups must still be inserted"

    def test_a_blank_user_id_is_refused(self, enabled, monkeypatch):
        inserted = []
        monkeypatch.setattr(sample_data.store, "insert_client", lambda row: inserted.append(row))
        assert sample_data.seed_sample_workspace("") is None
        assert not inserted
