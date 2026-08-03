from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

from .. import store
from ..dependencies import get_current_user
from ..models import CamelModel, User
from ..services import storage

# File download / upload routes (artifacts/gcp-cloud.md §4), adapted to Kora.
# All routes verify ownership before touching GCS; signed URLs are generated
# here, never in the frontend. Storage is optional — when no bucket is
# configured the export still works (streamed inline) and upload returns 503.

router = APIRouter(prefix="/api/storage", tags=["storage"])

_MAX_RECEIPT = 10 * 1024 * 1024  # 10 MB
_ALLOWED = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "application/pdf": "pdf"}


class SignedUrlResponse(CamelModel):
    url: str
    expires_in_minutes: int


@router.get("/status")
async def storage_status(user: User = Depends(get_current_user)):
    """Lets the frontend show/hide storage-backed features."""
    return {"configured": storage.is_configured()}


# ── Agent-log CSV export (works with or without GCS) ──────────────────────────
@router.get("/exports/agent-log")
async def export_agent_log(user: User = Depends(get_current_user)):
    logs = store.list_agent_logs(user.id)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["created_at", "agent_type", "action", "status", "latency_ms", "triggered_by", "tokens_used"])
    w.writeheader()
    for log in logs:
        w.writerow(
            {
                "created_at": log.created_at,
                "agent_type": log.agent_type,
                "action": log.action,
                "status": log.status,
                "latency_ms": log.latency_ms,
                "triggered_by": log.triggered_by,
                "tokens_used": log.tokens_used,
            }
        )
    csv_bytes = buf.getvalue().encode("utf-8")
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filename = f"kora-agent-log-{date_str}.csv"

    if storage.is_configured():
        try:
            path = storage.export_path(user.id, "agent-log", date_str)
            storage.upload_bytes(user.id, path, csv_bytes, "text/csv")
            url = storage.get_signed_url(user.id, path, expiry_minutes=30, filename_override=filename)
            return SignedUrlResponse(url=url, expires_in_minutes=30)
        except Exception as exc:  # fall back to inline stream if GCS misbehaves
            print(f"[storage] export to GCS failed, streaming inline: {exc}")
    # No bucket (or GCS error): stream the CSV directly.
    return Response(content=csv_bytes, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ── Receipt upload / download (requires GCS) ──────────────────────────────────
def _owns_transaction(user_id: str, transaction_id: str) -> bool:
    return any(t.id == transaction_id for t in store.list_transactions(user_id))


@router.post("/receipts/{transaction_id}")
async def upload_receipt(
    transaction_id: str,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    """Upload a receipt image/PDF for a transaction. Stored at a deterministic
    path (receipts/{transaction_id}.{ext}) — no DB column needed."""
    if not storage.is_configured():
        raise HTTPException(status_code=503, detail="File storage is not configured.")
    ext = _ALLOWED.get(file.content_type or "")
    if not ext:
        raise HTTPException(status_code=415, detail="Only JPEG, PNG, WebP, or PDF files accepted.")
    if not _owns_transaction(user.id, transaction_id):
        raise HTTPException(status_code=404, detail="Transaction not found")

    content = await file.read()
    if len(content) > _MAX_RECEIPT:
        raise HTTPException(status_code=413, detail="Receipt too large (max 10MB).")

    path = storage.receipt_path(user.id, transaction_id, ext)
    try:
        storage.upload_bytes(user.id, path, content, file.content_type)
    except Exception as exc:  # e.g. missing credentials off Cloud Run
        print(f"[storage] receipt upload failed: {exc}")
        raise HTTPException(status_code=503, detail="Storage unavailable — check credentials/bucket.")
    return {"path": path, "sizeBytes": len(content)}


@router.get("/receipts/{transaction_id}")
async def receipt_url(transaction_id: str, user: User = Depends(get_current_user)):
    """Signed URL for a previously uploaded receipt (found by transaction id)."""
    if not storage.is_configured():
        raise HTTPException(status_code=503, detail="File storage is not configured.")
    if not _owns_transaction(user.id, transaction_id):
        raise HTTPException(status_code=404, detail="Transaction not found")
    try:
        files = storage.list_user_files(user.id, "receipts")
        match = next((f for f in files if f["name"].startswith(f"{transaction_id}.")), None)
        if not match:
            raise HTTPException(status_code=404, detail="No receipt uploaded for this transaction.")
        url = storage.get_signed_url(user.id, match["path"], expiry_minutes=5)
    except HTTPException:
        raise
    except Exception as exc:  # missing credentials / GCS error
        print(f"[storage] receipt url failed: {exc}")
        raise HTTPException(status_code=503, detail="Storage unavailable — check credentials/bucket.")
    return SignedUrlResponse(url=url, expires_in_minutes=5)
