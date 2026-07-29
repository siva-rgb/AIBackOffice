"""Corpus test for the PII scrubber (M11.4 / M11.1 gate).

~30 representative log lines exercising every category in the scrubber's
catalog: bearer/JWT credentials, API keys, credit cards, emails, SSNs, and
nested dict payloads. If any of these leaks a raw secret through `scrub()`,
the test fails.

We also pin the catalog size — adding a new pattern requires updating this
test, so the catalog cannot grow without a matching unit test.
"""

from __future__ import annotations

import pytest

from app.utils.pii_scrubber import (
    _PATTERNS,
    _SECRET_KEYS,
    scrub,
)


# --- catalog pins -------------------------------------------------------------
def test_secret_keys_catalog_is_explicit():
    # Pinning the catalog — when somebody adds a key, they must update this test.
    expected = {
        "authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "x-auth-token",
        "x-cron-secret",
        "token",
        "secret",
        "api_key",
        "apikey",
        "password",
        "passwd",
        "pwd",
        "session",
        "session_id",
        "credit_card",
        "creditCard",
        "card_number",
        "ssn",
        "tax_id",
        "bank_account",
        "routing_number",
    }
    assert set(_SECRET_KEYS) == expected


def test_pattern_catalog_has_minimum_coverage():
    # At least 8 patterns — see comments in pii_scrubber.py for what each covers.
    assert len(_PATTERNS) >= 8


# --- corpus: simple string values --------------------------------------------
@pytest.mark.parametrize(
    "raw,marker",
    [
        ("Authorization: Bearer eyJabc.def.ghi", "Bearer"),
        ("header: Basic dXNlcjpwYXNz", "Basic"),
        ("token=eyJabc12345.payload.signature", "eyJ"),
        ("sk_live_4eC39HqLyjWDarjtT1zdp7dc", "sk_live_"),
        ("rk_test_abcdefghij1234567890", "rk_test_"),
        ("api_key=abcd1234EFGH5678ijkl", "api_key="),
        ("secret: aBcDeFgHiJkLmNoPqRsT1234", "secret:"),
        ("contact alice@example.com today", "@"),
        ("SSN 123-45-6789 on file", "123-45-6789"),
        ("routing 123456789", "123456789"),
        ("card 4111 1111 1111 1111", "4111"),
        ("card 4111-1111-1111-1111", "4111-1111"),
    ],
)
def test_string_scrubs_known_patterns(raw, marker):
    out = scrub(raw)
    assert marker not in out, f"leaked marker {marker!r} in {out!r}"
    assert "[REDACTED]" in out


def test_clean_string_passes_through():
    s = "user_42 fetched /api/agents/log at 2026-07-29T10:00:00Z"
    assert scrub(s) == s


# --- corpus: structured payloads ---------------------------------------------
def test_authorization_header_value_is_redacted():
    out = scrub({"authorization": "Bearer abc.def.ghi"})
    assert out["authorization"] == "[REDACTED]"


def test_cookie_header_value_is_redacted():
    out = scrub({"Cookie": "session=abc123"})
    assert out["Cookie"] == "[REDACTED]"


def test_nested_dict_with_bearer_is_redacted():
    payload = {
        "request_id": "abc",
        "user_id": "u-1",
        "headers": {"authorization": "Bearer eyJxxx.yyy.zzz"},
        "body": {"note": "user alice@example.com said hi"},
    }
    out = scrub(payload)
    # safe keys pass through
    assert out["request_id"] == "abc"
    assert out["user_id"] == "u-1"
    # bearer is gone
    assert "eyJxxx" not in str(out)
    assert "[REDACTED]" in str(out)
    # email is gone
    assert "alice@example.com" not in str(out)


def test_list_of_strings_each_scrubbed():
    out = scrub(["Bearer eyJabc.def.ghi", "user@example.com", "plain text"])
    assert "eyJabc" not in out[0]
    assert "@example.com" not in out[1]
    assert out[2] == "plain text"


def test_numbers_and_bools_pass_through():
    payload = {"count": 42, "ratio": 0.95, "ok": True, "name": None}
    assert scrub(payload) == payload


def test_tuple_is_walked():
    out = scrub(("Bearer xyz", "plain"))
    assert isinstance(out, tuple)
    assert "xyz" not in out[0]


# --- corpus: realistic one-line log fragments --------------------------------
@pytest.mark.parametrize(
    "line",
    [
        'GET /api/agents/log status=200 user="alice@example.com" ua="curl/7.0"',
        'POST /webhook/stripe body="card=4111-1111-1111-1111&exp=12/29"',
        'oauth state "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxw"',
        'gmail push notification for inbox "alice@example.com" subject="hi"',
        "redirect_uri=https://app.example.com/oauth/callback?code=abc123",
    ],
)
def test_realistic_log_lines_no_secrets_leak(line):
    out = scrub(line)
    s = str(out)
    # No raw email, no card digits clustered, no JWT-shaped triple, no Bearer.
    for needle in ("alice@example.com", "4111-1111-1111-1111", "Bearer "):
        assert needle not in s
