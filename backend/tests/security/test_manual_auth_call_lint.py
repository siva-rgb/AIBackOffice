"""`get_current_user` must always be called with (request, authorization).

Regression guard for the staging/local UAT finding. Nine routes support BOTH a
scheduler path (x-cron-secret) and a user path, so they cannot declare
`Depends(get_current_user)` unconditionally — that would force auth on the cron
call. They invoke the dependency by hand instead, and every one of them did it
with a single argument:

    user = await get_current_user(authorization)     # WRONG

`get_current_user(request, authorization)` takes the Request first, so the header
string landed in `request` and `authorization` fell back to the *unresolved*
`Header(default=None)` sentinel — FastAPI only resolves those when it builds the
dependency itself. Result: `AttributeError: 'Header' object has no attribute
'lower'`, a 500 on every "run now" button in the product.

It hid because `_bearer()` is only reached when KORA_DATA_BACKEND == "supabase";
local dev and the whole test suite run on the mock store, which returns the demo
user before that line. So no functional test could catch it — hence a lint.

Written as an AST check, matching the existing tenant-isolation lints in this
directory: it holds for all current call sites and any added later.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

ROUTERS = pathlib.Path(__file__).resolve().parents[2] / "app" / "routers"


def _manual_calls(tree: ast.AST):
    """Yield every direct call to get_current_user(...) in the module."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
            if name == "get_current_user":
                yield node


@pytest.mark.parametrize("path", sorted(ROUTERS.glob("*.py")), ids=lambda p: p.name)
def test_manual_get_current_user_calls_pass_request_first(path: pathlib.Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))

    for call in _manual_calls(tree):
        # Depends(get_current_user) is a reference, not a call — only real calls land here.
        assert len(call.args) >= 2, (
            f"{path.name}:{call.lineno} calls get_current_user() with "
            f"{len(call.args)} positional arg(s). It must be "
            f"get_current_user(request, authorization) — passing only the header "
            f"puts it in the `request` slot and leaves `authorization` as an "
            f"unresolved Header sentinel, which 500s at runtime under "
            f"KORA_DATA_BACKEND=supabase."
        )

        first = call.args[0]
        assert isinstance(first, ast.Name) and first.id == "request", f"{path.name}:{call.lineno} passes {ast.dump(first)[:60]} as the first " f"argument; it must be the FastAPI `request` object."


def test_every_route_calling_it_manually_declares_a_request_param():
    """A `request: Request` parameter must exist, or `request` is just a NameError."""
    offenders = []
    for path in sorted(ROUTERS.glob("*.py")):
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            if not any(_manual_calls(fn)):
                continue
            params = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
            if "request" not in params:
                offenders.append(f"{path.name}:{fn.lineno} {fn.name}()")

    assert not offenders, "these functions call get_current_user(request, ...) without declaring a " f"`request: Request` parameter: {offenders}"


def test_the_lint_has_something_to_check():
    """Guard against the lint silently passing because it found no call sites."""
    total = sum(len(list(_manual_calls(ast.parse(p.read_text(encoding="utf-8"))))) for p in ROUTERS.glob("*.py"))
    assert total >= 9, f"expected the dual cron/user routes to still call get_current_user " f"manually, found {total} call site(s) — if they were migrated to " f"Depends(), delete this lint."
