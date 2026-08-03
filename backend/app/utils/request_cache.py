"""Per-request memoization for expensive dashboard aggregations (M8.4)."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Callable, TypeVar

T = TypeVar("T")

_cache_var: ContextVar[dict[str, object] | None] = ContextVar("request_cache", default=None)


def begin_request_cache() -> None:
    _cache_var.set({})


def end_request_cache() -> None:
    _cache_var.set(None)


def request_cached(fn: Callable[..., T]) -> Callable[..., T]:
    """Memoize `fn` for the lifetime of the current HTTP request."""

    def wrapper(*args, **kwargs) -> T:
        cache = _cache_var.get()
        if cache is None:
            return fn(*args, **kwargs)
        key = f"{fn.__module__}.{fn.__qualname__}:{args!r}:{tuple(sorted(kwargs.items()))!r}"
        if key not in cache:
            cache[key] = fn(*args, **kwargs)
        return cache[key]  # type: ignore[return-value]

    return wrapper
