"""Cryptographically random, session-bound OAuth state tokens (M7b).

OAuth `state` must never carry a raw `user_id` — an attacker who tricks a
victim into visiting `/connect` could bind their Google/Stripe/Notion account
to the victim's Kora user. Instead we issue a signed, time-limited token that
embeds the user id and is verified on callback.

Uses HMAC-SHA256 over a base64url JSON payload, keyed from
`TOKEN_ENCRYPTION_KEY` (same secret store as token encryption).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

from ..config import settings

_TTL_SECONDS = 600  # 10 minutes — long enough for the browser OAuth round-trip


def _signing_key() -> bytes:
    raw = (settings.TOKEN_ENCRYPTION_KEY or "").strip()
    if not raw:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY required for OAuth state signing")
    return raw.encode()


def issue_oauth_state(user_id: str) -> str:
    """Return a random, HMAC-signed state token bound to `user_id`."""
    payload = {
        "uid": user_id,
        "nonce": secrets.token_urlsafe(16),
        "exp": int(time.time()) + _TTL_SECONDS,
    }
    data = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = hmac.new(_signing_key(), data.encode(), hashlib.sha256).hexdigest()
    return f"{data}.{sig}"


def verify_oauth_state(state: str | None) -> str | None:
    """Validate `state` and return the bound user id, or None if invalid/expired."""
    if not state or "." not in state:
        return None
    data, sig = state.rsplit(".", 1)
    expected = hmac.new(_signing_key(), data.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    pad = "=" * (-len(data) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(data + pad))
    except (json.JSONDecodeError, ValueError):
        return None
    if payload.get("exp", 0) < int(time.time()):
        return None
    uid = payload.get("uid")
    return uid if isinstance(uid, str) and uid else None
