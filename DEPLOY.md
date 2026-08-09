# Deploying KORA to Cloud Run

Both services are containerized: `backend/Dockerfile` (FastAPI/uvicorn) and
`frontend/Dockerfile` (Next.js standalone). `cloudbuild.yaml` builds, pushes, and
deploys both.

## The one thing that bites everyone: build-time vs runtime env

Next.js **inlines every `NEXT_PUBLIC_*` variable into the client bundle at build
time**. They are *not* runtime env vars — setting them on the Cloud Run service
does nothing for the browser bundle. Consequences:

1. **The backend must deploy first.** Its public URL becomes the frontend's
   `NEXT_PUBLIC_API_URL` **build arg**. `cloudbuild.yaml` enforces this order:
   deploy backend → read its URL → build the frontend with that URL baked in.
2. **Changing the API URL means rebuilding the frontend image**, not just
   restarting it.

Backend env (`MODEL_API_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `STRIPE_SECRET_KEY`,
`TOKEN_ENCRYPTION_KEY`, Google creds, …) **is** runtime env — set it on the
Cloud Run service, ideally from Secret Manager. Never bake secrets into an image
(that's why `.dockerignore` excludes `.env*` and the service-account JSON).

## CORS

The backend allows `FRONTEND_ORIGIN` in production and adds the localhost dev
origins **only** when `ENVIRONMENT != production` (`app/main.py`). So in prod:
set `ENVIRONMENT=production` and `FRONTEND_ORIGIN=https://<your-frontend-url>` on
the backend service. Because the frontend URL isn't known until it deploys, the
usual flow is:

1. Deploy backend (with a placeholder or the eventual frontend origin).
2. Build + deploy frontend → note its URL.
3. Update the backend's `FRONTEND_ORIGIN` to the real frontend URL and redeploy
   (or set it up front if you're using a custom domain).

## Runtime secrets — bind them or the revision never starts

`backend/app/services/token_encryption.py` builds its Fernet key **at import
time** and raises if `TOKEN_ENCRYPTION_KEY` is missing (M3, deliberate). A deploy
that doesn't bind it produces a container that exits before serving a request, so
the Cloud Run revision never becomes ready — with no obvious error at the CLI.

`ops/gcp_bootstrap.sh` is the one-time fix. It is idempotent, so re-running it is
safe:

```bash
GCP_PROJECT_ID=my-project REGION=us-central1 bash ops/gcp_bootstrap.sh
bash ops/gcp_bootstrap.sh --dry-run     # show what it would do first
```

It enables the required APIs, creates the `kora` Artifact Registry repo, loads
every secret in `ops/secrets.sh` from `backend/.env` into Secret Manager (one
secret per variable, same name), and grants the runtime + build service accounts
the roles they need. `ops/deploy.sh` and `cloudbuild.yaml` then bind whatever
exists — a project without Notion or Stripe still deploys.

**`ALLOW_DEMO_USER` must be `false` in any deployed environment.** It defaults to
`True`, and with it on, every `/api/*` route serves the seeded demo user's real
data to anonymous callers. Both deploy paths now set it explicitly, and
`get_current_user` additionally ignores the flag when `ENVIRONMENT` is
`production`/`staging`. This was a live S1 caught by the staging smoke gate —
see `docs/uat/UAT_PLAN.md` §7 D-001.

## Verify before and after — the UAT gates

Never promote on an unverified deploy. `ops/uat.sh` runs the automated half of
`docs/uat/UAT_PLAN.md`:

```bash
bash ops/uat.sh all           # G0–G3: preflight, backend, frontend, e2e
# ...deploy...
bash ops/uat.sh smoke --target <backend-url> --frontend <frontend-url>
```

The smoke gate is what catches deployment-configuration bugs that unit tests
cannot: anonymous access, missing security headers, CORS mismatch, leaked stack
traces. Warm the service with one request first — a cold start can exceed the
gate's 20 s timeout.

## Deploying without a local Docker daemon

`ops/deploy.sh` builds images locally and needs Docker Desktop running. When it
isn't, hand the build to Cloud Build instead — same `cloudbuild.yaml`, same
secret bindings, same service names:

```bash
bash ops/cloudbuild_deploy.sh staging
bash ops/cloudbuild_deploy.sh production
```

It reads the `NEXT_PUBLIC_*` values from `frontend/.env.local`, tags images with
the short git SHA, and prints the follow-up command when `FRONTEND_ORIGIN` needs
a second pass (see the CORS chicken-and-egg above).

## One-shot deploy (Cloud Build)

```bash
gcloud builds submit --config cloudbuild.yaml \
  --substitutions=\
_REGION=us-central1,\
_FRONTEND_ORIGIN=https://app.yourdomain.com,\
_NEXT_PUBLIC_SUPABASE_URL=https://xxxx.supabase.co,\
_NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJ...,\
_NEXT_PUBLIC_STRIPE_STARTER_PRICE_ID=price_...,\
_NEXT_PUBLIC_STRIPE_PRO_PRICE_ID=price_...
```

Prerequisites (one-time):
- An Artifact Registry repo named `kora` in `$_REGION`
  (`gcloud artifacts repositories create kora --repository-format=docker --location=us-central1`).
- Cloud Build's service account granted `run.admin` + `iam.serviceAccountUser`.
- Runtime secrets bound to the backend service (Secret Manager → `--set-secrets`).

## Building / running an image locally

Requires the Docker daemon running (Docker Desktop on Windows/Mac).

```bash
# Frontend — the NEXT_PUBLIC_* args are baked in:
docker build -t kora-frontend ./frontend \
  --build-arg NEXT_PUBLIC_API_URL=http://localhost:8000 \
  --build-arg NEXT_PUBLIC_SUPABASE_URL=... \
  --build-arg NEXT_PUBLIC_SUPABASE_ANON_KEY=...
docker run --rm -p 3000:8080 kora-frontend      # serves on http://localhost:3000
curl -fsS localhost:3000 >/dev/null && echo OK

# Backend:
docker build -t kora-backend ./backend
docker run --rm -p 8000:8080 --env-file backend/.env kora-backend
```

Cloud Run supplies `$PORT` (defaults to 8080); both images honor it.

## Automated CI/CD (GitHub Actions) — M16

`cloudbuild.yaml` above is the manual one-shot. `.github/workflows/deploy.yml` is the
**automated pipeline**; all deploy logic lives in one script, `ops/deploy.sh`.

```
merge to main ─▶ verify (hermetic tests) ─▶ STAGING (100%, automatic)
                                                  │
                                                  ▼
                                      PRODUCTION CANARY  ⏸ held for review
                                      (new revision, 10% traffic)
                                                  │  approve
                                                  ▼
        workflow_dispatch: promote ─▶ 100% traffic  (blue/green cutover)
        workflow_dispatch: rollback ─▶ canary → 0%  (instant, prior stable never left)
```

- **Staging is automatic** on every merge to `main` (after the test gate). It deploys to
  isolated `kora-backend-staging` / `kora-frontend-staging` services — a bad staging deploy
  can never touch production.
- **Production only ever moves behind a reviewed gate.** The `production-canary` job uses the
  `production` GitHub Environment; add required reviewers in **Settings ▸ Environments ▸
  production** and the job pauses until someone approves — that is the "promotion to production
  is a reviewed action" gate.
- **Canary / blue-green (M16.4)** uses Cloud Run revision tags: the new revision deploys with
  `--no-traffic --tag=canary`, then `CANARY_PERCENT` (10%) of traffic is shifted to it while the
  prior stable revision keeps serving the rest. `promote` sends 100% to the new revision;
  `rollback` drains the canary tag to 0% — an instant, complete rollback because stable never
  went offline.

### One-time setup

Auth uses keyless **Workload Identity Federation** (no long-lived SA key in the repo). Bind a
deploy service account with `run.admin` + `iam.serviceAccountUser` + `artifactregistry.writer`.

**Repo secrets** (Settings ▸ Secrets and variables ▸ Actions ▸ Secrets):

| Secret | Purpose |
|---|---|
| `GCP_PROJECT_ID` | target project |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | WIF provider resource name |
| `GCP_SERVICE_ACCOUNT` | deploy SA email |
| `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` | baked into the frontend build |
| `NEXT_PUBLIC_STRIPE_STARTER_PRICE_ID`, `NEXT_PUBLIC_STRIPE_PRO_PRICE_ID` | baked into the frontend build |

**Environment variables** (Settings ▸ Environments ▸ `staging` / `production` ▸ Variables): set
`FRONTEND_ORIGIN` per environment (each env's own public frontend URL). Region defaults to
`us-central1` and canary to 10% via `env:` in `deploy.yml`.

Prerequisite (as with the manual path): an Artifact Registry repo named `kora` in the region.
