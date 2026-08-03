# GCP Setup Guide for KORA

Complete walkthrough to configure a personal GCP account so KORA runs end-to-end.
Follow every section in order — later sections depend on resources created earlier.

---

## 1. Create a New GCP Project

1. Go to https://console.cloud.google.com
2. Click the project selector (top bar) → **New Project**
3. **Project name:** `kora-prod` (or any name you prefer)
4. Note the auto-generated **Project ID** (e.g. `kora-prod-123456`) — this goes into `GOOGLE_CLOUD_PROJECT_ID`
5. Click **Create** and wait for it to provision

---

## 2. Enable Required APIs

Go to **APIs & Services → Library** and enable each of the following:

| API Name | Why it's needed |
|---|---|
| Cloud Storage API | Document/PDF storage, exports |
| Cloud Resource Manager API | Required for many SDK calls |
| Identity and Access Management (IAM) API | Service account management |
| Gmail API | Email reading + sending via Google integration |
| Google Calendar API | Calendar event sync |
| Google Drive API | Document discovery |
| Google OAuth2 API | User login + token refresh |
| Cloud AI Platform (Vertex AI) API | LLM inference (production) |
| Document AI API | (Optional) PDF extraction upgrade |

**Quick way — run this in Cloud Shell:**
```bash
gcloud services enable \
  storage.googleapis.com \
  cloudresourcemanager.googleapis.com \
  iam.googleapis.com \
  gmail.googleapis.com \
  calendar-json.googleapis.com \
  drive.googleapis.com \
  aiplatform.googleapis.com \
  documentai.googleapis.com \
  --project=YOUR_PROJECT_ID
```

---

## 3. Create a Service Account (Backend Identity)

This service account is used by the FastAPI backend to call Cloud Storage and Vertex AI.

1. Go to **IAM & Admin → Service Accounts**
2. Click **+ Create Service Account**
   - Name: `kora-backend`
   - Description: `KORA FastAPI backend service account`
3. Click **Create and Continue**
4. Grant the following roles:

| Role | Purpose |
|---|---|
| `Storage Object Admin` (`roles/storage.objectAdmin`) | Upload/download/delete files in GCS |
| `Storage Bucket Reader` (`roles/storage.legacyBucketReader`) | List bucket contents |
| `Vertex AI User` (`roles/aiplatform.user`) | Call Vertex AI / Gemini models |
| `Document AI Editor` (`roles/documentai.editor`) | (Optional) Document AI processing |

5. Click **Done**

### Download the JSON Key
1. Click on the newly created `kora-backend` service account
2. Go to **Keys** tab → **Add Key → Create new key**
3. Choose **JSON** → **Create**
4. Save the downloaded file as:
   ```
   kora/backend/pg-us-n-app-119329-4e39c909e089.json
   ```
   (or any filename — update `GOOGLE_APPLICATION_CREDENTIALS` in `.env` to match)

> **Security:** Never commit this JSON file to git. It is already in `.gitignore`.

---

## 4. Create a Cloud Storage Bucket

> **Canonical bucket naming:** see [`docs/specs/gcp-cloud.md`](specs/gcp-cloud.md) §1 Step 1.
> Use `kora-storage-private-{your-project-id}` — not a bare `kora-user-data` name.

1. Go to **Cloud Storage → Buckets → + Create**
2. **Name:** `kora-storage-private-{your-project-id}` (must be globally unique — see gcp-cloud.md)
3. **Region:** `us-central1` (match `GOOGLE_CLOUD_LOCATION`)
4. **Storage class:** Standard
5. **Access control:** Uniform
6. **Public access:** Enforce public access prevention (keep private)
7. Click **Create**

### Grant the Service Account Access to the Bucket
1. In the bucket, go to **Permissions** tab
2. Click **+ Grant Access**
3. Principal: `kora-backend@YOUR_PROJECT_ID.iam.gserviceaccount.com`
4. Role: `Storage Object Admin`
5. Save

Update `.env`:
```
CLOUD_STORAGE_BUCKET=kora-storage-private-{your-project-id}
```

---

## 5. Configure OAuth 2.0 (Google Login + Gmail/Calendar/Drive)

### 5a. Configure the OAuth Consent Screen
1. Go to **APIs & Services → OAuth consent screen**
2. User type: **External** (for personal testing; Internal if using a Google Workspace org)
3. Fill in:
   - App name: `Kora`
   - User support email: your email
   - Developer contact email: your email
4. Click **Save and Continue**
5. On **Scopes**, add:
   - `openid`
   - `email`
   - `profile`
   - `https://www.googleapis.com/auth/gmail.readonly`
   - `https://www.googleapis.com/auth/gmail.send`
   - `https://www.googleapis.com/auth/calendar.readonly`
   - `https://www.googleapis.com/auth/calendar.events`
   - `https://www.googleapis.com/auth/drive.readonly`
6. On **Test users**, add your own Gmail address (required while app is in "Testing" status)
7. Click **Save and Continue**

### 5b. Create OAuth 2.0 Client ID
1. Go to **APIs & Services → Credentials → + Create Credentials → OAuth client ID**
2. Application type: **Web application**
3. Name: `Kora Web`
4. Authorized redirect URIs — add all of these:
   ```
   http://localhost:8000/api/auth/google/callback
   http://localhost:3000/api/auth/google/callback
   ```
   (Add production URL too when you deploy, e.g. `https://yourdomain.com/api/auth/google/callback`)
5. Click **Create**
6. Copy **Client ID** and **Client Secret**

Update `.env`:
```
GOOGLE_OAUTH_CLIENT_ID=YOUR_CLIENT_ID.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=GOCSPX-YOUR_SECRET
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:8000/api/auth/google/callback
```

---

## 6. Vertex AI Setup (Production LLM)

KORA currently uses an OpenAI-compatible gateway in dev (`MODEL_API_KEY` + `BASE_URL`).
To switch to Vertex AI / Gemini in production:

1. Vertex AI API must be enabled (done in step 2)
2. The service account needs `roles/aiplatform.user` (done in step 3)
3. Region must support Gemini — `us-central1` works

Update `.env` for Vertex AI mode:
```
KORA_AI_BACKEND=vertex
GOOGLE_CLOUD_PROJECT_ID=YOUR_PROJECT_ID
GOOGLE_CLOUD_LOCATION=us-central1
```

The backend's `vertex_ai.py` will use Application Default Credentials (ADC) from the service account JSON automatically when `GOOGLE_APPLICATION_CREDENTIALS` is set.

---

## 7. Document AI (Optional — advanced PDF extraction)

Currently KORA uses `pypdf`/`pdfplumber` for text extraction. Document AI gives higher accuracy for structured documents like invoices and contracts.

1. Go to **Document AI → Create Processor**
2. Choose **Form Parser** (for invoices) or **Document OCR**
3. Region: `us` or `eu`
4. Note the **Processor ID** shown after creation
5. Update `.env`:
   ```
   DOCUMENT_AI_PROCESSOR_ID=YOUR_PROCESSOR_ID
   ```

The service account needs `roles/documentai.editor` (already granted in step 3).

---

## 8. Final `.env` Block

After completing all steps, your `.env` GCP section should look like this:

```env
# --- Google Cloud ----------------------------------------------------------
GOOGLE_CLOUD_PROJECT_ID=kora-prod-123456
GOOGLE_CLOUD_LOCATION=us-central1
GOOGLE_APPLICATION_CREDENTIALS=kora/backend/kora-backend-key.json
CLOUD_STORAGE_BUCKET=kora-user-data-kora-prod-123456
DOCUMENT_AI_PROCESSOR_ID=abc1234567890

# Google OAuth (Gmail / Calendar / Drive + user login)
GOOGLE_OAUTH_CLIENT_ID=549651366634-xxxxxxxxxxxx.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=GOCSPX-xxxxxxxxxxxx
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:8000/api/auth/google/callback
```

---

## 9. Verify Everything Works

### Test service account credentials
```bash
cd kora/backend
python -c "
from google.cloud import storage
from app.config import settings
client = storage.Client.from_service_account_json(settings.GOOGLE_APPLICATION_CREDENTIALS, project=settings.GOOGLE_CLOUD_PROJECT_ID)
print('Buckets:', [b.name for b in client.list_buckets()])
"
```

### Test GCS upload
```bash
python -c "
from app.services import storage as gcs
print('Configured:', gcs.is_configured())
gcs.upload_text('test/hello.txt', 'hello kora')
print('Upload OK')
"
```

### Test OAuth flow
1. Start both servers (`npm run dev` + `uvicorn app.main:app --reload`)
2. Go to `http://localhost:3000/settings`
3. Click **Connect Google** — you should be redirected to Google's consent screen
4. After granting access, you should land back on Settings with "Google connected"

---

## 10. IAM Summary (Quick Reference)

| Service Account | Roles | Used for |
|---|---|---|
| `kora-backend@PROJECT.iam.gserviceaccount.com` | `storage.objectAdmin`, `storage.legacyBucketReader`, `aiplatform.user`, `documentai.editor` | Backend server process |

| OAuth Client | Scopes | Used for |
|---|---|---|
| `Kora Web` (Web app) | gmail, calendar, drive, openid, email, profile | Per-user Google integrations |

---

## 11. Production Checklist (When Deploying)

- [ ] Add production redirect URI to OAuth client (e.g. `https://app.kora.xyz/api/auth/google/callback`)
- [ ] Move service account JSON to a Secret Manager secret (never deploy as a file)
- [ ] Set `GOOGLE_APPLICATION_CREDENTIALS` to the Secret Manager path or use Workload Identity on Cloud Run
- [ ] Set OAuth consent screen status to **In production** (requires Google verification for sensitive scopes)
- [ ] Enable bucket versioning for user data protection
- [ ] Set bucket lifecycle rules (e.g. delete exports after 30 days)
- [ ] Restrict OAuth client to production domain only
