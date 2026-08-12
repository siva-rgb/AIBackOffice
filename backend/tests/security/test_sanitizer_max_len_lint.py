"""Every sanitizer call must state its own length cap.

`sanitize_prompt_input` / `safe_sanitize` default `max_len=2000`. That suits a
name or a chat message and quietly destroys anything longer, which is exactly
what happened: `meeting_agent` sliced transcripts to 8000 chars and
`gmail_intel` assembled 8000 chars of email threads, then handed both to a
sanitizer that cut them to 2000. Three quarters of the input never reached the
model — and because meetings agree their decisions at the *end*, the discarded
part was the part worth reading. Fifteen call sites had inherited the default.

No functional test catches this: every call still returns a plausible string, so
the suite stays green while output quality silently degrades. An AST lint is the
only thing that can see it, in the same spirit as the tenant-isolation lints.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"

_SANITIZERS = {"sanitize_prompt_input", "safe_sanitize"}


def _sanitizer_calls() -> list[tuple[Path, ast.Call]]:
    found: list[tuple[Path, ast.Call]] = []
    for path in APP.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
            if name in _SANITIZERS:
                found.append((path, node))
    return found


def test_the_lint_finds_the_calls_it_is_meant_to_check():
    """A guard on the guard — a lint that matches nothing always passes."""
    calls = _sanitizer_calls()
    assert len(calls) >= 20, f"expected many sanitizer calls, found {len(calls)} — has the call shape changed?"


def test_every_call_states_its_max_len():
    offenders = []
    for path, call in _sanitizer_calls():
        # security.py itself defines and delegates; its internal call is the
        # implementation, not a caller choosing a cap.
        if path.name == "security.py":
            continue
        if not any(kw.arg == "max_len" for kw in call.keywords):
            offenders.append(f"{path.relative_to(APP.parent)}:{call.lineno}")
    assert not offenders, (
        "sanitizer calls relying on the 2000-char default: "
        f"{offenders}. Pass max_len explicitly — the default silently truncates, "
        "which is how three quarters of every transcript was lost."
    )
