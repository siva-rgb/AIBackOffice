from __future__ import annotations

import logging
import os
from datetime import timedelta
from pathlib import Path

from ..config import settings

logger = logging.getLogger(__name__)

# backend dir (…/kora/backend) and repo root — used to resolve a relative
# GOOGLE_APPLICATION_CREDENTIALS path no matter the process working directory.
_BACKEND_DIR = Path(__file__).resolve().parents[2]
_REPO_ROOT = _BACKEND_DIR.parent.parent

# GCP Cloud Storage wrapper (artifacts/gcp-cloud.md). One private bucket, a
# folder per user, all access through the backend — no user ever touches GCS.
#
# Kora-specific: storage is OPTIONAL. The client and `google.cloud.storage` are
# imported lazily so the app boots and runs (Supabase + LLM gateway, no GCP)
# whether or not a bucket is configured. Call is_configured() before using it;
# routes degrade gracefully (stream on-the-fly / return 503) when it's off.
#
# Every read/write enforces the users/{user_id}/ prefix — that prefix is the
# ONLY tenant isolation, so it is checked server-side on every call.

_client = None


def is_configured() -> bool:
    """True when a bucket is set. (Credentials are resolved by the client at
    call time — on Cloud Run via the attached SA, locally via
    GOOGLE_APPLICATION_CREDENTIALS.)"""
    return bool(settings.CLOUD_STORAGE_BUCKET)


class StorageNotConfigured(RuntimeError):
    """Raised when a storage operation is attempted with no bucket configured."""


def _resolve_credentials_path() -> str | None:
    """Resolve GOOGLE_APPLICATION_CREDENTIALS to an existing file, trying the
    path as given (abs / cwd-relative), then repo-root- and backend-relative.
    Returns None when unset (client falls back to ADC / the attached SA)."""
    raw = (settings.GOOGLE_APPLICATION_CREDENTIALS or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")).strip()
    if not raw:
        return None
    for cand in (Path(raw), _REPO_ROOT / raw, _BACKEND_DIR / raw):
        if cand.is_file():
            return str(cand)
    # Configured but not found — surface clearly rather than silently using ADC.
    raise FileNotFoundError(f"GOOGLE_APPLICATION_CREDENTIALS file not found: {raw}")


def _get_client():
    global _client
    if _client is None:
        from google.cloud import storage  # lazy: package may be unused in mock setups

        project = settings.GOOGLE_CLOUD_PROJECT_ID or None
        key_path = _resolve_credentials_path()
        if key_path:
            _client = storage.Client.from_service_account_json(key_path, project=project)
        else:
            _client = storage.Client(project=project)
    return _client


def _bucket():
    if not is_configured():
        raise StorageNotConfigured("CLOUD_STORAGE_BUCKET is not set")
    return _get_client().bucket(settings.CLOUD_STORAGE_BUCKET)


# ── Path helpers ────────────────────────────────────────────────────────────
def _user_path(user_id: str, doc_type: str, filename: str) -> str:
    """Build a GCS object path, always prefixed users/{user_id}/. No traversal."""
    safe_filename = os.path.basename(filename).replace("..", "").lstrip("./")
    safe_type = doc_type.strip("/").replace("..", "")
    return f"users/{user_id}/{safe_type}/{safe_filename}"


def invoice_path(user_id: str, invoice_id: str) -> str:
    return _user_path(user_id, "invoices", f"{invoice_id}.pdf")


def contract_path(user_id: str, contract_id: str) -> str:
    return _user_path(user_id, "contracts", f"{contract_id}.pdf")


def proposal_path(user_id: str, proposal_id: str) -> str:
    return _user_path(user_id, "proposals", f"{proposal_id}.pdf")


def report_path(user_id: str, report_id: str, period: str) -> str:
    return _user_path(user_id, "reports", f"{report_id}-{period}.pdf")


def received_contract_path(user_id: str, contract_id: str, ext: str = "pdf") -> str:
    safe_ext = ext.lstrip(".").lower()
    if safe_ext not in ("pdf", "docx", "txt", "md"):
        safe_ext = "pdf"
    return _user_path(user_id, "received-contracts", f"{contract_id}.{safe_ext}")


def receipt_path(user_id: str, transaction_id: str, ext: str = "jpg") -> str:
    safe_ext = ext.lstrip(".").lower()
    if safe_ext not in ("jpg", "jpeg", "png", "pdf", "webp"):
        safe_ext = "pdf"
    return _user_path(user_id, "receipts", f"{transaction_id}.{safe_ext}")


def export_path(user_id: str, export_type: str, date_str: str) -> str:
    return _user_path(user_id, "exports", f"{export_type}-{date_str}.csv")


def _assert_owner(user_id: str, gcs_path: str) -> None:
    if not gcs_path.startswith(f"users/{user_id}/"):
        raise PermissionError(f"Path does not belong to user {user_id}")


# ── Upload ──────────────────────────────────────────────────────────────────
def upload_bytes(user_id: str, gcs_path: str, data: bytes, content_type: str) -> str:
    """Upload bytes. Returns the GCS path (store this — generate signed URLs on demand)."""
    _assert_owner(user_id, gcs_path)
    blob = _bucket().blob(gcs_path)
    blob.upload_from_string(data, content_type=content_type)
    return gcs_path


def upload_pdf(user_id: str, gcs_path: str, pdf_bytes: bytes) -> str:
    return upload_bytes(user_id, gcs_path, pdf_bytes, "application/pdf")


def upload_text(user_id: str, gcs_path: str, text: str, content_type: str = "text/plain") -> str:
    return upload_bytes(user_id, gcs_path, text.encode("utf-8"), content_type)


# ── Download ──────────────────────────────────────────────────────────────────
def download_bytes(user_id: str, gcs_path: str) -> bytes:
    _assert_owner(user_id, gcs_path)
    blob = _bucket().blob(gcs_path)
    if not blob.exists():
        raise FileNotFoundError(f"File not found: {gcs_path}")
    return blob.download_as_bytes()


# ── Signed URLs (browser download) ────────────────────────────────────────────
def _signing_kwargs() -> dict:
    """Extra `generate_signed_url` kwargs for runtimes that hold no private key.

    On Cloud Run the ambient identity is `compute_engine.Credentials` — a bare
    access token with no private key — so signing locally raises
    "you need a private key to sign credentials" and every PDF download 500s.
    Handing `generate_signed_url` the service-account email plus a live token
    makes it sign through the IAM SignBlob API instead, which needs
    `roles/iam.serviceAccountTokenCreator` on the SA itself (granted by
    ops/gcp_bootstrap.sh).

    Returns `{}` when the credentials CAN sign on their own (a service-account
    JSON via GOOGLE_APPLICATION_CREDENTIALS, i.e. local dev), so nothing about
    local behaviour changes.

    This is the class of bug no hermetic test can see: the code path is identical,
    only the ambient credential type differs between laptop and Cloud Run.
    """
    try:
        from google.auth import default as _google_auth_default
        from google.auth.transport.requests import Request as _AuthRequest

        creds, _ = _google_auth_default()
        # Service-account credentials expose a `signer` holding the private key.
        if getattr(creds, "signer", None) is not None:
            return {}
        if not getattr(creds, "valid", False):
            creds.refresh(_AuthRequest())
        email = getattr(creds, "service_account_email", None)
        token = getattr(creds, "token", None)
        if not email or not token:
            return {}
        return {"service_account_email": email, "access_token": token}
    except Exception:  # pragma: no cover - never let signing setup break the request
        logger.warning("Could not determine IAM signing credentials; attempting direct sign", exc_info=True)
        return {}


def get_signed_url(
    user_id: str,
    gcs_path: str,
    expiry_minutes: int = 15,
    filename_override: str | None = None,
) -> str:
    """Short-lived signed URL for browser download. Never expose the GCS path or
    bucket name to the browser — only the signed URL."""
    _assert_owner(user_id, gcs_path)
    blob = _bucket().blob(gcs_path)
    if not blob.exists():
        raise FileNotFoundError(f"File not found: {gcs_path}")
    disposition = f'attachment; filename="{filename_override}"' if filename_override else "attachment"
    return blob.generate_signed_url(
        expiration=timedelta(minutes=expiry_minutes),
        method="GET",
        response_disposition=disposition,
        version="v4",
        **_signing_kwargs(),
    )


# ── Delete ──────────────────────────────────────────────────────────────────
def delete_file(user_id: str, gcs_path: str) -> bool:
    _assert_owner(user_id, gcs_path)
    blob = _bucket().blob(gcs_path)
    if blob.exists():
        blob.delete()
        return True
    return False


def delete_user_data(user_id: str) -> int:
    """Delete ALL files for a user (GDPR account deletion). Returns count deleted.
    No-op (returns 0) when storage is not configured."""
    if not is_configured():
        return 0
    bucket = _bucket()
    blobs = list(bucket.list_blobs(prefix=f"users/{user_id}/"))
    if blobs:
        bucket.delete_blobs(blobs)
    return len(blobs)


# ── List ──────────────────────────────────────────────────────────────────────
def list_user_files(user_id: str, doc_type: str | None = None) -> list[dict]:
    prefix = f"users/{user_id}/{doc_type}/" if doc_type else f"users/{user_id}/"
    return [
        {
            "path": b.name,
            "name": b.name.split("/")[-1],
            "sizeBytes": b.size,
            "updated": b.updated.isoformat() if b.updated else None,
            "contentType": b.content_type,
        }
        for b in _bucket().list_blobs(prefix=prefix)
    ]
