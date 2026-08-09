"""The digest dedupe key must be a real UUID.

Regression guard for the staging UAT finding: `_digest_source_id` returned
`f"digest:{day}"`, which the in-memory mock store accepted happily (string
comparison) while Postgres rejected it with 22P02
`invalid input syntax for type uuid` — `manager_tasks.source_record_id` is a UUID
column. The result was a 500 on the whole digest endpoint.

It stayed hidden twice over: the mock store never type-checks, and the
not-connected-to-Gmail path returns before this line is reached. It only appeared
once a real tenant connected Google against a real database.
"""

from __future__ import annotations

import uuid

from app.services.alert_agent import _digest_source_id


def test_source_id_is_a_valid_uuid():
    """Postgres must be able to cast it — this is the assertion that matters."""
    value = _digest_source_id("2026-08-09")
    assert uuid.UUID(value)  # raises ValueError if not a well-formed UUID
    assert value == str(uuid.UUID(value)), "should be canonical UUID text"


def test_source_id_is_deterministic_for_the_same_day():
    """Dedupe depends on it: two runs on one day must collide."""
    assert _digest_source_id("2026-08-09") == _digest_source_id("2026-08-09")


def test_source_id_differs_across_days():
    """...and must not collide across days, or tomorrow's digest is suppressed."""
    days = ["2026-08-08", "2026-08-09", "2026-08-10", "2027-01-01"]
    ids = [_digest_source_id(d) for d in days]
    assert len(set(ids)) == len(days)


def test_source_id_never_contains_the_raw_prefix():
    """Guards against a well-meaning revert to the readable-but-invalid form."""
    assert not _digest_source_id("2026-08-09").startswith("digest:")
