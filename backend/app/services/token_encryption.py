from __future__ import annotations

import os

from cryptography.fernet import Fernet

from ..config import settings


def _make_fernet() -> Fernet:
    key = (settings.TOKEN_ENCRYPTION_KEY or os.environ.get("TOKEN_ENCRYPTION_KEY", "")).strip()
    if not key:
        raise RuntimeError(
            "TOKEN_ENCRYPTION_KEY is not set. Generate one with: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


try:
    _fernet = _make_fernet()
except RuntimeError:
    if settings.KORA_DATA_BACKEND == "mock":
        _fernet = None
    else:
        raise


def _get_fernet() -> Fernet:
    if _fernet is None:
        raise RuntimeError(
            "TOKEN_ENCRYPTION_KEY is not set — encryption is unavailable. "
            "Set the key to enable Google OAuth token encryption."
        )
    return _fernet


def encrypt_token(token: str) -> str:
    if not token:
        return ""
    return _get_fernet().encrypt(token.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    return _get_fernet().decrypt(ciphertext.encode()).decode()
