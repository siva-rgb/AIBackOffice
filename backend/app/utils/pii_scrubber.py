"""PII & secrets scrubber for log lines (M11.1, M11.4).

A single pure function — `scrub(value)` — that takes any Python value (dict,
list, str, number) and returns a copy with known-secret-shaped substrings
replaced by `[REDACTED]`. The middleware walks every request field through it
before the line hits the log file.

Design rules (don't relax these without an L4 verifier):

  1. **Pure.** No globals, no I/O, no time-of-day checks. Easy to unit-test on
     a corpus (M11.4 gate).
  2. **Conservative.** When in doubt, redact. False positives (over-redaction)
     are recoverable; false negatives leak secrets.
  3. **Recursive on dicts/lists.** Walks nested structures — log payloads are
     almost always JSON-shaped.
  4. **Allowlist for keys that should pass through** — opaque ids like
     `request_id`, `user_id`, `created_at`, route templates. Anything not on
     the allowlist and not on the deny-pattern list is left alone.
  5. **Pattern catalog** lives at module bottom. The unit test pins the
     catalog so changes are caught.
"""

from __future__ import annotations

import re
from typing import Any


# Keys whose values are NEVER scrubbed — opaque ids and timestamps. Anything
# off this list goes through the value scrubber.
_SAFE_KEYS: frozenset[str] = frozenset(
    {
        "request_id",
        "user_id",
        "created_at",
        "updated_at",
        "id",
        "agent_type",
        "triggered_by",
        "status",
        "model_used",
        "action",
        "method",
        "path",
        "route_template",
        "status_code",
        "latency_ms",
        "client_ip",
        "user_agent",
        "service",
        "environment",
        "dataBackend",
        "aiBackend",
        "activeModel",
        "today",
        "thisWeek",
        "byType",
        "byTrigger",
        "successRate",
        "avgLatencyMs",
        "totalCostUsd",
        "window_days",
        "p50LatencyMs",
        "p95LatencyMs",
        "totalTokens",
        "costByModel",
        "topErrors",
        "daily",
    }
)

# Keys whose VALUES are always redacted, regardless of content — header names
# that conventionally carry credentials, plus query-param names that look like
# secrets.
_SECRET_KEYS: frozenset[str] = frozenset(
    {
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
)

# Substring patterns — any of these hitting a string value triggers `[REDACTED]`.
# Each compiled regex must be *anchored* on a clearly-secret-shaped token so we
# don't accidentally redact words like "token" in user-visible prose.
_PATTERNS: tuple[re.Pattern[str], ...] = (
    # OAuth2 / JWT — `Bearer xxx`, `Basic xxx`
    re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._\-+/=]+"),
    # JSON Web Tokens — three base64url segments separated by dots, first seg starts with `eyJ`
    re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"),
    # Stripe live/test/restricted keys
    re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{16,}"),
    re.compile(r"\b(?:sk|rk)_test_[A-Za-z0-9]{16,}"),
    # Generic API key shapes — long base64-ish blobs prefixed with `key=` / `api_key=`
    re.compile(r"(?i)(?:api[_-]?key|secret|token)\s*[=:]\s*[A-Za-z0-9._\-+/=]{16,}"),
    # Credit card numbers — 13-19 digits, optional spaces/dashes between groups.
    # Anchored with word boundaries; Luhn check is out of scope here.
    re.compile(r"\b(?:\d[ -]?){13,19}\b"),
    # Email addresses — RFC-5322 is huge; this is a pragmatic subset.
    re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
    # US SSN — 3-2-4
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    # US bank routing — 9 digits, often space/dash-separated in groups.
    re.compile(r"\b\d{9}\b"),
)

_REDACTED = "[REDACTED]"


def _scrub_str(s: str) -> str:
    """Apply every pattern once. Order matters only for overlapping matches —
    each regex is independent and we redact all hits."""
    out = s
    for pat in _PATTERNS:
        out = pat.sub(_REDACTED, out)
    return out


def scrub(value: Any, *, allow_keys: frozenset[str] | None = None) -> Any:
    """Walk `value` and return a redacted copy.

    Strings: pattern-matched. Dicts/lists: walked recursively. Numbers/bools/
    None: passed through unchanged (no secret shape possible).
    """
    allow = allow_keys if allow_keys is not None else _SAFE_KEYS
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for k, v in value.items():
            key_str = str(k)
            # Header names arrive case-insensitively (Cookie / cookie / COOKIE
            # are the same header); do the same for the deny-list so a caller
            # doesn't have to canonicalise.
            if key_str.lower() in _SECRET_KEYS:
                out[k] = _REDACTED
            elif key_str in allow or key_str.lower() in {k.lower() for k in allow}:
                out[k] = v
            else:
                out[k] = scrub(v, allow_keys=allow)
        return out
    if isinstance(value, list):
        return [scrub(v, allow_keys=allow) for v in value]
    if isinstance(value, tuple):
        return tuple(scrub(v, allow_keys=allow) for v in value)
    if isinstance(value, str):
        return _scrub_str(value)
    return value
