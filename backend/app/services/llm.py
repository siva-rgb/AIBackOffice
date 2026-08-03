from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

from openai import AsyncOpenAI, OpenAI
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_random_exponential

from ..config import settings

# OpenAI-compatible LLM client (SKILL.md §6/§17). Points at the configured
# gateway (BASE_URL + MODEL_API_KEY) — e.g. the PwC GenAI shared service for
# development. To move to Google Vertex AI in production, implement a Gemini
# provider and switch KORA_AI_BACKEND; the agent code calls chat()/chat_json()
# and is provider-agnostic.

_client: OpenAI | None = None
_async_client: AsyncOpenAI | None = None


def is_configured() -> bool:
    return bool(settings.MODEL_API_KEY and settings.BASE_URL)


def _get_async_client() -> AsyncOpenAI:
    global _async_client
    if _async_client is None:
        _async_client = AsyncOpenAI(
            api_key=settings.MODEL_API_KEY,
            base_url=settings.BASE_URL.rstrip("/"),
            timeout=60.0,
            max_retries=0,
        )
    return _async_client


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=settings.MODEL_API_KEY,
            base_url=settings.BASE_URL.rstrip("/"),
            timeout=60.0,
            max_retries=0,  # we handle retries via tenacity below
        )
    return _client


async def achat(
    system: str,
    user: str,
    *,
    temperature: float = 0.2,
    max_tokens: int = 1500,
    json_mode: bool = False,
) -> LLMResult:
    """Async chat completion — use from async request handlers (M8.4)."""
    client = _get_async_client()
    start = time.time()
    kwargs: dict = {
        "model": settings.MODEL_NAME,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = await client.chat.completions.create(**kwargs)
    text = resp.choices[0].message.content or ""
    usage = resp.usage
    return LLMResult(
        text=text,
        input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        latency_ms=int((time.time() - start) * 1000),
        model=settings.MODEL_NAME,
    )


@dataclass
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    model: str


class LLMRetryableError(Exception):
    pass


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, LLMRetryableError):
        return True
    status = getattr(exc, "status_code", None)
    return status in (429, 500, 502, 503, 504)


@retry(
    retry=retry_if_exception(_is_retryable),
    wait=wait_random_exponential(multiplier=1, max=30),
    stop=stop_after_attempt(4),
    reraise=True,
)
def chat(
    system: str,
    user: str,
    *,
    temperature: float = 0.2,
    max_tokens: int = 1500,
    json_mode: bool = False,
) -> LLMResult:
    """Single chat completion with exponential backoff on 429/5xx."""
    client = _get_client()
    start = time.time()
    kwargs: dict = {
        "model": settings.MODEL_NAME,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(**kwargs)
    text = resp.choices[0].message.content or ""
    usage = resp.usage
    return LLMResult(
        text=text,
        input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        latency_ms=int((time.time() - start) * 1000),
        model=settings.MODEL_NAME,
    )


@dataclass
class ToolTurn:
    content: str | None
    tool_calls: list  # raw SDK tool_call objects (may be empty)
    input_tokens: int
    output_tokens: int
    model: str


def chat_messages(
    messages: list[dict],
    *,
    tools: list[dict] | None = None,
    temperature: float = 0.3,
    max_tokens: int = 900,
) -> ToolTurn:
    """One round of a tool-calling conversation. Caller owns the messages list
    and the loop (append the assistant turn + tool results, then call again).
    Used by the agentic manager. Raises on transport errors so the caller can
    fall back to plain chat."""
    client = _get_client()
    kwargs: dict = {
        "model": settings.MODEL_NAME,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    resp = client.chat.completions.create(**kwargs)
    msg = resp.choices[0].message
    usage = resp.usage
    return ToolTurn(
        content=msg.content,
        tool_calls=list(getattr(msg, "tool_calls", None) or []),
        input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        model=settings.MODEL_NAME,
    )


async def achat_messages(
    messages: list[dict],
    *,
    tools: list[dict] | None = None,
    temperature: float = 0.3,
    max_tokens: int = 900,
) -> ToolTurn:
    """Async tool-calling round (M8.4)."""
    client = _get_async_client()
    kwargs: dict = {
        "model": settings.MODEL_NAME,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"
    resp = await client.chat.completions.create(**kwargs)
    msg = resp.choices[0].message
    usage = resp.usage
    return ToolTurn(
        content=msg.content,
        tool_calls=list(getattr(msg, "tool_calls", None) or []),
        input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        model=settings.MODEL_NAME,
    )


def extract_json(text: str):
    """Best-effort JSON extraction from a model response (handles code fences
    and leading prose)."""
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # find first {...} or [...] block
    for opener, closer in (("[", "]"), ("{", "}")):
        start = cleaned.find(opener)
        end = cleaned.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("No valid JSON found in model response")
