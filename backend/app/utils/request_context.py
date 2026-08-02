"""Per-request correlation context (M11.2).

Sibling of `request_cache.py` — same ContextVar pattern, but for *observability*
state instead of memoization. Any service-layer function that wants to stamp
the current HTTP request onto a log row or a Sentry span can pull it without
threading a parameter through every callsite.

Two keys:

  * `current_request_id` — opaque uuid4 hex; minted by the access-log middleware
    (re-using an inbound `X-Request-ID` if it parses as a uuid), echoed back on
    the response, and propagated to `agent_logs` rows + Sentry tags.
  * `current_user_id`    — set by the auth dependency; lets `agent_logger` stamp
    the tenant id on rows when the caller didn't already pass it explicitly.

Both are scoped to the request lifetime via `begin_request_context` /
`end_request_context` (called from middleware), so a request that finishes is
guaranteed to clear its slot — no cross-request bleed.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from typing import Any


_request_id_var: ContextVar[str | None] = ContextVar("kora_request_id", default=None)
_user_id_var: ContextVar[str | None] = ContextVar("kora_user_id", default=None)


def _is_uuid_hex(value: str) -> bool:
    """True iff `value` parses as a uuid4 hex string (the only shape we re-use).

    Anything else from the inbound header is treated as a client mistake and we
    mint our own — accepting arbitrary bytes would let an attacker pin logs to
    a guessable id.
    """
    try:
        u = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return u.hex == value


def begin_request_context(*, inbound_request_id: str | None = None, user_id: str | None = None) -> str:
    """Open a new request scope.

    Returns the request id that was actually used (either re-used from the
    inbound header if it looked safe, or freshly minted).
    """
    if inbound_request_id and _is_uuid_hex(inbound_request_id):
        rid = inbound_request_id
    else:
        rid = uuid.uuid4().hex
    _request_id_var.set(rid)
    if user_id is not None:
        _user_id_var.set(user_id)
    return rid


def end_request_context() -> None:
    """Close the scope. Idempotent — calling it twice is a no-op."""
    _request_id_var.set(None)
    _user_id_var.set(None)


def current_request_id() -> str | None:
    return _request_id_var.get()


def set_user_id(user_id: str | None) -> None:
    """Stamp the authenticated user_id onto the current scope (called by auth deps)."""
    _user_id_var.set(user_id)


def current_user_id() -> str | None:
    return _user_id_var.get()


def snapshot() -> dict[str, Any]:
    """A small dict for places that want both values at once (e.g. Sentry tags)."""
    return {
        "request_id": _request_id_var.get(),
        "user_id": _user_id_var.get(),
    }
