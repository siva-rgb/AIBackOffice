"""Rate limiting — in-memory fallback and Redis-backed global limits (M6)."""

from __future__ import annotations

import multiprocessing as mp
import os
import uuid

import pytest
import redis

from app.utils.rate_limit import check_rate_limit, reset_rate_limit_backend_for_tests

# CI workflow exposes Redis on 6379; local runs can skip multi_worker without it.
REDIS_TEST_URL = os.environ.get("REDIS_TEST_URL", "redis://127.0.0.1:6379/15")


def _redis_available(url: str) -> bool:
    try:
        client = redis.from_url(url, decode_responses=True, socket_connect_timeout=0.5)
        client.ping()
        return True
    except (redis.RedisError, OSError):
        return False


@pytest.fixture
def in_memory_rate_limit(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "")
    from app.config import settings

    monkeypatch.setattr(settings, "REDIS_URL", "")
    reset_rate_limit_backend_for_tests()
    yield
    reset_rate_limit_backend_for_tests()


@pytest.fixture
def redis_rate_limit(monkeypatch):
    if not _redis_available(REDIS_TEST_URL):
        pytest.skip(f"Redis not reachable at {REDIS_TEST_URL}")

    monkeypatch.setenv("REDIS_URL", REDIS_TEST_URL)
    from app.config import settings

    monkeypatch.setattr(settings, "REDIS_URL", REDIS_TEST_URL)
    reset_rate_limit_backend_for_tests()
    client = redis.from_url(REDIS_TEST_URL, decode_responses=True)
    client.flushdb()
    yield client
    client.flushdb()
    reset_rate_limit_backend_for_tests()


def test_in_memory_allows_up_to_max(in_memory_rate_limit):
    key = f"test:mem:{uuid.uuid4()}"
    max_requests = 3
    for _ in range(max_requests):
        assert check_rate_limit(key, max_requests, 60).allowed is True
    assert check_rate_limit(key, max_requests, 60).allowed is False


def test_redis_allows_up_to_max(redis_rate_limit):
    key = f"test:redis:{uuid.uuid4()}"
    max_requests = 5
    for _ in range(max_requests):
        assert check_rate_limit(key, max_requests, 60).allowed is True
    blocked = check_rate_limit(key, max_requests, 60)
    assert blocked.allowed is False
    assert blocked.remaining == 0


def _multi_worker_hits(args: tuple) -> None:
    """Worker entrypoint — must be top-level for Windows spawn."""
    redis_url, key, max_requests, window_seconds, attempts, out_queue = args
    os.environ["REDIS_URL"] = redis_url
    os.environ.setdefault("KORA_DATA_BACKEND", "mock")
    os.environ.setdefault(
        "TOKEN_ENCRYPTION_KEY",
        "7Xa5l8OaKCyJqfqJdSG1fRXPtga_ofNl8v2EbfsAIWM=",
    )
    from app.utils.rate_limit import check_rate_limit, reset_rate_limit_backend_for_tests

    reset_rate_limit_backend_for_tests()
    allowed = 0
    for _ in range(attempts):
        if check_rate_limit(key, max_requests, window_seconds).allowed:
            allowed += 1
    out_queue.put(allowed)


def test_multi_worker_enforces_global_limit(redis_rate_limit):
    """M6 gate: concurrent processes share one Redis-backed counter."""
    key = f"test:multi:{uuid.uuid4()}"
    max_requests = 12
    window_seconds = 120
    workers = 4
    attempts_per_worker = 15

    ctx = mp.get_context("spawn")
    out_queue: mp.Queue = ctx.Queue()
    jobs = [
        (REDIS_TEST_URL, key, max_requests, window_seconds, attempts_per_worker, out_queue)
        for _ in range(workers)
    ]

    processes = [ctx.Process(target=_multi_worker_hits, args=(job,)) for job in jobs]
    for proc in processes:
        proc.start()
    for proc in processes:
        proc.join(timeout=30)
        assert proc.exitcode == 0, f"worker exited with {proc.exitcode}"

    total_allowed = sum(out_queue.get_nowait() for _ in range(workers))
    assert total_allowed == max_requests
