"""Background CSV import job tracking (M8.5).

Job state is persisted via the store (`import_jobs` table) rather than an
in-process dict, so status is queryable across workers and survives a restart.
Under multiple workers the previous in-memory design returned a 404 for a job
that had actually succeeded on a different worker.
"""

from __future__ import annotations

from typing import Any

from .. import store
from .bookkeeper import IngestResult, ingest_transactions


def create_job(user_id: str) -> str:
    job_id = store.uid("import")
    store.create_import_job(user_id, job_id)
    return job_id


def get_job(job_id: str, user_id: str) -> dict[str, Any] | None:
    job = store.get_import_job(user_id, job_id)
    if not job:
        return None
    # Reconstruct the flat camelCase response the frontend polls for.
    shaped: dict[str, Any] = {"jobId": job["id"], "status": job.get("status")}
    shaped.update(job.get("result") or {})
    if job.get("error"):
        shaped["error"] = job["error"]
    return shaped


def run_import_job(job_id: str, user_id: str, currency: str, rows) -> None:
    store.update_import_job(user_id, job_id, {"status": "processing"})
    try:
        result: IngestResult = ingest_transactions(user_id, currency, rows)
        store.update_import_job(
            user_id,
            job_id,
            {
                "status": "done",
                "result": {
                    "inserted": result.inserted,
                    "duplicatesSkipped": result.duplicates_skipped,
                    "lowConfidence": result.low_confidence,
                    "avgConfidence": result.avg_confidence,
                    "reconciled": result.reconciled,
                },
            },
        )
    except Exception as exc:
        store.update_import_job(
            user_id, job_id, {"status": "error", "error": str(exc)[:200]}
        )
