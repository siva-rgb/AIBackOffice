"""Token encryption — fail-closed at startup.

The encryption subsystem is a **critical security primitive**: every Google OAuth
and Notion access token stored in the database is encrypted with this key. If
the key is missing, malformed, or silently generated at runtime, every restart
makes already-encrypted tokens unreadable — silent data loss.

This module is therefore **fail-closed**:

* `load_key()` raises `StartupError` if `TOKEN_ENCRYPTION_KEY` is unset,
  empty, or not a valid Fernet key.
* `load_key()` is called once at module import, so a misconfigured deployment
  fails the **process** before a single request can be served.
* There is **no** random-key fallback. Generating a fresh key on startup would
  mean today's encrypted tokens become unreadable after the next restart.
* The CI suite (M3.3) exercises the negative path via a subprocess that asserts
  the process exits non-zero with a descriptive error.

Key lifecycle is documented in `docs/sops/token-key-rotation.md` (M3.4).

Threat model (per security-engineering concept page):
* Adversary: insider with access to the database but not the secret store.
* Without this control: the adversary gets cleartext OAuth tokens for every
  user (account takeover across Google, Notion, Stripe Connect).
* With this control: the adversary gets Fernet ciphertexts that are useless
  without `TOKEN_ENCRYPTION_KEY`, which lives in the secret store.
* Failure mode covered: the developer who forgets to set the env var no
  longer ships an "everything works, but every restart destroys all tokens"
  build — the process refuses to start instead.
"""

from __future__ import annotations

import logging
import os

from cryptography.fernet import Fernet, InvalidToken

from ..config import settings

logger = logging.getLogger("kora.security.token_encryption")


class StartupError(RuntimeError):
    """Raised at startup when token encryption cannot be initialized.

    The FastAPI app catches this at import-time and exits with code 1, so a
    misconfigured deployment cannot serve requests. Tests assert on this type
    to distinguish "config error" from "transient decryption error".
    """


_KEY_ENV = "TOKEN_ENCRYPTION_KEY"
_TEST_HELP = "Generate one with: " 'python -c "from cryptography.fernet import Fernet; ' 'print(Fernet.generate_key().decode())"'


def _read_key() -> str:
    """Return the configured key string, or raise StartupError if missing.

    Order of precedence: pydantic settings (which already merged .env +
    process env) → direct `os.environ` fallback (kept for tests that
    `monkeypatch.setenv` before the Settings instance is reloaded).
    """
    raw = (settings.TOKEN_ENCRYPTION_KEY or os.environ.get(_KEY_ENV, "")).strip()
    if not raw:
        raise StartupError(
            f"{_KEY_ENV} is not set. {_TEST_HELP} " "Refusing to start: every restart would silently destroy all " "encrypted OAuth/Notion/Stripe tokens."
        )
    return raw


def load_key() -> Fernet:
    """Build and validate a Fernet instance from `TOKEN_ENCRYPTION_KEY`.

    Raises `StartupError` if the key is unset, empty, or not a valid 32-byte
    url-safe base64-encoded Fernet key. Callers MUST let the exception
    propagate so the process exits before serving any request.
    """
    key = _read_key()
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, TypeError) as exc:
        # Fernet raises ValueError on bad base64 length / TypeError on bad type.
        raise StartupError(
            f"{_KEY_ENV} is malformed ({exc}). {_TEST_HELP} " "Refusing to start: continuing would make new encryptions " "unreadable on the next restart."
        ) from exc


# Module-level singleton. Built at import time so any misconfiguration fails
# the process at boot, not on the first encrypted-token write. There is no
# `try/except` here — the exception propagates and aborts startup, which is
# the whole point.
_fernet: Fernet = load_key()


def get_fernet() -> Fernet:
    """Return the singleton Fernet instance (validated at startup)."""
    return _fernet


def encrypt_token(token: str) -> str:
    """Encrypt an OAuth/Notion/Stripe access or refresh token.

    Empty strings round-trip as empty strings — this matches the existing
    contract used by callers that may receive a `None` refresh token from
    the OAuth flow.
    """
    if not token:
        return ""
    return _fernet.encrypt(token.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    """Decrypt a previously-encrypted token. Empty strings round-trip as empty.

    Raises `InvalidToken` if the ciphertext was encrypted with a different
    key (the canonical "Google reconnect needed" signal — see tracker.md
    2026-07-15 row 477).
    """
    if not ciphertext:
        return ""
    try:
        return _fernet.decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        logger.warning("Token decryption failed: likely encrypted with a previous key. " "User must reconnect Google / Notion / Stripe Connect.")
        raise
