"""Connection pooling for Supabase and HTTP clients (M8.2).

The Supabase Python client and httpx.AsyncClient are expensive to construct per
request. This module provides process-wide singletons with keep-alive limits so
dashboard/list endpoints reuse connections across workers.
"""

from __future__ import annotations

from functools import lru_cache

import httpx
from supabase import Client, create_client

from ..config import settings

_http: httpx.AsyncClient | None = None


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    """Return a shared Supabase client (service role)."""
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)


def get_async_http() -> httpx.AsyncClient:
    """Return a shared async HTTP client with connection pooling."""
    global _http
    if _http is None:
        _http = httpx.AsyncClient(
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
            timeout=30.0,
        )
    return _http


def close_pools() -> None:
    """Close pooled clients (tests / shutdown)."""
    global _http
    if _http is not None:
        _http = None
    get_supabase.cache_clear()
