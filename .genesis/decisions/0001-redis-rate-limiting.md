# ADR 0001 — Distributed rate limiting via Redis

## Status
Accepted (2026-07-28, M6)

## Context
AI-facing routers call `check_rate_limit()` per user/action. The MVP used an in-process sliding window, which **multiplies** the effective limit by worker count on Cloud Run / Gunicorn.

## Decision
- Add optional `REDIS_URL`. When set, enforce limits with a **Redis sorted-set sliding window** (shared across all workers).
- When `REDIS_URL` is empty, keep the existing in-process limiter for local zero-deps dev (documented as **not** multi-instance safe).
- CI runs multi-worker regression tests against a real Redis service container (`redis:7-alpine`).

## Consequences
- Production / staging must set `REDIS_URL` (e.g. Upstash, Memorystore, ElastiCache).
- Adds `redis` PyPI dependency; tests use DB index `/15` and flush between cases.
- No change to router call sites — same `check_rate_limit(key, max, window)` API.

## Alternatives considered
- Sticky sessions: rejected — uneven load, poor fit for Cloud Run scale-to-zero.
- Supabase table store (SKILL.md sketch): deferred — Redis is standard for rate counters and lower write latency.
