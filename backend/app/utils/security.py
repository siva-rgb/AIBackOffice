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
    """Strip control chars, reject injection attempts, and truncate."""
    clean = _CONTROL_CHARS.sub("", value)
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(clean):
            raise PromptInjectionError("Invalid input detected")
    return clean[:max_len]


def safe_sanitize(value: str, *, max_len: int = 2000) -> str:
    """Non-throwing variant for batch inputs (e.g. CSV descriptions): a flagged
    field is redacted rather than failing the whole batch."""
    try:
        return sanitize_prompt_input(value, max_len=max_len)
    except PromptInjectionError:
        return "[redacted]"
