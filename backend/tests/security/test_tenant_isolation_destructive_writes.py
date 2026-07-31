"""M1.4 regression — destructive writes in supabase_store MUST be user-scoped.

Guards a real cross-tenant data-loss bug: the M1 refactor to
`repo(user_id).raw_table(...)` dropped the `.eq("user_id", user_id)` filter on
several UPDATE/DELETE store functions. `raw_table()` is the escape hatch and does
NOT auto-scope, so under the service-role key (RLS bypassed) an unfiltered
`.delete()` wipes EVERY tenant's rows — and two of these functions
(`delete_kg_for_user`, `delete_agent_memory*`) are called by GDPR account deletion.

The mock backend has its own (correct) implementations, so the bug only lives in
`supabase_store`. These tests exercise that module directly by injecting a recording
fake Supabase client in place of the real `_sb`, then assert every destructive
write carried an `.eq("user_id", <caller>)` predicate.
"""

from __future__ import annotations

import uuid

import pytest


class _FakeResult:
    def __init__(self) -> None:
        self.data: list = []


class _FakeQuery:
    """Records the .delete()/.update()/.eq()/.like() chain for one table."""

    def __init__(self, table: str, log: list) -> None:
        self._table = table
        self._log = log
        self.op: str | None = None  # "delete" | "update" | ...
        self.eqs: list[tuple] = []  # [(col, val), ...]

    def delete(self) -> "_FakeQuery":
        self.op = "delete"
        return self

    def update(self, _payload) -> "_FakeQuery":
        self.op = "update"
        return self

    def insert(self, _payload) -> "_FakeQuery":
        self.op = "insert"
        return self

    def upsert(self, _payload, **_kw) -> "_FakeQuery":
        self.op = "upsert"
        return self

    def select(self, *_a, **_kw) -> "_FakeQuery":
        self.op = "select"
        return self

    def eq(self, col, val) -> "_FakeQuery":
        self.eqs.append((col, val))
        return self

    def like(self, col, val) -> "_FakeQuery":
        self.eqs.append(("~like", col, val))
        return self

    def execute(self) -> _FakeResult:
        self._log.append(self)
        return _FakeResult()


class _FakeClient:
    def __init__(self) -> None:
        self.queries: list[_FakeQuery] = []

    def table(self, name: str) -> _FakeQuery:
        return _FakeQuery(name, self.queries)


@pytest.fixture
def store_mod(monkeypatch):
    """Import `supabase_store` hermetically.

    Under the mock-mode conftest, Supabase creds are blanked, so the module-level
    `_sb = get_supabase()` would raise at import. We patch the pooled client to a
    fake first, then (lazily) import the module.
    """
    from app.clients import pool

    monkeypatch.setattr(pool, "get_supabase", lambda: _FakeClient())
    from app.backends import supabase_store as ss

    return ss


@pytest.fixture
def fake_sb(monkeypatch, store_mod):
    client = _FakeClient()
    monkeypatch.setattr(store_mod, "_sb", client)
    return client


def _scoped_deletes(client: _FakeClient, table: str, user_id: str) -> list[_FakeQuery]:
    """Every recorded destructive (delete/update) query against `table`
    must carry an eq('user_id', user_id)."""
    hits = [
        q for q in client.queries if q._table == table and q.op in ("delete", "update")
    ]
    assert hits, f"no delete/update recorded for {table}"
    for q in hits:
        assert ("user_id", user_id) in q.eqs, (
            f"{table}.{q.op}() ran without eq('user_id', {user_id!r}) — "
            f"cross-tenant write! eqs={q.eqs}"
        )
    return hits


def test_delete_stripe_connection_is_user_scoped(fake_sb, store_mod):
    uid = str(uuid.uuid4())
    store_mod.delete_stripe_connection(uid)
    _scoped_deletes(fake_sb, "stripe_connections", uid)


def test_update_stripe_connection_is_user_scoped(fake_sb, store_mod):
    uid = str(uuid.uuid4())
    store_mod.update_stripe_connection(uid, {"connected": False})
    _scoped_deletes(fake_sb, "stripe_connections", uid)


def test_delete_notion_connection_is_user_scoped(fake_sb, store_mod):
    uid = str(uuid.uuid4())
    store_mod.delete_notion_connection(uid)
    _scoped_deletes(fake_sb, "notion_connections", uid)


def test_update_notion_connection_is_user_scoped(fake_sb, store_mod):
    uid = str(uuid.uuid4())
    store_mod.update_notion_connection(uid, {"connected": False})
    _scoped_deletes(fake_sb, "notion_connections", uid)


def test_delete_kg_for_user_scopes_both_tables(fake_sb, store_mod):
    uid = str(uuid.uuid4())
    store_mod.delete_kg_for_user(uid)
    _scoped_deletes(fake_sb, "kg_edges", uid)
    _scoped_deletes(fake_sb, "kg_nodes", uid)


def test_delete_agent_memory_for_user_is_user_scoped(fake_sb, store_mod):
    uid = str(uuid.uuid4())
    store_mod.delete_agent_memory_for_user(uid)
    _scoped_deletes(fake_sb, "agent_memory", uid)


def test_delete_agent_memory_by_kind_is_user_scoped(fake_sb, store_mod):
    """The Notion-disconnect purge path (kind='notion') must not delete other
    tenants' notion memories."""
    uid = str(uuid.uuid4())
    store_mod.delete_agent_memory(uid, kind="notion")
    hits = _scoped_deletes(fake_sb, "agent_memory", uid)
    # and it did also narrow by kind
    assert any(("kind", "notion") in q.eqs for q in hits)


def test_delete_stories_for_task_is_user_scoped(fake_sb, store_mod):
    uid = str(uuid.uuid4())
    store_mod.delete_stories_for_task(uid, "task-123")
    hits = _scoped_deletes(fake_sb, "stories", uid)
    assert any(("task_id", "task-123") in q.eqs for q in hits)


def test_update_playbook_entry_is_user_scoped(fake_sb, store_mod):
    """PATCH /api/playbook/{entry_id} passes entry_id straight from the URL, so
    without a user_id filter one tenant could overwrite another's entry."""
    uid = str(uuid.uuid4())
    store_mod.update_playbook_entry(uid, "entry-abc", {"confidence": 0.5})
    hits = _scoped_deletes(fake_sb, "business_playbook", uid)
    assert any(("id", "entry-abc") in q.eqs for q in hits)


def test_delete_client_view_is_user_scoped(fake_sb, store_mod):
    uid = str(uuid.uuid4())
    store_mod.delete_client_view(uid, "client-xyz")
    hits = _scoped_deletes(fake_sb, "client_view_cache", uid)
    assert any(("client_id", "client-xyz") in q.eqs for q in hits)
