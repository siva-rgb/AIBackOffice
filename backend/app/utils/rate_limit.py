from __future__ import annotations

import threading
import time
from dataclasses import dataclass

# Per-user rate limiting for AI endpoints (SKILL.md §16 Rule 5). In-memory
# sliding window — no Redis needed for the MVP slice. Swap for the Supabase /
# Upstash store described in the spec when going multi-instance.

_lock = threading.Lock()
_hits: dict[str, list[float]] = {}


@dataclass
class RateLimitResult:
    allowed: bool
    remaining: int
    reset_in_seconds: int


def check_rate_limit(key: str, max_requests: int, window_seconds: int) -> RateLimitResult:
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
