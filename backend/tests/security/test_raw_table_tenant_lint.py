"""M1 enforcement lint — every destructive `raw_table()` write must be user-scoped.

`repo(user_id).raw_table(...)` is the escape hatch: unlike the wrapper's own
`.select()/.update()/.delete()`, it does NOT auto-inject `.eq("user_id", ...)`.
The M1 refactor dropped that filter on 11 functions, creating cross-tenant
UPDATE/DELETE holes under the service-role key (RLS bypassed). Those are fixed,
but a static guard is what stops a 12th regression from ever landing.

Rule enforced here: for every method chain in `supabase_store.py` that contains
BOTH a `.raw_table(...)` call AND a `.update(...)` or `.delete()` call, the chain
must also contain an `.eq(<col>, user_id)` predicate whose value argument is the
local `user_id` parameter. (`.eq("id", user_id)` on the `users` table counts —
the tenant key there is the id itself.)

This is an AST lint, not a runtime test — it reads the source and parses it.
"""

from __future__ import annotations

import ast
from pathlib import Path

STORE = Path(__file__).resolve().parents[2] / "app" / "backends" / "supabase_store.py"


def _chain_methods(call: ast.Call) -> list[tuple[str, list[ast.expr]]]:
    """Unwind a fluent call chain into [(method_name, arg_nodes), ...]."""
    methods: list[tuple[str, list[ast.expr]]] = []
    node: ast.AST = call
    while isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        methods.append((node.func.attr, node.args))
        node = node.func.value
    return methods


def _has_user_id_eq(methods: list[tuple[str, list[ast.expr]]]) -> bool:
    """True if some .eq(<col>, user_id) is present (value arg is the Name user_id)."""
    for name, args in methods:
        if name == "eq" and len(args) >= 2:
            val = args[1]
            if isinstance(val, ast.Name) and val.id == "user_id":
                return True
    return False


def _collect_violations() -> list[int]:
    tree = ast.parse(STORE.read_text(encoding="utf-8"))

    # A call is "inner" if it is the receiver (.func.value) of another call —
    # so terminal calls (not inner) are the tops of maximal chains.
    inner: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Call):
                inner.add(id(node.func.value))

    violations: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or id(node) in inner:
            continue
        methods = _chain_methods(node)
        names = {m for m, _ in methods}
        if "raw_table" not in names:
            continue
        if not (names & {"update", "delete"}):
            continue
        if not _has_user_id_eq(methods):
            violations.append(node.lineno)
    return violations


def test_no_unscoped_raw_table_destructive_writes():
    violations = _collect_violations()
    assert not violations, (
        "Unscoped raw_table() delete/update in supabase_store.py (missing "
        f".eq(<col>, user_id)) at line(s): {violations}. This is a cross-tenant "
        "data-loss hole — add .eq('user_id', user_id) to the chain."
    )


def test_lint_actually_detects_a_violation():
    """Sanity: the lint flags an unscoped destructive raw_table chain."""
    bad = (
        "def f(user_id):\n"
        "    repo(user_id).raw_table('t').delete().eq('client_id', x).execute()\n"
    )
    tree = ast.parse(bad)
    inner = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Call):
                inner.add(id(node.func.value))
    flagged = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or id(node) in inner:
            continue
        methods = _chain_methods(node)
        names = {m for m, _ in methods}
        if "raw_table" in names and (names & {"update", "delete"}):
            flagged = not _has_user_id_eq(methods)
    assert flagged, "lint failed to detect an unscoped raw_table delete"
