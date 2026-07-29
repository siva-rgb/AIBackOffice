"""Context-var set/reset semantics for M11.2.

Three properties matter:

  1. `current_request_id()` is None when no scope is open.
  2. Two concurrent `begin_request_context()` calls don't leak — values set
     inside one don't survive into the other (ContextVar semantics).
  3. `end_request_context()` is idempotent — calling it twice doesn't raise.
"""

from __future__ import annotations

import asyncio
import uuid

from app.utils.request_context import (
    begin_request_context,
    current_request_id,
    current_user_id,
    end_request_context,
    set_user_id,
)


def setup_function(_):
    end_request_context()


def teardown_function(_):
    end_request_context()


def test_default_is_none():
    assert current_request_id() is None
    assert current_user_id() is None


def test_begin_mints_a_uuid_hex():
    rid = begin_request_context()
    try:
        assert rid == current_request_id()
        # uuid4 hex — 32 chars, all hex.
        assert len(rid) == 32
        assert all(c in "0123456789abcdef" for c in rid)
    finally:
        end_request_context()


def test_inbound_uuid_hex_is_reused():
    sample = uuid.uuid4().hex
    rid = begin_request_context(inbound_request_id=sample)
    try:
        assert rid == sample
    finally:
        end_request_context()


def test_inbound_garbage_is_ignored_and_replaced():
    bad_inputs = ["not-a-uuid", "<script>alert(1)</script>", "", "1234567"]
    for bad in bad_inputs:
        rid = begin_request_context(inbound_request_id=bad)
        try:
            assert rid != bad
            assert len(rid) == 32
        finally:
            end_request_context()


def test_end_is_idempotent():
    begin_request_context()
    end_request_context()
    # Second call must not raise and must leave the var at None.
    end_request_context()
    assert current_request_id() is None


def test_set_user_id_persists_in_scope():
    begin_request_context()
    try:
        set_user_id("user-1")
        assert current_user_id() == "user-1"
    finally:
        end_request_context()
    assert current_user_id() is None


async def test_concurrent_requests_do_not_leak():
    """Two concurrent tasks, distinct request ids, no cross-pollination."""
    results: dict[str, str | None] = {}

    async def task(label: str, rid: str):
        begin_request_context(inbound_request_id=rid)
        try:
            await asyncio.sleep(0.01)
            # What *this* task sees must be its own id, not another task's.
            results[f"{label}_own"] = current_request_id()
            await asyncio.sleep(0.01)
            results[f"{label}_again"] = current_request_id()
        finally:
            end_request_context()

    rid_a = uuid.uuid4().hex
    rid_b = uuid.uuid4().hex
    await asyncio.gather(task("a", rid_a), task("b", rid_b))
    assert results["a_own"] == rid_a
    assert results["a_again"] == rid_a
    assert results["b_own"] == rid_b
    assert results["b_again"] == rid_b
