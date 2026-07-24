"""Integration tests for the LLM service boundary (app/services/llm.py).

Validates the contract between Kora's agents and the OpenAI-compatible gateway:
- chat() and chat_messages() call the SDK with the right shape and return LLMResult/ToolTurn
- extract_json() handles fenced, plain, and malformed responses
- Retry logic fires on 429/5xx and stops on 4xx
- is_configured() gates real calls; unconfigured → no client is built
- No real network calls are made — the OpenAI SDK is monkeypatched at the
  completions.create boundary.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.llm import (
    LLMRetryableError,
    LLMResult,
    ToolTurn,
    _is_retryable,
    chat,
    chat_messages,
    extract_json,
    is_configured,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_completion(content: str, prompt_tokens: int = 10, completion_tokens: int = 20):
    usage = SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    msg = SimpleNamespace(content=content, tool_calls=None)
    choice = SimpleNamespace(message=msg)
    return SimpleNamespace(choices=[choice], usage=usage)


def _make_tool_completion(content: str | None, tool_calls: list):
    usage = SimpleNamespace(prompt_tokens=5, completion_tokens=5)
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=msg)
    return SimpleNamespace(choices=[choice], usage=usage)


# ── is_configured ─────────────────────────────────────────────────────────────

def test_is_configured_false_when_no_key(monkeypatch):
    monkeypatch.setattr("app.services.llm.settings.MODEL_API_KEY", "")
    monkeypatch.setattr("app.services.llm.settings.BASE_URL", "")
    assert is_configured() is False


def test_is_configured_true_when_both_set(monkeypatch):
    monkeypatch.setattr("app.services.llm.settings.MODEL_API_KEY", "key")
    monkeypatch.setattr("app.services.llm.settings.BASE_URL", "https://api.example.com")
    assert is_configured() is True


def test_is_configured_false_when_only_key(monkeypatch):
    monkeypatch.setattr("app.services.llm.settings.MODEL_API_KEY", "key")
    monkeypatch.setattr("app.services.llm.settings.BASE_URL", "")
    assert is_configured() is False


# ── chat() ────────────────────────────────────────────────────────────────────

def test_chat_returns_llm_result(monkeypatch):
    fake_resp = _make_completion("Hello world", prompt_tokens=8, completion_tokens=3)
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = fake_resp
    monkeypatch.setattr("app.services.llm._client", mock_client)

    result = chat("You are helpful.", "Say hello.")

    assert isinstance(result, LLMResult)
    assert result.text == "Hello world"
    assert result.input_tokens == 8
    assert result.output_tokens == 3
    assert result.latency_ms >= 0


def test_chat_passes_json_mode(monkeypatch):
    fake_resp = _make_completion('{"key": "val"}')
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = fake_resp
    monkeypatch.setattr("app.services.llm._client", mock_client)

    chat("sys", "user", json_mode=True)

    call_kwargs = mock_client.chat.completions.create.call_args[1]
    assert call_kwargs.get("response_format") == {"type": "json_object"}


def test_chat_sends_correct_messages(monkeypatch):
    fake_resp = _make_completion("ok")
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = fake_resp
    monkeypatch.setattr("app.services.llm._client", mock_client)

    chat("system-prompt", "user-prompt")

    messages = mock_client.chat.completions.create.call_args[1]["messages"]
    assert messages[0] == {"role": "system", "content": "system-prompt"}
    assert messages[1] == {"role": "user", "content": "user-prompt"}


def test_chat_handles_empty_content(monkeypatch):
    fake_resp = _make_completion(None)
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = fake_resp
    monkeypatch.setattr("app.services.llm._client", mock_client)

    result = chat("sys", "user")
    assert result.text == ""


# ── chat_messages() ───────────────────────────────────────────────────────────

def test_chat_messages_returns_tool_turn(monkeypatch):
    fake_resp = _make_tool_completion("I'll call a tool.", [])
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = fake_resp
    monkeypatch.setattr("app.services.llm._client", mock_client)

    result = chat_messages([{"role": "user", "content": "hello"}])

    assert isinstance(result, ToolTurn)
    assert result.content == "I'll call a tool."
    assert result.tool_calls == []


def test_chat_messages_passes_tools(monkeypatch):
    fake_resp = _make_tool_completion(None, [SimpleNamespace(id="tc1")])
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = fake_resp
    monkeypatch.setattr("app.services.llm._client", mock_client)

    tools = [{"type": "function", "function": {"name": "get_invoices"}}]
    result = chat_messages([{"role": "user", "content": "list invoices"}], tools=tools)

    call_kwargs = mock_client.chat.completions.create.call_args[1]
    assert call_kwargs["tools"] == tools
    assert call_kwargs["tool_choice"] == "auto"
    assert len(result.tool_calls) == 1


def test_chat_messages_no_tools_omits_tool_choice(monkeypatch):
    fake_resp = _make_tool_completion("plain response", [])
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = fake_resp
    monkeypatch.setattr("app.services.llm._client", mock_client)

    chat_messages([{"role": "user", "content": "hi"}])

    call_kwargs = mock_client.chat.completions.create.call_args[1]
    assert "tools" not in call_kwargs
    assert "tool_choice" not in call_kwargs


# ── extract_json() ────────────────────────────────────────────────────────────

def test_extract_json_plain_object():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_plain_array():
    assert extract_json('[1, 2, 3]') == [1, 2, 3]


def test_extract_json_fenced():
    assert extract_json("```json\n{\"x\": 2}\n```") == {"x": 2}


def test_extract_json_fenced_no_lang():
    assert extract_json("```\n{\"y\": 3}\n```") == {"y": 3}


def test_extract_json_with_leading_prose():
    text = "Here is the result:\n{\"status\": \"ok\"}"
    assert extract_json(text) == {"status": "ok"}


def test_extract_json_raises_on_no_json():
    with pytest.raises(ValueError, match="No valid JSON"):
        extract_json("This is just plain text with no JSON.")


# ── _is_retryable() ───────────────────────────────────────────────────────────

def test_retryable_on_429():
    exc = Exception()
    exc.status_code = 429
    assert _is_retryable(exc) is True


def test_retryable_on_503():
    exc = Exception()
    exc.status_code = 503
    assert _is_retryable(exc) is True


def test_not_retryable_on_400():
    exc = Exception()
    exc.status_code = 400
    assert _is_retryable(exc) is False


def test_not_retryable_on_401():
    exc = Exception()
    exc.status_code = 401
    assert _is_retryable(exc) is False


def test_retryable_on_llm_retryable_error():
    assert _is_retryable(LLMRetryableError("overloaded")) is True


def test_not_retryable_on_generic_exception():
    assert _is_retryable(ValueError("bad input")) is False
