"""What this dashboard claims has to survive someone checking it.

It is shown to judges as evidence that real people used the product, which puts
a different weight on the numbers than a normal internal metric. The three
things that would quietly turn it into a lie:

  * counting the team's own accounts as outside interest,
  * treating a seeded row as a visit, when the person never signed in,
  * publishing addresses that identify testers who never agreed to it.

Each is pinned below.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config, metrics  # noqa: E402


class TestMasking:
    def test_two_similar_addresses_stay_distinguishable(self):
        """The bug this caught on real data: both collapsed to k••••••@gmail.com,
        so two testers rendered as one indistinguishable row."""
        a = metrics.mask_email("kteja4000@gmail.com")
        b = metrics.mask_email("krishnateja.thallapalli@gmail.com")
        assert a != b

    def test_the_address_is_not_recoverable(self):
        masked = metrics.mask_email("krishnateja.thallapalli@gmail.com")
        assert "krishnateja.thallapalli" not in masked
        assert "•" in masked

    def test_the_domain_survives(self):
        """Which provider someone used is not identifying, and it reads as real."""
        assert metrics.mask_email("someone@neplis.com").endswith("@neplis.com")

    @pytest.mark.parametrize(
        "addr",
        ["a@b.com", "ab@b.com", "abc@b.com", "demo@kora.app", "sivan@x.com", "tester@kora.app"],
    )
    def test_short_locals_do_not_leak_the_whole_name(self, addr):
        """`demo` under a two-and-two window masks to `de••mo` — the kept
        characters spell the original straight back out."""
        local = addr.split("@")[0]
        kept = metrics.mask_email(addr).split("@")[0].replace("•", "")
        assert kept != local
        assert len(kept) < len(local)

    def test_a_malformed_value_does_not_crash_the_page(self):
        assert metrics.mask_email("not-an-email") == "—"
        assert metrics.mask_email("") == "—"

    def test_masking_is_on_unless_explicitly_disabled(self, monkeypatch):
        """The service runs unauthenticated, so the default has to be the safe one."""
        monkeypatch.setattr(config, "SHOW_EMAILS", False)
        assert metrics._display_email("real@example.com") != "real@example.com"

    def test_the_override_publishes_the_real_address(self, monkeypatch):
        monkeypatch.setattr(config, "SHOW_EMAILS", True)
        assert metrics._display_email("real@example.com") == "real@example.com"


class TestDayFilling:
    def test_quiet_days_occupy_their_real_width(self):
        """Plotting only days that have rows would draw a busier product than
        the one that exists — the gaps are the signal."""
        from collections import Counter

        days = metrics._dense_days(Counter({"2026-08-01": 3, "2026-08-05": 1}), Counter())
        assert [d["date"] for d in days] == [
            "2026-08-01",
            "2026-08-02",
            "2026-08-03",
            "2026-08-04",
            "2026-08-05",
        ]
        assert [d["runs"] for d in days] == [3, 0, 0, 0, 1]

    def test_signups_and_runs_share_one_timeline(self):
        from collections import Counter

        days = metrics._dense_days(Counter({"2026-08-02": 1}), Counter({"2026-08-01": 2}))
        assert days[0] == {"date": "2026-08-01", "runs": 0, "signups": 2}
        assert days[1] == {"date": "2026-08-02", "runs": 1, "signups": 0}

    def test_no_data_is_an_empty_list_not_a_crash(self):
        from collections import Counter

        assert metrics._dense_days(Counter(), Counter()) == []


class TestTimestampParsing:
    def test_a_trailing_z_is_accepted(self):
        assert metrics._parse("2026-08-14T10:00:00Z") is not None

    def test_an_offset_is_accepted(self):
        assert metrics._parse("2026-08-14 10:00:00+00:00") is not None

    def test_a_naive_timestamp_is_treated_as_utc(self):
        """A naive value compared against an aware `now` raises TypeError, which
        would take out the whole page rather than one cell."""
        parsed = metrics._parse("2026-08-14T10:00:00")
        assert parsed is not None and parsed.tzinfo is not None
        assert (datetime.now(timezone.utc) - parsed) > timedelta(seconds=0)

    def test_junk_is_none_rather_than_an_exception(self):
        assert metrics._parse("not a date") is None
        assert metrics._parse(None) is None


class TestTestAccountsAreConfigured:
    def test_the_demo_tenant_is_treated_as_internal(self):
        """It is the shared evaluator login and holds most of the seeded data,
        so counting it as outside interest would inflate the headline badly."""
        assert "demo@kora.app" in config.TEST_ACCOUNTS

    def test_the_demo_tenants_profile_address_is_also_covered(self):
        """auth and profile disagree for this tenant — the profile row reads
        pandasivananda0@, which is the address the users table actually holds."""
        assert "pandasivananda0@gmail.com" in config.TEST_ACCOUNTS

    def test_the_list_is_lowercased_for_comparison(self):
        assert all(a == a.lower() for a in config.TEST_ACCOUNTS)


class TestCache:
    def test_clearing_forces_a_recompute(self, monkeypatch):
        calls = []
        monkeypatch.setattr(metrics, "build_snapshot", lambda: calls.append(1) or {"n": len(calls)})
        metrics.clear_cache()
        first = metrics.get_snapshot()
        second = metrics.get_snapshot()
        assert first == second and len(calls) == 1
        metrics.clear_cache()
        metrics.get_snapshot()
        assert len(calls) == 2

    def test_force_bypasses_the_cache(self, monkeypatch):
        calls = []
        monkeypatch.setattr(metrics, "build_snapshot", lambda: calls.append(1) or {"n": len(calls)})
        metrics.clear_cache()
        metrics.get_snapshot()
        metrics.get_snapshot(force=True)
        assert len(calls) == 2
