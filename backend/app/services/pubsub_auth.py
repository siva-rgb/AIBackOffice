"""Google Pub/Sub push JWT verification (M7c).

When a push subscription is configured with authentication, Google sends an
OIDC bearer token in the Authorization header. This module verifies that token
against Google's public keys before accepting a Gmail watch notification.

Set `GMAIL_PUBSUB_AUDIENCE` to the push endpoint URL (e.g.
`https://api.example.com/api/gmail/push`). When empty, verification is
skipped so local dev without Pub/Sub infra still works.
"""

from __future__ import annotations

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from ..config import settings


def verify_pubsub_push_token(authorization: str | None) -> bool:
    """Return True when the bearer token is a valid Google OIDC token for our audience."""
    audience = (settings.GMAIL_PUBSUB_AUDIENCE or "").strip()
    if not audience:
        return True  # dev / push not secured yet

    if not authorization or not authorization.lower().startswith("bearer "):
        return False

    token = authorization.split(" ", 1)[1].strip()
    if not token:
        return False

    try:
        id_token.verify_oauth2_token(token, google_requests.Request(), audience=audience)
        return True
    except Exception:
        return False
