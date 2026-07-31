"""M1 enforcement lint (app-wide) — destructive `.table()` writes must be scoped.

The store layer (`backends/`) has its own `raw_table` lint
(`test_raw_table_tenant_lint.py`). This one covers the *other* ~16 files —
services, routers, workers, seed — that reach Supabase via a raw
`db`/`sb`/`_db()` handle and call `.table(<name>).update(...)` / `.delete()`.

Because the runtime uses the service-role key (RLS bypassed), the application
`.eq(...)` filter is the ONLY tenant guard. This lint fails if any destructive
`.table()` chain outside `backends/` lacks a predicate tying the row to the
caller — either `.eq(<col>, user_id)` (service functions) or `.eq(<col>, user.id)`
(router handlers with a `user: User`). Reads (`.select()`) are out of scope here.

If a write is *intentionally* cross-tenant (admin/seed/migration), justify it by
putting `# tenant-lint: allow` on the line with the `.table(` call.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"
ALLOW_MARKER = "tenant-lint: allow"


def _chain_methods(call: ast.Call) -> list[tuple[str, list[ast.expr]]]:
    methods: list[tuple[str, list[ast.expr]]] = []
    node: ast.AST = call
    while isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        methods.append((node.func.attr, node.args))
        node = node.func.value
    return methods


def _is_caller_ref(node: ast.expr) -> bool:
    """True for `user_id` (Name) or `user.id` (Attribute) — the caller's id."""
    if isinstance(node, ast.Name):
        return node.id == "user_id"
    if isinstance(node, ast.Attribute) and node.attr == "id":
        return isinstance(node.value, ast.Name) and node.value.id == "user"
    return False


def _has_tenant_eq(methods: list[tuple[str, list[ast.expr]]]) -> bool:
    for name, args in methods:
        if name != "eq" or len(args) < 2:
            continue
        col, val = args[0], args[1]
        # .eq(<col>, user_id/user.id) — value is the caller
        if _is_caller_ref(val):
            return True
        # .eq("user_id", <anything>) — column is the tenant key
        if isinstance(col, ast.Constant) and col.value == "user_id":
            return True
    return False


def _collect_violations() -> list[str]:
    violations: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        if path.parts[-2] == "backends":
            continue  # covered by the raw_table lint
        src = path.read_text(encoding="utf-8")
        lines = src.splitlines()
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue

        inner: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Call):
                    inner.add(id(node.func.value))

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or id(node) in inner:
                continue
            methods = _chain_methods(node)
            names = {m for m, _ in methods}
            if "table" not in names or not (names & {"update", "delete"}):
                continue
            if _has_tenant_eq(methods):
                continue
            # allow explicit, justified cross-tenant writes
            line_txt = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
            if ALLOW_MARKER in line_txt:
                continue
            rel = path.relative_to(APP.parents[0])
            violations.append(f"{rel}:{node.lineno}")
    return violations


def test_no_unscoped_table_destructive_writes_outside_store():
    violations = _collect_violations()
    assert not violations, (
        "Unscoped .table() delete/update outside backends/ (missing an "
        ".eq(..., user_id) / .eq(..., user.id) tenant predicate) at: "
        f"{violations}. Add the tenant filter, or annotate a deliberate "
        f"cross-tenant write with `# {ALLOW_MARKER}`."
    )


def test_lint_detects_and_allows():
    good = "def f(user_id):\n    db.table('clients').update({}).eq('id', c).eq('user_id', user_id).execute()\n"
    bad = "def f(user_id):\n    db.table('clients').update({}).eq('id', c).execute()\n"
    allowed = (
        "def f():\n    db.table('clients').update({}).execute()  # tenant-lint: allow\n"
    )

    def flagged(src: str) -> bool:
        tree = ast.parse(src)
        lines = src.splitlines()
        inner = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
                if isinstance(n.func.value, ast.Call):
                    inner.add(id(n.func.value))
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call) or id(n) in inner:
                continue
            m = _chain_methods(n)
            names = {x for x, _ in m}
            if "table" in names and (names & {"update", "delete"}):
                if _has_tenant_eq(m):
                    return False
                if ALLOW_MARKER in lines[n.lineno - 1]:
                    return False
                return True
        return False

    assert flagged(bad)
    assert not flagged(good)
    assert not flagged(allowed)
