"""Background CSV import job tracking (M8.5)."""

from __future__ import annotations

from threading import Lock
from typing import Any

from .. import store
from .bookkeeper import IngestResult, ingest_transactions

_lock = Lock()
_jobs: dict[str, dict[str, Any]] = {}


def create_job(user_id: str) -> str:
    job_id = store.uid("import")
    with _lock:
        _jobs[job_id] = {"jobId": job_id, "userId": user_id, "status": "pending"}
    return job_id


def get_job(job_id: str, user_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(job_id)
    if not job or job.get("userId") != user_id:
        return None
    return dict(job)


def run_import_job(job_id: str, user_id: str, currency: str, rows) -> None:
    with _lock:
        _jobs[job_id]["status"] = "processing"
    try:
        result: IngestResult = ingest_transactions(user_id, currency, rows)
        payload = {
            "status": "done",
            "inserted": result.inserted,
            "duplicatesSkipped": result.duplicates_skipped,
            "lowConfidence": result.low_confidence,
            "avgConfidence": result.avg_confidence,
            "reconciled": result.reconciled,
        }
    except Exception as exc:
        payload = {"status": "error", "error": str(exc)[:200]}
    with _lock:
        _jobs[job_id].update(payload)
