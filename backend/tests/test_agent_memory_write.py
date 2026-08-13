"""Semantic memory must still record when `embedding_vec` is unavailable.

PostgREST validates writes against its **schema cache** and rejects the whole
row with PGRST204 when a column isn't in it. Two different causes produce the
identical error: the optional M10 pgvector migration was never run, or it was
run and PostgREST's cache is stale.

Staging hit the second. `embedding_vec` existed in Postgres — a plain SELECT on
it returned 200 — while every write failed PGRST204. `remember()` is
best-effort and swallows exceptions, so `agent_memory` sat at 0 rows while the
reindex endpoint reported "playbook: 7, graph_fact: 6" as though it had stored
them. Once the cache refreshed, the same reindex stored 13/13.

Retrying without the column keeps the memory under either cause. The JSONB
`embedding` column is what the default recall backend reads.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def ss(monkeypatch):
    """Import supabase_store hermetically.

    Its module-level `_sb = get_supabase()` would raise under the mock-mode
    conftest, so the pooled client is faked before the import — same pattern as
    tests/security/test_tenant_isolation_destructive_writes.py.
    """
    from app.clients import pool

    monkeypatch.setattr(pool, "get_supabase", lambda: object())
    from app.backends import supabase_store as module

    monkeypatch.setattr(module, "_HAS_EMBEDDING_VEC", None, raising=False)
    return module


class FakeExec:
    def __init__(self, data):
        self.data = data


class FakeChain:
    """Captures the payload and optionally raises the PostgREST error."""

    def __init__(self, sink, fail_on_vec):
        self.sink = sink
        self.fail_on_vec = fail_on_vec
        self.payload = None

    def insert(self, _table, body):
        self.payload = body
        return self

    def raw_table(self, _table):
        return self

    def update(self, body):
        self.payload = body
        return self

    def eq(self, *_a, **_kw):
        return self

    def execute(self):
        self.sink.append(self.payload)
        if self.fail_on_vec and "embedding_vec" in (self.payload or {}):
            raise RuntimeError("{'code': 'PGRST204', 'message': \"Could not find the 'embedding_vec' column of 'agent_memory' in the schema cache\"}")
        return FakeExec([{**(self.payload or {}), "id": "row-1"}])


@pytest.fixture
def writes(monkeypatch, ss):
    """Patch repo() and return (attempts, set_missing_column)."""
    attempts: list = []
    state = {"fail": False}
    monkeypatch.setattr(ss, "repo", lambda _uid: FakeChain(attempts, state["fail"]))
    monkeypatch.setattr(ss, "_HAS_EMBEDDING_VEC", None, raising=False)

    def set_missing(flag: bool):
        state["fail"] = flag
        monkeypatch.setattr(ss, "repo", lambda _uid: FakeChain(attempts, state["fail"]))

    return attempts, set_missing


class TestVectorColumnPresent:
    def test_writes_the_vector_when_the_column_exists(self, writes, ss):
        attempts, _ = writes
        ss._write_agent_memory("u1", {"content": "hi", "embedding_vec": "[0.1]"}, existing_id=None)
        assert len(attempts) == 1
        assert "embedding_vec" in attempts[0]


class TestVectorColumnMissing:
    def test_retries_without_the_vector_column(self, writes, ss):
        """The regression: the whole row used to be lost."""
        attempts, set_missing = writes
        set_missing(True)
        result = ss._write_agent_memory("u1", {"content": "hi", "embedding_vec": "[0.1]"}, existing_id=None)

        assert len(attempts) == 2, "expected a retry"
        assert "embedding_vec" in attempts[0]
        assert "embedding_vec" not in attempts[1]
        assert result.data[0]["content"] == "hi"  # the memory survived

    def test_later_writes_skip_the_doomed_first_attempt(self, writes, ss):
        """Probe once, not on every single remember() call."""
        attempts, set_missing = writes
        set_missing(True)
        ss._write_agent_memory("u1", {"content": "a", "embedding_vec": "[0.1]"}, existing_id=None)
        before = len(attempts)
        ss._write_agent_memory("u1", {"content": "b", "embedding_vec": "[0.2]"}, existing_id=None)
        assert len(attempts) == before + 1
        assert "embedding_vec" not in attempts[-1]

    def test_updates_fall_back_too(self, writes, ss):
        attempts, set_missing = writes
        set_missing(True)
        ss._write_agent_memory("u1", {"content": "hi", "embedding_vec": "[0.1]"}, existing_id="row-9")
        assert len(attempts) == 2
        assert "embedding_vec" not in attempts[1]

    def test_an_unrelated_error_still_raises(self, writes, ss):
        """Only the missing-column case is recoverable; nothing else is masked."""
        attempts = []

        class Boom(FakeChain):
            def execute(self):
                raise RuntimeError("{'code': '23505', 'message': 'duplicate key value'}")

        import pytest as _pytest

        ss.repo = lambda _uid: Boom(attempts, False)
        with _pytest.raises(RuntimeError, match="23505"):
            ss._write_agent_memory("u1", {"content": "hi", "embedding_vec": "[0.1]"}, existing_id=None)


class TestErrorMatching:
    @pytest.mark.parametrize(
        "message,expected",
        [
            ("{'code': 'PGRST204', 'message': \"Could not find the 'embedding_vec' column\"}", True),
            ("Could not find the 'embedding_vec' column of 'agent_memory' in the schema cache", True),
            ("{'code': 'PGRST204', 'message': \"Could not find the 'salience' column\"}", False),
            ("duplicate key value violates unique constraint", False),
        ],
    )
    def test_only_the_vector_column_error_matches(self, message, expected, ss):
        assert ss._missing_vector_column(RuntimeError(message)) is expected
