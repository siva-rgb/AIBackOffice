"""Every Drive API call must opt into shared drives.

Drive v3 returns My Drive only unless `supportsAllDrives` (and, for list calls,
`includeItemsFromAllDrives`) is set. Without them a Google Workspace user whose
watched folder or Meet transcripts live in a shared drive gets an empty scan and
no error explaining it — the API call succeeds, it just matches nothing. That is
the same silent-nothing failure mode as D-017 and it is invisible to every
functional test, because the tests never reach Google.

An AST lint rather than a runtime test for the same reason as
`test_manual_auth_call_lint.py`: the defect lives in the call sites, is spread
across modules, and a new call added later would reintroduce it silently.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"

# files.export accepts neither flag and needs neither — shared-drive files
# export fine without it.
_LIST_METHODS = {"list"}
_GET_METHODS = {"get", "get_media"}


def _drive_calls() -> list[tuple[Path, ast.Call]]:
    """Every `<something>.files().<method>(...)` call under app/."""
    found: list[tuple[Path, ast.Call]] = []
    for path in APP.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            receiver = node.func.value
            # Matches the `service.files().list(...)` shape specifically, so a
            # PostgREST `.select(...).execute()` chain is never picked up.
            if isinstance(receiver, ast.Call) and isinstance(receiver.func, ast.Attribute) and receiver.func.attr == "files":
                found.append((path, node))
    return found


def _keyword_names(call: ast.Call) -> set[str]:
    """Explicit keywords plus the names of any `**CONSTANT` spreads."""
    names = {kw.arg for kw in call.keywords if kw.arg}
    for kw in call.keywords:
        if kw.arg is None and isinstance(kw.value, ast.Name):
            names.add(kw.value.id)
    return names


def test_the_lint_finds_the_drive_calls_it_is_meant_to_check():
    """A guard on the guard: a silent zero-match lint would always pass."""
    calls = _drive_calls()
    assert len(calls) >= 5, f"expected several Drive calls, found {len(calls)} — has the call shape changed?"


def test_list_calls_include_shared_drive_items():
    offenders = []
    for path, call in _drive_calls():
        if call.func.attr not in _LIST_METHODS:
            continue
        names = _keyword_names(call)
        ok = "ALL_DRIVES_LIST" in names or {"supportsAllDrives", "includeItemsFromAllDrives"} <= names
        if not ok:
            offenders.append(f"{path.name}:{call.lineno}")
    assert not offenders, (
        "Drive files().list() calls missing shared-drive support "
        f"(pass **ALL_DRIVES_LIST): {offenders}. Without it, shared-drive folders "
        "and transcripts are invisible and no error is raised."
    )


def test_get_calls_support_shared_drives():
    offenders = []
    for path, call in _drive_calls():
        if call.func.attr not in _GET_METHODS:
            continue
        names = _keyword_names(call)
        if not ("ALL_DRIVES_GET" in names or "supportsAllDrives" in names):
            offenders.append(f"{path.name}:{call.lineno}")
    assert not offenders, f"Drive files().get/get_media calls missing supportsAllDrives (pass **ALL_DRIVES_GET): {offenders}"


def test_the_two_constants_carry_the_right_flags():
    """includeItemsFromAllDrives is a list-only parameter — passing it to
    files.get raises TypeError, which is why there are two constants."""
    from app.services.drive_intel import ALL_DRIVES_GET, ALL_DRIVES_LIST

    assert ALL_DRIVES_LIST == {"supportsAllDrives": True, "includeItemsFromAllDrives": True}
    assert ALL_DRIVES_GET == {"supportsAllDrives": True}
    assert "includeItemsFromAllDrives" not in ALL_DRIVES_GET
