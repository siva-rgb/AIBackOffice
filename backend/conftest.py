"""Test harness bootstrap.

**This module's import-time side effects are load-bearing — do not move them into
a fixture.**

`app/store.py` picks its data backend *at import time* from
`settings.KORA_DATA_BACKEND`, and `app/config.py` builds `Settings()` at import
by reading the developer's real `.env`. On this machine that `.env` points at a
live Supabase project, a live LLM gateway and a live Notion workspace.

pytest imports `conftest.py` before any test module, and pydantic-settings ranks
real environment variables above the dotenv file — so mutating `os.environ` here,
at module scope, is what keeps the suite hermetic. Without it, running the tests
would read and write production data.
"""

from __future__ import annotations

import os
import uuid

# ── Hermetic environment (must run before any `app.*` import) ───────────────
# In-memory store: no Supabase connection is even constructed.
os.environ["KORA_DATA_BACKEND"] = "mock"

# Blank the outbound credentials. `llm.is_configured()` is
# `bool(MODEL_API_KEY and BASE_URL)`, so blanking these makes
# `embeddings.is_enabled()` False and every embed call return None — the suite
# exercises the lexical-fallback path by default and cannot reach the network.
os.environ["MODEL_API_KEY"] = ""
os.environ["BASE_URL"] = ""

# Blanking keys is no longer sufficient on its own: the Vertex transport
# authenticates with Application Default Credentials, not an env var, so on any
# machine that has run `gcloud auth application-default login` (and on every
# Cloud Build worker) `KORA_AI_BACKEND=auto` would resolve to Vertex and the
# suite would issue *live, billable* model calls. Pin the mock provider.
# Tests that exercise the Vertex transport patch it explicitly instead.
os.environ["KORA_AI_BACKEND"] = "mock"
os.environ["GOOGLE_CLOUD_PROJECT_ID"] = ""

# Notion: blank both the internal key and the OAuth pair so tests control the
# auth mode explicitly via monkeypatch instead of inheriting the developer's.
os.environ["NOTION_API_KEY"] = ""
os.environ["NOTION_OAUTH_CLIENT_ID"] = ""
os.environ["NOTION_OAUTH_CLIENT_SECRET"] = ""
os.environ["NOTION_PARENT_PAGE_ID"] = ""

# Supabase: blank so an accidental supabase-mode import fails loudly rather than
# quietly connecting somewhere real.
os.environ["SUPABASE_URL"] = ""
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = ""

# Token encryption (M3): pin a known Fernet key so the suite remains hermetic
# and the module-level `load_key()` succeeds. Tests that exercise the
# missing-key / malformed-key failure path set TOKEN_ENCRYPTION_KEY="" or a
# bad value locally (via monkeypatch) and import a fresh module instance.
# This fixed key is deterministic across runs — never use it outside tests.
os.environ["TOKEN_ENCRYPTION_KEY"] = "7Xa5l8OaKCyJqfqJdSG1fRXPtga_ofNl8v2EbfsAIWM="

import pytest  # noqa: E402  — must follow the env setup above


@pytest.fixture
def user_id() -> str:
    """A unique user id per test.

    `memory_store` holds state in module-level dicts that persist for the whole
    session. Giving each test its own user id isolates them without reaching
    into private module state to reset it.
    """
    return str(uuid.uuid4())


@pytest.fixture
def settings():
    """The live settings object, for tests that need to flip a flag.

    Use with `monkeypatch.setattr(settings, "NOTION_OAUTH_CLIENT_ID", "x")` —
    the instance is built once at import, so patching the attribute is what
    takes effect, not re-reading the environment.
    """
    from app.config import settings as _settings

    return _settings


@pytest.fixture
def no_embeddings(monkeypatch):
    """Force the lexical-only recall path, regardless of ambient config."""
    from app.services import embeddings

    monkeypatch.setattr(embeddings, "is_enabled", lambda: False)
    monkeypatch.setattr(embeddings, "embed", lambda _text: None)
    return embeddings


@pytest.fixture
def fake_embeddings(monkeypatch):
    """Deterministic offline embeddings so the *semantic* path is testable.

    Returns a `register(text, vector)` callable. Unregistered text embeds to
    None, which is exactly how the real provider behaves on failure.
    """
    from app.services import embeddings

    table: dict[str, list[float]] = {}

    def _embed(text: str):
        return table.get((text or "").strip())

    monkeypatch.setattr(embeddings, "is_enabled", lambda: True)
    monkeypatch.setattr(embeddings, "embed", _embed)

    def register(text: str, vector: list[float]) -> None:
        table[text.strip()] = vector

    return register
