from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass

# Per-user rate limiting for AI endpoints (SKILL.md §16 Rule 5).
# When REDIS_URL is set, limits are enforced globally via a Redis sliding window
# (M6 / ADR 0001). Without Redis, an in-process window applies (single worker only).

_lock = threading.Lock()
_hits: dict[str, list[float]] = {}
_redis_client = None
_redis_init_lock = threading.Lock()


@dataclass
class RateLimitResult:
    allowed: bool
    remaining: int
    reset_in_seconds: int


def _redis_url() -> str:
    from app.config import settings

    return (settings.REDIS_URL or "").strip()


def _get_redis():
    global _redis_client
    url = _redis_url()
    if not url:
        return None
    if _redis_client is not None:
        return _redis_client
    with _redis_init_lock:
        if _redis_client is None:
            import redis

            _redis_client = redis.from_url(url, decode_responses=True)
    return _redis_client


def reset_rate_limit_backend_for_tests() -> None:
    """Clear in-memory state and drop cached Redis client (tests only)."""
    global _redis_client
    with _lock:
        _hits.clear()
    with _redis_init_lock:
        _redis_client = None


def _check_in_memory(key: str, max_requests: int, window_seconds: int) -> RateLimitResult:
    now = time.time()
    window_start = now - window_seconds
    with _lock:
        timestamps = [t for t in _hits.get(key, []) if t >= window_start]
        allowed = len(timestamps) < max_requests
        if allowed:
            timestamps.append(now)
        _hits[key] = timestamps
        remaining = max(0, max_requests - len(timestamps))
    return RateLimitResult(
        allowed=allowed,
        remaining=remaining,
        reset_in_seconds=window_seconds,
    )


def _check_redis(key: str, max_requests: int, window_seconds: int) -> RateLimitResult:
    client = _get_redis()
    if client is None:
        return _check_in_memory(key, max_requests, window_seconds)

    now = time.time()
    window_start = now - window_seconds
    member = f"{now}:{uuid.uuid4().hex}"

    pipe = client.pipeline()
    pipe.zremrangebyscore(key, 0, window_start)
    pipe.zadd(key, {member: now})
    pipe.zcard(key)
    pipe.expire(key, window_seconds + 1)
    _, _, count, _ = pipe.execute()

    allowed = count <= max_requests
    if not allowed:
        client.zrem(key, member)
        count -= 1

    remaining = max(0, max_requests - count)
    return RateLimitResult(
        allowed=allowed,
        remaining=remaining,
        reset_in_seconds=window_seconds,
    )


def check_rate_limit(key: str, max_requests: int, window_seconds: int) -> RateLimitResult:
    if _redis_url():
        return _check_redis(key, max_requests, window_seconds)
    return _check_in_memory(key, max_requests, window_seconds)
