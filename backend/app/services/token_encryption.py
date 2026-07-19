from __future__ import annotations

import os

from cryptography.fernet import Fernet

from ..config import settings

# Cache a single Fernet instance for the process lifetime. The key MUST come from
# settings (which loads .env) — reading os.environ alone misses it, because
# pydantic-settings populates `settings`, not the process environment. Without a
# stable key we'd mint a random one per process, so every restart would make
# previously-encrypted Google tokens undecryptable. Fall back to os.environ, then
# a temporary key (dev only — tokens won't survive a restart in that case).
def _make_fernet() -> Fernet:
    key = (settings.TOKEN_ENCRYPTION_KEY or os.environ.get("TOKEN_ENCRYPTION_KEY", "")).strip()
    if not key:
        key = Fernet.generate_key().decode()
    return Fernet(key.encode() if isinstance(key, str) else key)

_fernet = _make_fernet()


def _get_fernet() -> Fernet:
    return _fernet


def encrypt_token(token: str) -> str:
    if not token:
        return ""
    return _get_fernet().encrypt(token.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    return _get_fernet().decrypt(ciphertext.encode()).decode()
