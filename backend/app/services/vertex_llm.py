"""Google Vertex AI transport — the Gemini counterpart to `llm.py`.

`llm.py` speaks OpenAI's Chat Completions shape against a gateway. This module
exposes the *same four functions* returning the *same dataclasses*, so callers
go through `ai_backend.active()` and never branch on the provider themselves.

Auth is Application Default Credentials: on Cloud Run that is the runtime
service account (needs `roles/aiplatform.user`), locally it is
`gcloud auth application-default login`. There is no API key to store or rotate,
which is the main operational win over the gateway.

Two shape differences from OpenAI that this module hides:

  * **JSON mode** is `response_mime_type="application/json"` on the generation
    config rather than a `response_format` argument.
  * **Tool calling** has no call ids and pairs a result to its call by function
    *name*; OpenAI pairs by id. `chat_messages` synthesises stable ids on the way
    out and maps them back to names on the way in, so the caller's message list
    stays in OpenAI shape and `supervisor.py`'s loop is untouched.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

from tenacity import retry, retry_if_exception, stop_after_attempt, wait_random_exponential

from ..config import settings
from .llm import LLMResult, ToolTurn

# Schema keys Gemini's FunctionDeclaration accepts. OpenAI tool schemas often
# carry extras ($schema, additionalProperties) that Vertex rejects outright, so
# every declaration is filtered through `_clean_schema` before it is sent.
_SCHEMA_KEYS = {"type", "properties", "required", "items", "description", "enum", "nullable", "format"}

_DEFAULT_MODEL = "gemini-2.5-flash"

# Gemini 2.5 charges thinking tokens against the output budget; callers pass
# budgets tuned for a non-thinking gateway. See `_generate`.
_TOKEN_HEADROOM = 3
_MAX_OUTPUT_CEILING = 8192

_initialised = False
_configured: bool | None = None
_project_cache: str | None = None


# ── configuration ───────────────────────────────────────────────────────────


def _project() -> str:
    """Explicit project wins; otherwise whatever ADC resolves to."""
    global _project_cache
    if _project_cache is not None:
        return _project_cache
    if settings.GOOGLE_CLOUD_PROJECT_ID:
        _project_cache = settings.GOOGLE_CLOUD_PROJECT_ID
        return _project_cache
    try:
        import google.auth

        _, project = google.auth.default()
        _project_cache = project or ""
    except Exception:
        _project_cache = ""
    return _project_cache


def is_configured() -> bool:
    """True when a project *and* usable credentials are both present.

    Both halves matter: a project id with no ADC would let `auto` select Vertex
    on a developer machine and then fail every call at request time.
    """
    global _configured
    if _configured is None:
        try:
            import google.auth

            google.auth.default()
            _configured = bool(_project())
        except Exception:
            _configured = False
    return _configured


def model_name() -> str:
    """The Gemini model to call.

    Falls back to the default when `MODEL_NAME` is still pointing at a gateway
    model (e.g. `azure.gpt-4.1` left over from the previous backend) — a stale
    value would otherwise 404 every single agent call.
    """
    name = (settings.MODEL_NAME or "").strip()
    return name if name.startswith("gemini") else _DEFAULT_MODEL


def _init():
    global _initialised
    if _initialised:
        return
    import vertexai

    vertexai.init(project=_project(), location=settings.GOOGLE_CLOUD_LOCATION or "us-central1")
    _initialised = True


# ── retries ─────────────────────────────────────────────────────────────────


def _is_retryable(exc: BaseException) -> bool:
    try:
        from google.api_core import exceptions as gexc
    except Exception:
        return False
    return isinstance(exc, (gexc.ResourceExhausted, gexc.ServiceUnavailable, gexc.InternalServerError, gexc.DeadlineExceeded, gexc.TooManyRequests))


_retry = retry(
    retry=retry_if_exception(_is_retryable),
    wait=wait_random_exponential(multiplier=1, max=30),
    stop=stop_after_attempt(4),
    reraise=True,
)


# ── response helpers ────────────────────────────────────────────────────────


def _text_of(response) -> str:
    """Join the text parts of the first candidate.

    `response.text` raises when the candidate holds no text part — which happens
    on a pure function-call turn, on a safety block, and when the output budget
    is exhausted. Every one of those is a normal outcome here, so read the parts
    directly instead.
    """
    try:
        candidates = list(getattr(response, "candidates", None) or [])
        if not candidates:
            return ""
        parts = list(getattr(candidates[0].content, "parts", None) or [])
        return "".join(getattr(p, "text", "") or "" for p in parts)
    except Exception:
        return ""


def _usage(response) -> tuple[int, int]:
    """(input, output) tokens. Gemini 2.5 bills thinking tokens as output, so
    they are counted here too — omitting them would understate spend."""
    u = getattr(response, "usage_metadata", None)
    if not u:
        return 0, 0
    out = int(getattr(u, "candidates_token_count", 0) or 0) + int(getattr(u, "thoughts_token_count", 0) or 0)
    return int(getattr(u, "prompt_token_count", 0) or 0), out


def _gen_config(temperature: float, max_tokens: int, json_mode: bool):
    from vertexai.generative_models import GenerationConfig

    kwargs = {"temperature": temperature, "max_output_tokens": max_tokens}
    if json_mode:
        kwargs["response_mime_type"] = "application/json"
    return GenerationConfig(**kwargs)


def _truncated(response) -> bool:
    """True when generation stopped because the output budget ran out.

    finish_reason 2 is MAX_TOKENS. The pinned SDK's enum isn't always importable,
    so match on the name when present and fall back to the wire value.
    """
    try:
        reason = response.candidates[0].finish_reason
    except Exception:
        return False
    name = getattr(reason, "name", None)
    return name == "MAX_TOKENS" if name else int(reason or 0) == 2


def _generate(model, contents, temperature: float, max_tokens: int, json_mode: bool):
    """Generate, retrying once with a larger budget if the answer was cut off.

    Gemini 2.5 bills *thinking* against `max_output_tokens`, so a budget that
    covered the answer on the OpenAI gateway can be consumed entirely by
    reasoning here, returning an empty or half-written response. Callers pass
    budgets tuned for the gateway, so the transport applies headroom rather than
    making 15 call sites carry a provider quirk.

    `thinking_config` — the direct way to bound this — is not available in
    google-cloud-aiplatform 1.74, which predates Gemini 2.5. Upgrading to the
    google-genai SDK would allow setting a thinking budget explicitly and make
    this retry unnecessary.
    """
    budget = min(max_tokens * _TOKEN_HEADROOM, _MAX_OUTPUT_CEILING)
    response = model.generate_content(contents, generation_config=_gen_config(temperature, budget, json_mode))
    if _truncated(response) and budget < _MAX_OUTPUT_CEILING:
        response = model.generate_content(contents, generation_config=_gen_config(temperature, _MAX_OUTPUT_CEILING, json_mode))
    return response


async def _generate_async(model, contents, temperature: float, max_tokens: int, json_mode: bool):
    budget = min(max_tokens * _TOKEN_HEADROOM, _MAX_OUTPUT_CEILING)
    response = await model.generate_content_async(contents, generation_config=_gen_config(temperature, budget, json_mode))
    if _truncated(response) and budget < _MAX_OUTPUT_CEILING:
        response = await model.generate_content_async(contents, generation_config=_gen_config(temperature, _MAX_OUTPUT_CEILING, json_mode))
    return response


def _model(system: str | None = None, tools=None):
    from vertexai.generative_models import GenerativeModel

    _init()
    return GenerativeModel(model_name(), system_instruction=system or None, tools=tools or None)


# ── plain chat ──────────────────────────────────────────────────────────────


@_retry
def chat(
    system: str,
    user: str,
    *,
    temperature: float = 0.2,
    max_tokens: int = 1500,
    json_mode: bool = False,
) -> LLMResult:
    """Single generation. Mirrors `llm.chat`."""
    start = time.time()
    response = _generate(_model(system), user, temperature, max_tokens, json_mode)
    in_tok, out_tok = _usage(response)
    return LLMResult(
        text=_text_of(response),
        input_tokens=in_tok,
        output_tokens=out_tok,
        latency_ms=int((time.time() - start) * 1000),
        model=model_name(),
    )


async def achat(
    system: str,
    user: str,
    *,
    temperature: float = 0.2,
    max_tokens: int = 1500,
    json_mode: bool = False,
) -> LLMResult:
    """Async generation. Mirrors `llm.achat`."""
    start = time.time()
    response = await _generate_async(_model(system), user, temperature, max_tokens, json_mode)
    in_tok, out_tok = _usage(response)
    return LLMResult(
        text=_text_of(response),
        input_tokens=in_tok,
        output_tokens=out_tok,
        latency_ms=int((time.time() - start) * 1000),
        model=model_name(),
    )


# ── tool calling ────────────────────────────────────────────────────────────


@dataclass
class _Fn:
    name: str
    arguments: str  # JSON string, matching the OpenAI SDK's shape


@dataclass
class _ToolCall:
    id: str
    function: _Fn
    type: str = "function"


def _clean_schema(node):
    """Recursively drop schema keys Vertex's FunctionDeclaration rejects."""
    if not isinstance(node, dict):
        return node
    out = {}
    for key, value in node.items():
        if key not in _SCHEMA_KEYS:
            continue
        if key == "properties" and isinstance(value, dict):
            out[key] = {k: _clean_schema(v) for k, v in value.items()}
        elif key == "items":
            out[key] = _clean_schema(value)
        else:
            out[key] = value
    if out.get("type") == "object" and "properties" not in out:
        out["properties"] = {}
    return out


def _to_tools(tools: list[dict] | None):
    """OpenAI tool definitions → a single Vertex Tool."""
    if not tools:
        return None
    from vertexai.generative_models import FunctionDeclaration, Tool

    declarations = []
    for entry in tools:
        fn = entry.get("function", entry) or {}
        name = fn.get("name")
        if not name:
            continue
        declarations.append(
            FunctionDeclaration(
                name=name,
                description=fn.get("description", ""),
                parameters=_clean_schema(fn.get("parameters") or {"type": "object", "properties": {}}),
            )
        )
    return [Tool(function_declarations=declarations)] if declarations else None


def _to_history(messages: list[dict]) -> tuple[str | None, list]:
    """OpenAI message list → (system_instruction, Vertex Content list).

    The caller keeps its history in OpenAI shape across turns, so this has to
    understand assistant turns carrying `tool_calls` and `tool` result turns.
    Gemini pairs a result to its call by function *name*, so the id→name map
    built from the assistant turns is what makes the round trip work.
    """
    from vertexai.generative_models import Content, Part

    system_parts: list[str] = []
    history: list = []
    call_names: dict[str, str] = {}

    for message in messages:
        role = message.get("role")
        content = message.get("content") or ""

        if role == "system":
            if content:
                system_parts.append(content)
            continue

        if role == "tool":
            name = call_names.get(message.get("tool_call_id") or "", "tool")
            try:
                payload = json.loads(content) if content else {}
            except Exception:
                payload = {"result": content}
            if not isinstance(payload, dict):
                payload = {"result": payload}
            history.append(Content(role="user", parts=[Part.from_function_response(name=name, response={"content": payload})]))
            continue

        if role == "assistant":
            parts = []
            if content:
                parts.append(Part.from_text(content))
            for call in message.get("tool_calls") or []:
                fn = call.get("function") or {}
                call_names[call.get("id") or ""] = fn.get("name") or ""
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except Exception:
                    args = {}
                parts.append(Part.from_dict({"function_call": {"name": fn.get("name"), "args": args}}))
            if parts:
                history.append(Content(role="model", parts=parts))
            continue

        if content:
            history.append(Content(role="user", parts=[Part.from_text(content)]))

    return ("\n\n".join(system_parts) or None), history


def _to_turn(response) -> ToolTurn:
    """Vertex response → the OpenAI-shaped ToolTurn the caller expects."""
    calls: list[_ToolCall] = []
    try:
        candidates = list(getattr(response, "candidates", None) or [])
        parts = list(getattr(candidates[0].content, "parts", None) or []) if candidates else []
    except Exception:
        parts = []

    for index, part in enumerate(parts):
        function_call = getattr(part, "function_call", None)
        name = getattr(function_call, "name", "") if function_call else ""
        if not name:
            continue
        try:
            args = dict(function_call.args or {})
        except Exception:
            args = {}
        # Gemini issues no call ids; synthesise one that is stable within the
        # turn so the caller can correlate its own tool-result messages.
        calls.append(_ToolCall(id=f"call_{index}_{name}", function=_Fn(name=name, arguments=json.dumps(args, default=str))))

    in_tok, out_tok = _usage(response)
    text = _text_of(response)
    return ToolTurn(
        content=text or None,
        tool_calls=calls,
        input_tokens=in_tok,
        output_tokens=out_tok,
        model=model_name(),
    )


@_retry
def chat_messages(
    messages: list[dict],
    *,
    tools: list[dict] | None = None,
    temperature: float = 0.3,
    max_tokens: int = 900,
) -> ToolTurn:
    """One tool-calling round. Mirrors `llm.chat_messages`."""
    system, history = _to_history(messages)
    vertex_tools = _to_tools(tools)
    response = _generate(_model(system, vertex_tools), history, temperature, max_tokens, False)
    return _to_turn(response)


async def achat_messages(
    messages: list[dict],
    *,
    tools: list[dict] | None = None,
    temperature: float = 0.3,
    max_tokens: int = 900,
) -> ToolTurn:
    """Async tool-calling round. Mirrors `llm.achat_messages`."""
    system, history = _to_history(messages)
    vertex_tools = _to_tools(tools)
    response = await _generate_async(_model(system, vertex_tools), history, temperature, max_tokens, False)
    return _to_turn(response)
