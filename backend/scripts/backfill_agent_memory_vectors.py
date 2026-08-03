"""Backfill `agent_memory.embedding_vec` from `agent_memory.embedding` (JSONB).

Idempotent. Pages through all rows of agent_memory, converts each row's JSONB
embedding to a pgvector literal, and writes it into the new `embedding_vec`
column. Rows where the JSONB embedding is NULL or the wrong dimensionality
are skipped (and counted).

Usage:
    python -m scripts.backfill_agent_memory_vectors              # run
    python -m scripts.backfill_agent_memory_vectors --dry-run    # report only
    python -m scripts.backfill_agent_memory_vectors --reset      # clear
                                                                # embedding_vec
                                                                # first (forces
                                                                # re-backfill)
    python -m scripts.backfill_agent_memory_vectors --batch 500  # batch size

Requires:
    - SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in the environment
      (conftest.py blanks these for the test suite; this script must NOT be
      imported under conftest's hermetic env)
    - The 2026-07-29_pgvector_agent_memory.sql migration applied
    - The settings.EMBEDDING_DIM value matches the column dimensionality
      (1536 by default; 3072 for text-embedding-3-large)

Why the script is hermetic-friendly but explicitly a script:
    The test suite (conftest.py) blanks SUPABASE_* so importing this module
    is safe; running it would early-exit at the env check. That keeps unit
    tests free of network calls without needing sys.modules tricks.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Iterable

# Allow `python -m scripts.backfill_agent_memory_vectors` from the backend dir.
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from app.config import settings  # noqa: E402  — sys.path bootstrap above
from app.clients.pool import get_supabase  # noqa: E402


DEFAULT_BATCH = 200


def _vector_literal(vec: list[float]) -> str:
    """Format a Python list of floats as a pgvector literal: '[v1,v2,...]'."""
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


def _page(sb, *, page_size: int) -> Iterable[list[dict]]:
    """Yield agent_memory pages (offset-based — pgvector ANN tables are usually
    small enough per tenant that this is fine; the table itself is bounded by
    per-user memory size, not global)."""
    offset = 0
    while True:
        resp = (
            sb.table("agent_memory")
            .select("id,user_id,embedding,embedding_vec")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        rows = resp.data or []
        if not rows:
            return
        yield rows
        if len(rows) < page_size:
            return
        offset += page_size


def run(*, dry_run: bool, reset: bool, batch: int) -> dict:
    if not (settings.SUPABASE_URL and settings.SUPABASE_SERVICE_ROLE_KEY):
        return {
            "skipped": True,
            "reason": "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not set",
        }

    sb = get_supabase()

    if reset and not dry_run:
        # Clear all embedding_vec so we re-derive from JSONB. Idempotent on
        # repeated calls (NULL <- NULL is a no-op).
        sb.table("agent_memory").update({"embedding_vec": None}).neq(
            "embedding_vec", None
        ).execute()

    counts: dict = {
        "scanned": 0,
        "updated": 0,
        "skipped_null_embedding": 0,
        "skipped_dim_mismatch": 0,
        "skipped_already_populated": 0,
        "errors": 0,
        "dim": settings.EMBEDDING_DIM,
    }

    started = time.monotonic()
    for page in _page(sb, page_size=batch):
        for row in page:
            counts["scanned"] += 1
            emb = row.get("embedding")
            if emb is None:
                counts["skipped_null_embedding"] += 1
                continue
            if row.get("embedding_vec") is not None and not reset:
                counts["skipped_already_populated"] += 1
                continue
            if isinstance(emb, str):
                try:
                    emb = json.loads(emb)
                except (TypeError, ValueError):
                    counts["errors"] += 1
                    continue
            if not isinstance(emb, list) or len(emb) != settings.EMBEDDING_DIM:
                counts["skipped_dim_mismatch"] += 1
                continue
            if dry_run:
                counts["updated"] += 1
                continue
            try:
                sb.table("agent_memory").update(
                    {"embedding_vec": _vector_literal(emb)}
                ).eq("id", row["id"]).execute()
                counts["updated"] += 1
            except Exception as exc:
                print(f"[backfill] row {row.get('id')} failed: {exc}")
                counts["errors"] += 1

    counts["elapsed_sec"] = float(round(time.monotonic() - started, 3))
    return counts


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--dry-run", action="store_true", help="report counts only, do not write"
    )
    p.add_argument(
        "--reset", action="store_true", help="clear embedding_vec before backfilling"
    )
    p.add_argument(
        "--batch",
        type=int,
        default=DEFAULT_BATCH,
        help=f"page size (default {DEFAULT_BATCH})",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    counts = run(dry_run=args.dry_run, reset=args.reset, batch=args.batch)
    print(
        json.dumps({"dry_run": args.dry_run, "reset": args.reset, **counts}, indent=2)
    )
    return 0 if counts.get("errors", 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
