# Kora — GCP Cloud Storage Setup & Implementation

> One private bucket. Folders per user. All access through the backend.
> No user ever touches GCP directly.

---

## 1. GCP Console setup (one time, ~10 minutes)

### Step 1 — Create the bucket

Go to: GCP Console → Cloud Storage → Buckets → Create

```
Bucket name:         kora-storage-private-{your-project-id}
                     (bucket names must be globally unique — add your project ID)

Location type:       Region
Location:            us-central1
                     (same region as your Cloud Run — avoids egress costs)

Storage class:       Standard
                     (not Nearline/Coldline — you access files frequently)

Access control:      Uniform
                     (NOT fine-grained — uniform is simpler and safer for this pattern)

Public access:       Enforce public access prevention = ON
                     This is the most important setting. Prevents any accidental
                     public exposure of user documents.

Protection:          Soft delete: 7 days
                     (lets you recover accidentally deleted files)
```

Click Create.

### Step 2 — Set IAM permissions for your service account

Your Cloud Run service already has a service account (`kora-backend@...`).
Grant it Storage Object Admin on this bucket only (not the whole project):

```bash
gcloud storage buckets add-iam-policy-binding gs://kora-storage-private-{your-project-id} \
  --member="serviceAccount:kora-backend@{your-project-id}.iam.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"
```

This gives your backend full read/write/delete on this bucket.
Your service account already has `roles/aiplatform.user` on the project.
Do NOT add `roles/storage.objectAdmin` at the project level — scope it to the bucket only.

### Step 3 — Set CORS policy (needed for direct browser upload in future)

Even if you're not doing direct browser uploads now, set this so you don't have to
reconfigure later:

Create a file `cors.json`:
```json
[
  {
    "origin": ["https://kora.app", "http://localhost:3000"],
    "method": ["GET", "PUT", "POST", "DELETE", "HEAD"],
    "responseHeader": ["Content-Type", "Content-Length", "Content-Disposition"],
    "maxAgeSeconds": 3600
  }
]
```

Apply it:
```bash
gcloud storage buckets update gs://kora-storage-private-{your-project-id} \
  --cors-file=cors.json
```

### Step 4 — Set lifecycle rules (auto-delete old temp files)

Create `lifecycle.json`:
```json
{
  "rule": [
    {
      "action": {"type": "Delete"},
      "condition": {
        "matchesPrefix": ["users/"],
        "daysSinceCustomTime": 365,
        "isLive": true
      }
    }
  ]
}
```

This is optional for MVP — skip it and add later if needed.

### Step 5 — Add bucket name to environment variables

```bash
# In .env (backend) and Vercel env vars (frontend doesn't need this — only backend):
CLOUD_STORAGE_BUCKET=kora-storage-private-{your-project-id}
```

---

## 2. Folder structure

Every file path follows this pattern:

```
users/{user_id}/{document_type}/{filename}
```

Full structure:

```
users/
  {user_id}/                              ← Supabase auth UUID
    contracts/
      {contract_id}.pdf                   ← generated contract PDFs
      {contract_id}-draft.md              ← markdown source (optional)
    proposals/
      {proposal_id}.pdf
    reports/
      {report_id}-pl-{period}.pdf         ← P&L reports from bookkeeper
    receipts/
      {transaction_id}.jpg                ← uploaded receipt images
      {transaction_id}.pdf                ← uploaded receipt PDFs
    transcripts/
      {meeting_id}.txt                    ← meeting transcript uploads
    exports/
      agent-log-{date}.csv               ← user data exports
      transactions-{period}.csv
```

Rules:
- Always use the record UUID in the filename. Never use the user's name or email.
- Always use lowercase with hyphens in filenames. No spaces, no special characters.
- The `user_id` segment is the ONLY tenant isolation. Enforce it server-side always.

---

## 3. Storage service (Python)

```python
# backend/app/services/storage.py
"""
GCP Cloud Storage wrapper for Kora.
All methods enforce user_id prefix — files can never be accessed
across users.
"""
import os
from datetime import timedelta
from google.cloud import storage
from google.oauth2 import service_account
from app.config import settings


def _get_client() -> storage.Client:
    """Return a GCS client using the service account credentials."""
    # On Cloud Run: uses the service account attached to the instance automatically.
    # Locally: uses GOOGLE_APPLICATION_CREDENTIALS env var pointing to gcloud-key.json.
    return storage.Client(project=settings.GOOGLE_CLOUD_PROJECT_ID)


def _bucket() -> storage.Bucket:
    return _get_client().bucket(settings.CLOUD_STORAGE_BUCKET)


# ── Path helpers ──────────────────────────────────────────────────────────────

def _user_path(user_id: str, doc_type: str, filename: str) -> str:
    """
    Build a GCS object path. Always prefixed with users/{user_id}/.
    Never allows path traversal — strips leading slashes and dots.
    """
    safe_filename = os.path.basename(filename).replace("..", "").lstrip("./")
    safe_type = doc_type.strip("/").replace("..", "")
    return f"users/{user_id}/{safe_type}/{safe_filename}"

def contract_path(user_id: str, contract_id: str) -> str:
    return _user_path(user_id, "contracts", f"{contract_id}.pdf")

def proposal_path(user_id: str, proposal_id: str) -> str:
    return _user_path(user_id, "proposals", f"{proposal_id}.pdf")

def report_path(user_id: str, report_id: str, period: str) -> str:
    return _user_path(user_id, "reports", f"{report_id}-{period}.pdf")

def receipt_path(user_id: str, transaction_id: str, ext: str = "jpg") -> str:
    safe_ext = ext.lstrip(".").lower()
    if safe_ext not in ("jpg", "jpeg", "png", "pdf", "webp"):
        safe_ext = "pdf"
    return _user_path(user_id, "receipts", f"{transaction_id}.{safe_ext}")

def transcript_path(user_id: str, meeting_id: str) -> str:
    return _user_path(user_id, "transcripts", f"{meeting_id}.txt")

def export_path(user_id: str, export_type: str, date_str: str) -> str:
    return _user_path(user_id, "exports", f"{export_type}-{date_str}.csv")


# ── Upload ────────────────────────────────────────────────────────────────────

def upload_bytes(
    user_id: str,
    gcs_path: str,
    data: bytes,
    content_type: str,
) -> str:
    """
    Upload bytes to GCS. Returns the GCS path (not a URL).
    Store this path in your database — generate signed URLs on demand.
    """
    # Safety check: path must start with user's prefix
    if not gcs_path.startswith(f"users/{user_id}/"):
        raise ValueError(f"Path does not belong to user {user_id}")

    blob = _bucket().blob(gcs_path)
    blob.upload_from_string(data, content_type=content_type)
    return gcs_path


def upload_pdf(user_id: str, gcs_path: str, pdf_bytes: bytes) -> str:
    return upload_bytes(user_id, gcs_path, pdf_bytes, "application/pdf")


def upload_image(user_id: str, gcs_path: str, image_bytes: bytes,
                 content_type: str = "image/jpeg") -> str:
    return upload_bytes(user_id, gcs_path, image_bytes, content_type)


def upload_text(user_id: str, gcs_path: str, text: str) -> str:
    return upload_bytes(user_id, gcs_path, text.encode("utf-8"), "text/plain")


# ── Download ──────────────────────────────────────────────────────────────────

def download_bytes(user_id: str, gcs_path: str) -> bytes:
    """
    Download file bytes. Enforces user ownership before fetching.
    Raises FileNotFoundError if path doesn't exist.
    """
    if not gcs_path.startswith(f"users/{user_id}/"):
        raise PermissionError(f"Path does not belong to user {user_id}")

    blob = _bucket().blob(gcs_path)
    if not blob.exists():
        raise FileNotFoundError(f"File not found: {gcs_path}")

    return blob.download_as_bytes()


def download_text(user_id: str, gcs_path: str) -> str:
    return download_bytes(user_id, gcs_path).decode("utf-8")


# ── Signed URLs (for browser download) ───────────────────────────────────────

def get_signed_url(
    user_id: str,
    gcs_path: str,
    expiry_minutes: int = 15,
    filename_override: str = None,
) -> str:
    """
    Generate a signed URL for browser download.
    The URL expires after expiry_minutes.
    Never expose the GCS path or bucket name to the browser — only the signed URL.

    expiry_minutes:
      - PDF downloads: 15 minutes (enough to click and download)
      - Receipt previews: 5 minutes
      - Export downloads: 30 minutes
    """
    if not gcs_path.startswith(f"users/{user_id}/"):
        raise PermissionError(f"Path does not belong to user {user_id}")

    blob = _bucket().blob(gcs_path)
    if not blob.exists():
        raise FileNotFoundError(f"File not found: {gcs_path}")

    # Content-Disposition: forces browser to download, not open inline
    # (important for contracts/PDFs — don't want them rendered in browser by default)
    response_disposition = (
        f'attachment; filename="{filename_override}"'
        if filename_override
        else "attachment"
    )

    url = blob.generate_signed_url(
        expiration=timedelta(minutes=expiry_minutes),
        method="GET",
        response_type=blob.content_type or "application/octet-stream",
        response_disposition=response_disposition,
        version="v4",
    )
    return url


# ── Delete ────────────────────────────────────────────────────────────────────

def delete_file(user_id: str, gcs_path: str) -> bool:
    """Delete a file. Returns True if deleted, False if not found."""
    if not gcs_path.startswith(f"users/{user_id}/"):
        raise PermissionError(f"Path does not belong to user {user_id}")

    blob = _bucket().blob(gcs_path)
    if blob.exists():
        blob.delete()
        return True
    return False


def delete_user_data(user_id: str) -> int:
    """
    Delete ALL files for a user. Used for GDPR account deletion.
    Returns count of deleted files.
    Call this from DELETE /api/account/delete BEFORE deleting the DB record.
    """
    bucket = _bucket()
    prefix = f"users/{user_id}/"
    blobs = list(bucket.list_blobs(prefix=prefix))
    count = len(blobs)
    if blobs:
        bucket.delete_blobs(blobs)
    return count


# ── List ──────────────────────────────────────────────────────────────────────

def list_user_files(user_id: str, doc_type: str = None) -> list[dict]:
    """
    List all files for a user, optionally filtered by type.
    Returns list of {path, size, updated, name} dicts.
    """
    prefix = f"users/{user_id}/{doc_type}/" if doc_type else f"users/{user_id}/"
    blobs = _bucket().list_blobs(prefix=prefix)
    return [
        {
            "path": b.name,
            "name": b.name.split("/")[-1],
            "size_bytes": b.size,
            "updated": b.updated.isoformat() if b.updated else None,
            "content_type": b.content_type,
        }
        for b in blobs
    ]


# ── File existence check ──────────────────────────────────────────────────────

def file_exists(user_id: str, gcs_path: str) -> bool:
    if not gcs_path.startswith(f"users/{user_id}/"):
        return False
    return _bucket().blob(gcs_path).exists()
```

---

## 4. FastAPI routes for file access

```python
# backend/app/routers/storage.py
"""
File download and upload routes.
All routes verify user ownership before touching GCS.
Signed URLs are generated here — never in the frontend.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from app.dependencies import get_current_user
from app.services import storage
from pydantic import BaseModel
from typing import Literal

router = APIRouter(prefix="/storage", tags=["storage"])

# ── Download endpoints ────────────────────────────────────────────────────────

class SignedUrlResponse(BaseModel):
    url: str
    expires_in_minutes: int

@router.get("/contracts/{contract_id}/download")
async def download_contract(contract_id: str, user=Depends(get_current_user)):
    """
    Get a signed URL to download a contract PDF.
    Frontend redirects to this URL — file downloads directly from GCS.
    """
    from supabase import create_client
    from app.config import settings as s
    db = create_client(s.SUPABASE_URL, s.SUPABASE_SERVICE_ROLE_KEY)

    # Verify the contract belongs to this user
    contract = db.table("contracts").select("pdf_url, client_name").eq(
        "id", contract_id).eq("user_id", user["id"]).single().execute().data
    if not contract or not contract.get("pdf_url"):
        raise HTTPException(404, "Contract not found")

    try:
        url = storage.get_signed_url(
            user_id=user["id"],
            gcs_path=contract["pdf_url"],
            expiry_minutes=15,
            filename_override=f"contract-{contract_id}.pdf",
        )
        return SignedUrlResponse(url=url, expires_in_minutes=15)
    except FileNotFoundError:
        raise HTTPException(404, "Contract PDF not found in storage")


@router.get("/proposals/{proposal_id}/download")
async def download_proposal(proposal_id: str, user=Depends(get_current_user)):
    from supabase import create_client
    from app.config import settings as s
    db = create_client(s.SUPABASE_URL, s.SUPABASE_SERVICE_ROLE_KEY)

    proposal = db.table("proposals").select("pdf_url, title").eq(
        "id", proposal_id).eq("user_id", user["id"]).single().execute().data
    if not proposal or not proposal.get("pdf_url"):
        raise HTTPException(404, "Proposal not found")

    url = storage.get_signed_url(
        user_id=user["id"],
        gcs_path=proposal["pdf_url"],
        expiry_minutes=15,
        filename_override=f"proposal-{proposal_id}.pdf",
    )
    return SignedUrlResponse(url=url, expires_in_minutes=15)


@router.get("/reports/{report_id}/download")
async def download_report(report_id: str, user=Depends(get_current_user)):
    from supabase import create_client
    from app.config import settings as s
    db = create_client(s.SUPABASE_URL, s.SUPABASE_SERVICE_ROLE_KEY)

    report = db.table("reports").select("pdf_url, type, period_start").eq(
        "id", report_id).eq("user_id", user["id"]).single().execute().data
    if not report or not report.get("pdf_url"):
        raise HTTPException(404, "Report not found")

    url = storage.get_signed_url(
        user_id=user["id"],
        gcs_path=report["pdf_url"],
        expiry_minutes=15,
        filename_override=f"report-{report['type']}-{report['period_start']}.pdf",
    )
    return SignedUrlResponse(url=url, expires_in_minutes=15)


# ── Receipt upload ────────────────────────────────────────────────────────────

@router.post("/receipts/{transaction_id}")
async def upload_receipt(
    transaction_id: str,
    file: UploadFile = File(...),
    user=Depends(get_current_user),
):
    """Upload a receipt image or PDF for a transaction."""
    MAX_SIZE = 10 * 1024 * 1024  # 10MB
    ALLOWED_TYPES = ["image/jpeg", "image/png", "image/webp", "application/pdf"]

    if file.size and file.size > MAX_SIZE:
        raise HTTPException(413, "Receipt file too large (max 10MB)")
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(415, "Only JPEG, PNG, WebP, or PDF files accepted")

    # Verify transaction belongs to this user
    from supabase import create_client
    from app.config import settings as s
    db = create_client(s.SUPABASE_URL, s.SUPABASE_SERVICE_ROLE_KEY)

    txn = db.table("transactions").select("id").eq(
        "id", transaction_id).eq("user_id", user["id"]).single().execute().data
    if not txn:
        raise HTTPException(404, "Transaction not found")

    content = await file.read()
    ext = (file.content_type or "").split("/")[-1].replace("jpeg", "jpg")
    gcs_path = storage.receipt_path(user["id"], transaction_id, ext)

    storage.upload_bytes(
        user_id=user["id"],
        gcs_path=gcs_path,
        data=content,
        content_type=file.content_type,
    )

    # Save path to transaction record
    db.table("transactions").update({
        "receipt_url": gcs_path
    }).eq("id", transaction_id).execute()

    return {"path": gcs_path, "size_bytes": len(content)}


# ── Export download ───────────────────────────────────────────────────────────

@router.get("/exports/agent-log")
async def download_agent_log_export(user=Depends(get_current_user)):
    """Generate and return a CSV export of the agent log for this user."""
    import csv
    import io
    from supabase import create_client
    from app.config import settings as s
    from datetime import datetime

    db = create_client(s.SUPABASE_URL, s.SUPABASE_SERVICE_ROLE_KEY)
    logs = db.table("agent_logs").select("*").eq(
        "user_id", user["id"]).order("created_at", desc=True).execute().data

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "created_at", "agent_type", "action", "status",
        "latency_ms", "triggered_by", "tokens_used"
    ])
    writer.writeheader()
    for log in logs:
        writer.writerow({
            "created_at": log.get("created_at", ""),
            "agent_type": log.get("agent_type", ""),
            "action": log.get("action", ""),
            "status": log.get("status", ""),
            "latency_ms": log.get("latency_ms", ""),
            "triggered_by": log.get("triggered_by", ""),
            "tokens_used": log.get("tokens_used", ""),
        })

    csv_bytes = output.getvalue().encode("utf-8")
    date_str = datetime.utcnow().strftime("%Y-%m-%d")

    # Upload to GCS and return signed URL
    gcs_path = storage.export_path(user["id"], "agent-log", date_str)
    storage.upload_bytes(user["id"], gcs_path, csv_bytes, "text/csv")

    url = storage.get_signed_url(
        user_id=user["id"],
        gcs_path=gcs_path,
        expiry_minutes=30,
        filename_override=f"kora-agent-log-{date_str}.csv",
    )
    return SignedUrlResponse(url=url, expires_in_minutes=30)
```

---

## 5. How existing services use storage

### Contract generator — save PDF after generation

```python
# In app/services/contract_agent.py, after PDF is generated:
from app.services import storage

async def save_contract_pdf(user_id: str, contract_id: str, pdf_bytes: bytes) -> str:
    gcs_path = storage.contract_path(user_id, contract_id)
    storage.upload_pdf(user_id, gcs_path, pdf_bytes)

    # Save path to DB (not a URL — just the GCS path)
    from supabase import create_client
    from app.config import settings
    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    db.table("contracts").update({"pdf_url": gcs_path}).eq("id", contract_id).execute()

    return gcs_path
```

### P&L report generator — same pattern

```python
# In app/services/pdf_generator.py:
from app.services import storage

async def save_report_pdf(
    user_id: str, report_id: str, period: str, pdf_bytes: bytes
) -> str:
    gcs_path = storage.report_path(user_id, report_id, period)
    storage.upload_pdf(user_id, gcs_path, pdf_bytes)

    from supabase import create_client
    from app.config import settings
    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    db.table("reports").update({"pdf_url": gcs_path}).eq("id", report_id).execute()

    return gcs_path
```

### Meeting transcript — save raw upload text

```python
# In app/routers/meetings.py, after reading the uploaded file:
from app.services import storage

gcs_path = storage.transcript_path(user_id, meeting_id)
storage.upload_text(user_id, gcs_path, transcript_text)

# Store path in meetings table
db.table("meetings").update({
    "transcript_gcs_path": gcs_path
}).eq("id", meeting_id).execute()
```

---

## 6. Frontend: how to trigger a download

The frontend never constructs GCS paths or talks to GCS directly.
It always calls your FastAPI backend to get a short-lived signed URL,
then redirects the browser to that URL.

```typescript
// lib/api/storage.ts

export async function downloadContract(contractId: string): Promise<void> {
  const { url } = await apiGet<{ url: string }>(
    `/storage/contracts/${contractId}/download`
  )
  // Open in new tab — browser handles the download
  window.open(url, "_blank")
}

export async function downloadReport(reportId: string): Promise<void> {
  const { url } = await apiGet<{ url: string }>(
    `/storage/reports/${reportId}/download`
  )
  window.open(url, "_blank")
}

export async function downloadAgentLogExport(): Promise<void> {
  const { url } = await apiGet<{ url: string }>("/storage/exports/agent-log")
  window.open(url, "_blank")
}

// Receipt upload — sends the file to your backend (not directly to GCS)
export async function uploadReceipt(
  transactionId: string,
  file: File
): Promise<void> {
  const formData = new FormData()
  formData.append("file", file)
  await fetch(`${API_BASE}/storage/receipts/${transactionId}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${await getAccessToken()}` },
    body: formData,
  })
}
```

---

## 7. GDPR account deletion — delete all files first

```python
# In app/api/account/delete route — call this BEFORE deleting DB records:
from app.services import storage

async def handle_account_deletion(user_id: str):
    # 1. Delete all GCS files for this user
    deleted_count = storage.delete_user_data(user_id)
    print(f"Deleted {deleted_count} files for user {user_id}")

    # 2. Cancel Stripe subscription
    # 3. Delete from Supabase (cascade deletes all DB records)
    # 4. Delete Supabase auth user
    # 5. Insert deletion_log row (no PII)
```

---

## 8. Cost estimate at MVP scale

```
Storage pricing (us-central1):
  Standard storage:   $0.020 per GB per month
  Operations:
    Class A (upload):  $0.05 per 10,000 operations
    Class B (read):    $0.004 per 10,000 operations
  Egress (downloads): $0.08 per GB (first 1GB/month free)

At MVP scale (50 users, ~100 files each, average 500KB per file):
  Storage:   50 × 100 × 0.5MB = 2.5GB → $0.05/month
  Downloads: ~1,000/month → well under 1GB → $0
  Uploads:   ~1,000/month → $0.005

Total at 50 users: under $0.10/month.
At 500 users: under $1/month.
Storage is effectively free at hackathon and early growth scale.
```

---

## 9. New environment variable

```bash
# Already in your stack — just make sure it's set:
CLOUD_STORAGE_BUCKET=kora-storage-private-{your-project-id}

# The GOOGLE_APPLICATION_CREDENTIALS and GOOGLE_CLOUD_PROJECT_ID
# you already have handle authentication — no new variables needed.
```

---

## 10. New pip dependency

```bash
pip install google-cloud-storage --break-system-packages
# Already in your requirements.txt from the original SKILL.md.
# If not present, add it.
```