"""snake_case → camelCase for API responses.

The Butler endpoints (meetings / calendar / gmail intel) return raw Supabase
rows and dicts, whose keys are snake_case. The frontend types + components are
camelCase (the app convention via CamelModel). `camelize()` bridges the two so
those responses actually render. Idempotent on already-camel keys (no `_` → no
change), so it's safe to apply broadly.
"""
from __future__ import annotations

from typing import Any


def _snake_to_camel(key: str) -> str:
    if "_" not in key:
        return key
    head, *rest = key.split("_")
    return head + "".join(word[:1].upper() + word[1:] for word in rest)


def camelize(obj: Any) -> Any:
    """Recursively convert dict keys from snake_case to camelCase (lists too)."""
    if isinstance(obj, dict):
        return {_snake_to_camel(k): camelize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [camelize(v) for v in obj]
    return obj
