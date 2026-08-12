"""Which transport the agents talk to: Vertex AI, or the OpenAI-compatible gateway.

Two modules implement the same four functions (`chat`, `achat`, `chat_messages`,
`achat_messages`) and return the same dataclasses:

  * `llm.py`        — OpenAI Chat Completions against `BASE_URL`
  * `vertex_llm.py` — Google Vertex AI (Gemini), authenticated by ADC

Everything that needs a model goes through `active()` so no caller has to branch
on the provider. Selection follows `KORA_AI_BACKEND`:

    vertex  → Vertex (the mock provider takes over if it isn't configured)
    openai  → the gateway
    mock    → neither; `vertex_ai.get_ai()` returns MockGemini
    auto    → Vertex if configured, else the gateway, else mock

Embeddings deliberately do **not** route through here — `embeddings.py` stays on
the gateway. Vectors from different models aren't comparable, so moving them
would require re-embedding every stored row before semantic recall worked again.
"""

from __future__ import annotations

from ..config import settings
from . import llm, vertex_llm


def using_vertex() -> bool:
    backend = settings.KORA_AI_BACKEND
    if backend == "vertex":
        return True
    if backend in ("openai", "mock"):
        return False
    return vertex_llm.is_configured()  # auto: Vertex wins when it's available


def active():
    """The transport module to call. Never returns the mock — provider choice
    between real and mock stays in `vertex_ai.get_ai()`."""
    return vertex_llm if using_vertex() else llm


def is_configured() -> bool:
    """True when the selected transport can actually serve a request."""
    return vertex_llm.is_configured() if using_vertex() else llm.is_configured()


def active_name() -> str:
    """Model identifier for logs, the health endpoint and cost attribution."""
    return vertex_llm.model_name() if using_vertex() else settings.MODEL_NAME
