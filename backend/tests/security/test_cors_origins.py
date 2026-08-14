"""CORS must allow every origin the deployment actually answers on — and no more.

Cloud Run serves each service on TWO hostnames: the legacy
`SERVICE-HASH-REGION.a.run.app` and the newer
`SERVICE-PROJECTNUMBER.REGION.run.app`. The console shows the new one, our
deploy scripts read the old one. Both load the app, so a visitor can arrive on
either — but only the single configured origin passed CORS. The page rendered
and every API call was rejected, surfacing in the browser as "Failed to fetch",
which looks like a network fault rather than a policy decision. That cost real
debugging time and hit a real user.

Parsing is the whole fix, so these pin both halves: every listed origin is
allowed, and widening the list must not become a wildcard.
"""

from __future__ import annotations

import importlib

import pytest


def _origins_for(monkeypatch, value: str, environment: str = "production") -> list[str]:
    """Re-import main with a given FRONTEND_ORIGIN and return the parsed list."""
    from app import config

    monkeypatch.setattr(config.settings, "FRONTEND_ORIGIN", value)
    monkeypatch.setattr(config.settings, "ENVIRONMENT", environment)
    import app.main as main

    importlib.reload(main)
    return list(main._cors_origins)


class TestParsing:
    def test_a_single_origin_still_works(self, monkeypatch):
        assert _origins_for(monkeypatch, "https://a.example") == ["https://a.example"]

    def test_both_cloud_run_hostnames_are_allowed(self, monkeypatch):
        """The regression: only one of the two was configured."""
        got = _origins_for(
            monkeypatch,
            "https://kora-frontend-m7hwifxt4q-uc.a.run.app,https://kora-frontend-1047233401635.us-central1.run.app",
        )
        assert "https://kora-frontend-m7hwifxt4q-uc.a.run.app" in got
        assert "https://kora-frontend-1047233401635.us-central1.run.app" in got

    def test_surrounding_whitespace_is_tolerated(self, monkeypatch):
        """Hand-edited env vars and YAML pick up spaces."""
        got = _origins_for(monkeypatch, "  https://a.example , https://b.example  ")
        assert got == ["https://a.example", "https://b.example"]

    def test_empty_entries_are_dropped(self, monkeypatch):
        """A trailing comma must not inject an empty origin."""
        got = _origins_for(monkeypatch, "https://a.example,,")
        assert got == ["https://a.example"]
        assert "" not in got

    def test_an_unset_value_yields_no_origins(self, monkeypatch):
        """Better to allow nothing than to allow everything."""
        assert _origins_for(monkeypatch, "") == []


class TestStaysRestrictive:
    def test_no_wildcard_is_introduced(self, monkeypatch):
        got = _origins_for(monkeypatch, "https://a.example,https://b.example")
        assert "*" not in got

    def test_localhost_is_not_allowed_in_production(self, monkeypatch):
        """The existing guarantee — widening the list must not weaken it."""
        got = _origins_for(monkeypatch, "https://a.example", environment="production")
        assert not any("localhost" in o or "127.0.0.1" in o for o in got)

    def test_localhost_is_still_allowed_outside_production(self, monkeypatch):
        got = _origins_for(monkeypatch, "http://localhost:3000", environment="development")
        assert "http://localhost:3000" in got
        assert "http://localhost:3001" in got

    def test_an_unlisted_origin_is_absent(self, monkeypatch):
        got = _origins_for(monkeypatch, "https://a.example,https://b.example")
        assert "https://evil.example" not in got


@pytest.fixture(autouse=True)
def _restore():
    """Leave app.main as the rest of the suite expects it."""
    yield
    import app.main as main

    importlib.reload(main)
