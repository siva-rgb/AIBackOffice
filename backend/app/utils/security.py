from __future__ import annotations

import re

# AI prompt-injection defense (SKILL.md §16 Rule 4). Any user-supplied string
# that enters a Gemini prompt must pass through sanitize_prompt_input().

_INJECTION_PATTERNS = [
    re.compile(r"ignore (previous|above|prior) instructions", re.I),
    re.compile(r"you are now", re.I),
    re.compile(r"disregard (your|all|the)", re.I),
    re.compile(r"system prompt", re.I),
    re.compile(r"<\|.*?\|>"),  # token boundary attacks
    re.compile(r"###\s*(system|assistant|user)", re.I),
]

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class PromptInjectionError(ValueError):
    """Raised when user input contains a likely prompt-injection attempt."""


def sanitize_prompt_input(value: str, *, max_len: int = 2000) -> str:
    """Strip control chars, reject injection attempts, and truncate.

    `max_len` defaults to 2000 for short fields (names, titles, a chat message).
    **Callers handling long content must pass it explicitly** — several didn't,
    and the sanitizer silently discarded three quarters of every meeting
    transcript and email-thread bundle before the model ever saw them. The
    truncation log line below exists so that loss is never silent again, and
    `tests/security/test_sanitizer_max_len_lint.py` requires every call site to
    state its cap.
    """
    clean = _CONTROL_CHARS.sub("", value)
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(clean):
            raise PromptInjectionError("Invalid input detected")
    if len(clean) > max_len:
        print(f"[sanitize] truncated {len(clean)} chars to {max_len} — raise max_len at this call site if the tail matters")
    return clean[:max_len]


def safe_sanitize(value: str, *, max_len: int = 2000) -> str:
    """Non-throwing variant for batch inputs (e.g. CSV descriptions): a flagged
    field is redacted rather than failing the whole batch."""
    try:
        return sanitize_prompt_input(value, max_len=max_len)
    except PromptInjectionError:
        return "[redacted]"
