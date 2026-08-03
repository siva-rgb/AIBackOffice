"""M3 — Token Encryption Fail-Closed.

Tests cover four scenarios, in order from cheapest to most expensive:

1. Module-level: `load_key()` raises `StartupError` if `TOKEN_ENCRYPTION_KEY`
   is unset, empty, or malformed.
2. Round-trip: with a valid key, `encrypt_token`/`decrypt_token` invert.
3. Empty-string contract: empty tokens round-trip as empty (callers depend
   on this for OAuth `refresh_token=None`).
4. **Startup smoke test** (M3.3): a subprocess that imports the module with
   `TOKEN_ENCRYPTION_KEY=""` exits non-zero with a descriptive error. This
   is the canonical M3 gate: "Starting the app without `TOKEN_ENCRYPTION_KEY`
   exits non-zero with a descriptive error instead of booting" (PLAN.md M3).
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest

# ── Module under test ───────────────────────────────────────────────────────
# Importing `token_encryption` triggers the module-level `load_key()`, so the
# test process must already have a valid key set. `conftest.py` handles that
# for the whole suite; this import works under that assumption.
from app.services.token_encryption import (
    StartupError,
    decrypt_token,
    encrypt_token,
    load_key,
)


# ── 1. Module-level failure paths ────────────────────────────────────────────


def test_load_key_raises_when_unset(monkeypatch):
    """No env var → StartupError, never a random key."""
    monkeypatch.setattr("app.services.token_encryption.settings.TOKEN_ENCRYPTION_KEY", "")
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)
    with pytest.raises(StartupError) as exc_info:
        load_key()
    msg = str(exc_info.value)
    assert "TOKEN_ENCRYPTION_KEY" in msg
    assert "Refusing to start" in msg


def test_load_key_raises_when_whitespace(monkeypatch):
    """Whitespace-only key (e.g. accidental newline) is treated as unset."""
    monkeypatch.setattr("app.services.token_encryption.settings.TOKEN_ENCRYPTION_KEY", "   \n  ")
    with pytest.raises(StartupError):
        load_key()


def test_load_key_raises_when_malformed(monkeypatch):
    """A non-Fernet string → StartupError with `malformed` in the message."""
    monkeypatch.setattr(
        "app.services.token_encryption.settings.TOKEN_ENCRYPTION_KEY",
        "this-is-not-a-fernet-key",
    )
    with pytest.raises(StartupError) as exc_info:
        load_key()
    assert "malformed" in str(exc_info.value)


def test_load_key_returns_fernet_with_valid_key(monkeypatch):
    """A real Fernet key round-trips through load_key() without raising."""
    from cryptography.fernet import Fernet

    valid = Fernet.generate_key().decode()
    monkeypatch.setattr("app.services.token_encryption.settings.TOKEN_ENCRYPTION_KEY", valid)
    f = load_key()
    assert isinstance(f, Fernet)


# ── 2. Round-trip ───────────────────────────────────────────────────────────


def test_encrypt_decrypt_round_trip():
    plaintext = "ya29.a0AfH6SMBxx-fake-google-access-token"
    ciphertext = encrypt_token(plaintext)
    assert ciphertext != plaintext
    assert decrypt_token(ciphertext) == plaintext


def test_encrypt_produces_different_ciphertexts_per_call():
    """Fernet uses a random IV — encrypting the same plaintext twice must
    produce different ciphertexts. Catches accidental deterministic-mode
    regressions (e.g. someone passing `Fernet(key)` twice into the same
    instance)."""
    a = encrypt_token("same-token")
    b = encrypt_token("same-token")
    assert a != b
    assert decrypt_token(a) == decrypt_token(b) == "same-token"


# ── 3. Empty-string contract (callers depend on this) ───────────────────────


def test_encrypt_empty_string_returns_empty():
    assert encrypt_token("") == ""


def test_decrypt_empty_string_returns_empty():
    assert decrypt_token("") == ""


# ── 4. Startup smoke test (M3.3) ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad_key, expected_fragment",
    [
        ("", "is not set"),
        ("not-a-real-fernet-key", "malformed"),
    ],
)
def test_subprocess_exits_nonzero_without_valid_key(bad_key, expected_fragment):
    """Spawn a fresh Python subprocess that imports `token_encryption` with a
    bad `TOKEN_ENCRYPTION_KEY`. The module-level `load_key()` must abort the
    process with a non-zero exit code and a descriptive message.

    This is the exact M3 gate: "Starting the app without `TOKEN_ENCRYPTION_KEY`
    exits non-zero with a descriptive error instead of booting" (PLAN.md M3).
    """
    script = textwrap.dedent(
        """
        import os
        os.environ["TOKEN_ENCRYPTION_KEY"] = {key!r}
        from app.services.token_encryption import load_key  # noqa: F401
        load_key()
        """
    ).format(key=bad_key)

    env = os.environ.copy()
    env["TOKEN_ENCRYPTION_KEY"] = bad_key
    env["KORA_DATA_BACKEND"] = "mock"

    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert proc.returncode != 0, f"Expected non-zero exit, got {proc.returncode}.\n" f"stdout: {proc.stdout!r}\nstderr: {proc.stderr!r}"
    combined = proc.stdout + proc.stderr
    assert expected_fragment in combined, f"Expected {expected_fragment!r} in output, got: {combined!r}"
