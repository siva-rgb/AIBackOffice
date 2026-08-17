# Onboarding a Contributor to KORA (GCP + Repo)

A step-by-step sequence for the **project owner** to give a developer access to the
KORA GCP project and codebase — **without ever sharing your password or a
service-account key file**. The developer gets their own Google identity with
scoped, least-privilege roles.

> Two people are involved. Steps marked **[OWNER]** are done by you. Steps marked
> **[DEV]** are done by the contributor. Do them in order — later steps depend on
> earlier ones.

---

## What KORA uses on GCP (context)

The role set below is derived from KORA's actual deploy pipeline
([cloudbuild.yaml](../cloudbuild.yaml), [DEPLOY.md](../DEPLOY.md),
[gcp_setup.md](gcp_setup.md), [specs/gcp-cloud.md](specs/gcp-cloud.md)):

| Service | Used for |
|---|---|
| Cloud Run | hosts `kora-backend` + `kora-frontend` |
| Cloud Build | builds/pushes images, runs the deploy |
| Artifact Registry (`kora` repo) | stores the Docker images |
| Cloud Storage (`kora-storage-private-*`) | user documents / PDFs |
| Secret Manager | runtime secrets (`MODEL_API_KEY`, `STRIPE_SECRET_KEY`, `TOKEN_ENCRYPTION_KEY`, …) |
| Vertex AI | production LLM inference |
| Cloud Logging | debugging |

Gmail / Calendar / Drive are per-user OAuth, **not** IAM — ignore them here.

---

## Prerequisites

- **[DEV]** has a **Google account** (Gmail or Google Workspace) — this email is
  their GCP identity.
- **[DEV]** has a **GitHub account** — for the repo.
- **[OWNER]** knows the **GCP Project ID** (e.g. `kora-prod-123456`).
- Both accounts have **2-Factor Authentication** enabled.

---

## Step 1 — [OWNER] Collect the developer's details

Ask the contributor for:

1. Their **Google account email** (the exact address — Gmail or Workspace).
2. Their **GitHub username**.

---

## Step 2 — [OWNER] Grant GCP IAM roles

Open **[Google Cloud Console](https://console.cloud.google.com)** → select the KORA
project → click **Activate Cloud Shell** (top-right terminal icon).

Paste this block, editing the first two lines, then press Enter:

```bash
# ── Grant a developer contributor access to KORA (least-privilege) ──
DEV="user:DEV_EMAIL"                 # e.g. user:jane@gmail.com
PROJECT="PROJECT_ID"                 # e.g. kora-prod-123456

for ROLE in \
  roles/run.developer \
  roles/cloudbuild.builds.editor \
  roles/artifactregistry.writer \
  roles/storage.objectAdmin \
  roles/secretmanager.secretAccessor \
  roles/aiplatform.user \
  roles/logging.viewer \
  roles/iam.serviceAccountUser \
  roles/serviceusage.serviceUsageConsumer
do
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="$DEV" --role="$ROLE" --condition=None
done
```

### What each role does (and why it's safe)

| Role | Why the dev needs it | Why it's safe |
|---|---|---|
| `run.developer` | deploy/update the two Cloud Run services | can't change IAM or delete the project |
| `cloudbuild.builds.editor` | run `gcloud builds submit` | build-only |
| `artifactregistry.writer` | push/pull Docker images | can't delete the repo |
| `storage.objectAdmin` | read/write files in the bucket | object-level, not bucket admin |
| `secretmanager.secretAccessor` | **read** secret values the app needs | can't create/edit/delete secrets |
| `aiplatform.user` | call Vertex AI | inference only |
| `logging.viewer` | debug via Cloud Logging | read-only |
| `iam.serviceAccountUser` | deploy services that run *as* `kora-backend` | can't create keys or new SAs |
| `serviceusage.serviceUsageConsumer` | let their SDK/API calls go through | standard for any dev |

> **Console alternative:** IAM & Admin → **IAM** → **+ Grant access** → New
> principals = the dev's email → add each role above → **Save**.

### Do NOT grant

- ❌ `Owner`, `Editor` — too broad (can delete the project, add/remove people).
- ❌ Any **Billing** role — keeps your payment methods untouchable.
- ❌ Never email them a service-account **JSON key**.

---

## Step 3 — [OWNER] Add the developer to the GitHub repo

1. Go to the repo on GitHub → **Settings** → **Collaborators and teams**.
2. **Add people** → enter their GitHub username → role **Write**.
3. They'll receive an email invite to accept.

> Branch protection on `main` is recommended — require PRs so contributions come
> through review rather than direct pushes.

---

## Step 4 — [DEV] Accept invites & install tooling

1. Accept the **GitHub** collaborator invite (email).
2. Accept the **GCP** access — signing into
   [console.cloud.google.com](https://console.cloud.google.com) with the invited
   Google account should now show the KORA project in the project picker.
3. Install:
   - [Google Cloud CLI (`gcloud`)](https://cloud.google.com/sdk/docs/install)
   - [Docker Desktop](https://www.docker.com/products/docker-desktop/) (for building images)
   - [Node.js 20](https://nodejs.org/) and Python 3.11 (KORA's runtimes)
   - Git

---

## Step 5 — [DEV] Authenticate with GCP (no key files)

Run these locally — **use your own Google account**, never a shared key:

```bash
# 1. Log in (opens a browser)
gcloud auth login

# 2. Point the CLI at the KORA project
gcloud config set project PROJECT_ID          # e.g. kora-prod-123456

# 3. Set up Application Default Credentials so the app's SDK can authenticate
gcloud auth application-default login

# 4. Let Docker push/pull to Artifact Registry
gcloud auth configure-docker us-central1-docker.pkg.dev
```

Verify access:

```bash
gcloud run services list --region=us-central1        # should list kora-backend / kora-frontend
gcloud storage buckets list                          # should show the kora bucket
```

---

## Step 6 — [DEV] Clone the repo & configure local env

```bash
git clone https://github.com/OWNER/REPO.git kora
cd kora
```

Set up environment files:

- **Backend:** copy `backend/.env.example` → `backend/.env` (ask the owner for any
  values not in Secret Manager). With `gcloud auth application-default login` done
  in Step 5, you do **not** need a `GOOGLE_APPLICATION_CREDENTIALS` JSON file —
  ADC is used automatically. Set `GOOGLE_CLOUD_PROJECT_ID` to the project ID.
- **Frontend:** copy `frontend/.env.local.example` → `frontend/.env.local`.

Install & run (see [DEPLOY.md](../DEPLOY.md) and the repo README for details):

```bash
# Backend
cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload

# Frontend (separate terminal)
cd frontend && npm install && npm run dev
```

---

## Step 7 — [DEV] First contribution flow

```bash
git checkout -b feature/your-change
# ...make changes, commit...
git push -u origin feature/your-change
```

Open a Pull Request against `main`. The owner reviews and merges.

To deploy (if authorized):

```bash
gcloud builds submit --config cloudbuild.yaml \
  --substitutions=_REGION=us-central1,_FRONTEND_ORIGIN=https://<frontend-url>,...
```

(See [DEPLOY.md](../DEPLOY.md) for the full substitutions list.)

---

## Step 8 — [OWNER] Ongoing management

**Audit access anytime:**

```bash
gcloud projects get-iam-policy PROJECT_ID \
  --flatten="bindings[].members" \
  --filter="bindings.members:DEV_EMAIL" \
  --format="table(bindings.role)"
```

**Revoke ALL access** when the contributor leaves — run in Cloud Shell:

```bash
DEV="user:DEV_EMAIL"
PROJECT="PROJECT_ID"

for ROLE in \
  roles/run.developer \
  roles/cloudbuild.builds.editor \
  roles/artifactregistry.writer \
  roles/storage.objectAdmin \
  roles/secretmanager.secretAccessor \
  roles/aiplatform.user \
  roles/logging.viewer \
  roles/iam.serviceAccountUser \
  roles/serviceusage.serviceUsageConsumer
do
  gcloud projects remove-iam-policy-binding "$PROJECT" \
    --member="$DEV" --role="$ROLE" --condition=None
done
```

Also remove them from the **GitHub** repo collaborators list.

---

## Optional — tighter security

- **Scope Storage/Secrets instead of project-wide.** Grant `storage.objectAdmin`
  on the specific bucket and `secretAccessor` on specific secrets rather than the
  whole project. Start broad, narrow once they're set up.
- **Hide prod secrets.** If the dev shouldn't see values like `STRIPE_SECRET_KEY`,
  drop `secretmanager.secretAccessor` and give them a separate dev secret set.
- **CI instead of local deploy keys.** For automated deploys, use **Workload
  Identity Federation** rather than long-lived JSON keys.
- **Require 2FA** on both Google and GitHub accounts.

---

## Quick checklist

- [ ] [OWNER] Got dev's Google email + GitHub username
- [ ] [OWNER] Ran the IAM grant block in Cloud Shell
- [ ] [OWNER] Added dev to GitHub repo (Write)
- [ ] [DEV] Accepted both invites
- [ ] [DEV] Installed gcloud, Docker, Node 20, Python 3.11, Git
- [ ] [DEV] `gcloud auth login` + `application-default login` + `configure-docker`
- [ ] [DEV] Cloned repo, set up `.env` files, ran app locally
- [ ] [DEV] Opened first PR
