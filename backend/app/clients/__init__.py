"""Shared outbound clients (M8.2)."""

from .pool import close_pools, get_async_http, get_supabase

__all__ = ["get_supabase", "get_async_http", "close_pools"]
