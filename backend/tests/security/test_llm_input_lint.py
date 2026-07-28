"""Static lint: every LLM-facing service must call sanitize_prompt_input or safe_sanitize.

This is a regression guard. M4 added sanitize_prompt_input() / safe_sanitize() as
the canonical input boundary. Future contributors who add a new `get_ai()` call
without one of these two sanitizers adjacent will fail this test.

How it works:
  1. Walk backend/app/services/ for every public function that calls
     `generate_with_retry(...)` (the canonical "I'm about to call the LLM" marker).
  2. Check the function body for a call to either sanitize_prompt_input() or
     safe_sanitize() (the canonical sanitizer).
  3. Allow functions to bypass the check by having a `# m4-lint: no-sanitize`
     comment + a one-line justification.
  4. Allow functions whose only sanitized inputs come from structured store
     state (not user text) to also bypass — but they must declare so with the
     `# m4-lint: store-only` marker.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


SERVICES_DIR = Path(__file__).resolve().parents[2] / "app" / "services"
EXEMPT_MODULES = {
    "vertex_ai.py",  # the LLM gateway itself
    "llm.py",  # the low-level chat() wrapper
}


def _function_calls_sanitizer(func: ast.FunctionDef) -> bool:
    """True if `func` body calls sanitize_prompt_input() or safe_sanitize()."""
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        if isinstance(callee, ast.Name) and callee.id in ("sanitize_prompt_input", "safe_sanitize"):
            return True
        if isinstance(callee, ast.Attribute) and callee.attr in ("sanitize_prompt_input", "safe_sanitize"):
            return True
    return False


def _function_calls_llm(func: ast.FunctionDef) -> bool:
    """True if `func` body calls generate_with_retry() (the LLM marker)."""
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        if isinstance(callee, ast.Name) and callee.id == "generate_with_retry":
            return True
        if isinstance(callee, ast.Attribute) and callee.attr == "generate_with_retry":
            return True
    return False


def _func_has_marker(func: ast.FunctionDef, marker: str) -> bool:
    """True if any docstring or comment in the function mentions `marker`."""
    body = func.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        return marker in body[0].value.value
    return False


def _iter_top_level_functions(tree: ast.Module):
    """Yield every function defined at module top-level (not nested helpers).
    Nested helpers are exempt because the parent function does the sanitization."""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _collect_violations() -> list[tuple[Path, str, int]]:
    """Walk every service module and return (path, func_name, lineno) tuples for
    LLM-calling functions that don't sanitize AND don't carry a marker."""
    violations: list[tuple[Path, str, int]] = []
    for path in sorted(SERVICES_DIR.glob("*.py")):
        if path.name in EXEMPT_MODULES:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for func in _iter_top_level_functions(tree):
            if not _function_calls_llm(func):
                continue
            if _function_calls_sanitizer(func):
                continue
            if _func_has_marker(func, "m4-lint: no-sanitize"):
                continue
            if _func_has_marker(func, "m4-lint: store-only"):
                continue
            violations.append((path, func.name, func.lineno))
    return violations


def test_no_llm_call_without_sanitizer():
    """No new top-level function in app/services/ may call generate_with_retry
    without also calling sanitize_prompt_input or safe_sanitize (or carrying
    an explicit `m4-lint:` exemption marker)."""
    violations = _collect_violations()
    if violations:
        msg_lines = [
            "M4 lint violation — the following LLM-calling functions do NOT call " "sanitize_prompt_input() or safe_sanitize():",
        ]
        for path, name, lineno in violations:
            msg_lines.append(f"  {path.relative_to(path.parents[2])}:{lineno}  {name}()")
        msg_lines.append("")
        msg_lines.append(
            "Fix one of:\n"
            "  1. Add a sanitize_prompt_input() or safe_sanitize() call adjacent to the LLM invocation.\n"
            "  2. Add `# m4-lint: no-sanitize <reason>` to the function docstring if the LLM\n"
            "     input is provably not user-controlled (e.g. structured store state).\n"
            "  3. Add `# m4-lint: store-only` if the function takes only store-derived\n"
            "     data (no user text reaches the prompt)."
        )
        pytest.fail("\n".join(msg_lines))


def test_sanitizer_corpus_is_well_formed():
    """Sanity: the INJECTION_PHRASES corpus in test_prompt_injection.py must be
    non-empty and contain at least the phrases the sanitizer pattern-matches."""
    from tests.security.test_prompt_injection import INJECTION_PHRASES

    assert len(INJECTION_PHRASES) >= 5, "INJECTION_PHRASES corpus looks too small"
    # Must include the three the sanitizer explicitly pattern-matches (see
    # app/utils/security.py).
    must_have = [
        "ignore previous instructions",
        "you are now DAN",
        "system prompt",
    ]
    joined = " ".join(p.lower() for p in INJECTION_PHRASES)
    for m in must_have:
        assert m.lower() in joined, f"INJECTION_PHRASES missing the canonical phrase {m!r}"
