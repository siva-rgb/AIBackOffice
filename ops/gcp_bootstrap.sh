#!/usr/bin/env bash
#
# One-time (idempotent) GCP bootstrap for Kora.
#
#   bash ops/gcp_bootstrap.sh                     # uses gcloud's current project
#   GCP_PROJECT_ID=my-proj REGION=us-central1 bash ops/gcp_bootstrap.sh
#   bash ops/gcp_bootstrap.sh --dry-run           # show what it would do
#
# What it does:
#   1. Enables the APIs Cloud Run + Cloud Build + Artifact Registry + Secret Manager need.
#   2. Creates the `kora` Artifact Registry docker repo in $REGION.
#   3. Loads every runtime secret from backend/.env into Secret Manager, one
#      secret per variable, named exactly after the variable.
#   4. Grants the Cloud Run runtime service account `secretmanager.secretAccessor`.
#
# Why this exists: the backend fails CLOSED at import when TOKEN_ENCRYPTION_KEY is
# absent (M3, by design). Deploying without the secrets bound produces a revision
# that can never become ready. `ops/deploy.sh` binds whatever this script created.
#
# Secrets are read from backend/.env and never printed.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

PROJECT_ID="${GCP_PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"
REPO="${REPO:-kora}"
ENV_FILE="${ENV_FILE:-backend/.env}"

: "${PROJECT_ID:?no project — set GCP_PROJECT_ID or run: gcloud config set project <id>}"

log() { echo "▸ $*"; }
run() { if [ "$DRY" = "1" ]; then echo "   [dry-run] $*"; else "$@"; fi; }

log "project=$PROJECT_ID region=$REGION repo=$REPO"

# ------------------------------------------------------------------- 1. APIs --
log "enabling APIs (no-op if already enabled)"
run gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  iamcredentials.googleapis.com \
  aiplatform.googleapis.com \
  --project="$PROJECT_ID"

# --------------------------------------------------- 2. Artifact Registry ----
if gcloud artifacts repositories describe "$REPO" \
     --location="$REGION" --project="$PROJECT_ID" >/dev/null 2>&1; then
  log "artifact registry '$REPO' already exists"
else
  log "creating artifact registry '$REPO'"
  run gcloud artifacts repositories create "$REPO" \
    --repository-format=docker \
    --location="$REGION" \
    --description="Kora backend + frontend images" \
    --project="$PROJECT_ID"
fi

# --------------------------------------------------------- 3. Secrets --------
# The key list is shared with deploy.sh and cloudbuild.yaml — see ops/secrets.sh.
# shellcheck source=ops/secrets.sh
. "$ROOT/ops/secrets.sh"

if [ ! -f "$ENV_FILE" ]; then
  echo "!! $ENV_FILE not found — cannot populate secrets." >&2
  echo "   Create it from backend/.env.example, or set them by hand in Secret Manager." >&2
  exit 1
fi

# Read a value out of the env file without sourcing it (values may contain
# spaces, '#', quotes — sourcing would execute or mangle them).
read_env() {
  local key="$1" line
  # LAST match, not first: dotenv lets a later line override an earlier one,
  # so a duplicated key means the bottom one is what the app actually loads.
  # Reading the first would push a stale value to Secret Manager.
  line="$(grep -E "^[[:space:]]*${key}=" "$ENV_FILE" | tail -n1 || true)"
  [ -z "$line" ] && return 1
  line="${line#*=}"
  line="${line%$'\r'}"                       # strip CRLF from Windows-edited files
  line="${line#\"}"; line="${line%\"}"       # strip surrounding quotes
  line="${line#\'}"; line="${line%\'}"
  printf '%s' "$line"
}

CREATED=0; UPDATED=0; SKIPPED=0
for key in "${KORA_SECRET_KEYS[@]}"; do
  # Deployment-specific keys are handled below, from the live service URLs —
  # never copied from a laptop's .env.
  if kora_is_env_specific "$key"; then
    echo "   defer $key (deployment-specific; set from the service URLs below)"
    continue
  fi
  if ! value="$(read_env "$key")" || [ -z "$value" ]; then
    echo "   skip  $key (not set in $ENV_FILE)"
    SKIPPED=$((SKIPPED+1))
    continue
  fi

  if gcloud secrets describe "$key" --project="$PROJECT_ID" >/dev/null 2>&1; then
    # Only add a new version when the value actually changed — avoids version sprawl.
    current="$(gcloud secrets versions access latest --secret="$key" --project="$PROJECT_ID" 2>/dev/null || true)"
    if [ "$current" = "$value" ]; then
      echo "   same  $key"
      continue
    fi
    echo "   update $key (new version)"
    if [ "$DRY" != "1" ]; then
      printf '%s' "$value" | gcloud secrets versions add "$key" --data-file=- --project="$PROJECT_ID" >/dev/null
    fi
    UPDATED=$((UPDATED+1))
  else
    echo "   create $key"
    if [ "$DRY" != "1" ]; then
      printf '%s' "$value" | gcloud secrets create "$key" \
        --data-file=- --replication-policy=automatic --project="$PROJECT_ID" >/dev/null
    fi
    CREATED=$((CREATED+1))
  fi
done

log "secrets: $CREATED created, $UPDATED updated, $SKIPPED skipped"

# ────────────────────────────────── 3b. Deployment-specific redirect URIs ────
# These must match the deployed service exactly — the provider (Google, Notion,
# Stripe) compares the redirect_uri byte-for-byte against what is registered in
# its console. Derived from the live Cloud Run URLs so they cannot drift.
#
# TARGET_ENV picks which pair of services to point at; override BACKEND_URL /
# FRONTEND_URL to aim somewhere else entirely (a custom domain, say).
TARGET_ENV="${TARGET_ENV:-staging}"
case "$TARGET_ENV" in
  staging)    _be_svc="kora-backend-staging"; _fe_svc="kora-frontend-staging" ;;
  production) _be_svc="kora-backend";         _fe_svc="kora-frontend" ;;
  *) echo "!! TARGET_ENV must be staging|production" >&2; exit 2 ;;
esac

svc_url() {
  gcloud run services describe "$1" --region="$REGION" --project="$PROJECT_ID" \
    --format='value(status.url)' 2>/dev/null || true
}

BACKEND_URL="${BACKEND_URL:-$(svc_url "$_be_svc")}"
FRONTEND_URL="${FRONTEND_URL:-$(svc_url "$_fe_svc")}"

if [ -z "$BACKEND_URL" ]; then
  log "no $_be_svc service yet — skipping redirect URIs (re-run this script after the first deploy)"
else
  log "redirect URIs for ${TARGET_ENV}: backend=$BACKEND_URL frontend=${FRONTEND_URL:-<none>}"
  set_secret() {  # $1 key, $2 value
    local key="$1" value="$2" current
    [ -z "$value" ] && { echo "   skip  $key (no service URL)"; return; }
    if gcloud secrets describe "$key" --project="$PROJECT_ID" >/dev/null 2>&1; then
      current="$(gcloud secrets versions access latest --secret="$key" --project="$PROJECT_ID" 2>/dev/null || true)"
      [ "$current" = "$value" ] && { echo "   same  $key"; return; }
      echo "   update $key -> $value"
      [ "$DRY" != "1" ] && printf '%s' "$value" | gcloud secrets versions add "$key" --data-file=- --project="$PROJECT_ID" >/dev/null
    else
      echo "   create $key -> $value"
      [ "$DRY" != "1" ] && printf '%s' "$value" | gcloud secrets create "$key" --data-file=- --replication-policy=automatic --project="$PROJECT_ID" >/dev/null
    fi
  }

  set_secret GOOGLE_OAUTH_REDIRECT_URI "${BACKEND_URL}/api/auth/google/callback"
  set_secret NOTION_OAUTH_REDIRECT_URI "${BACKEND_URL}/api/notion/callback"
  [ -n "$FRONTEND_URL" ] && set_secret STRIPE_CONNECT_REDIRECT_URI "${FRONTEND_URL}/api/auth/stripe/callback"

  echo
  log "register these EXACT strings in each provider's console (byte-for-byte):"
  echo "     Google : ${BACKEND_URL}/api/auth/google/callback"
  echo "     Notion : ${BACKEND_URL}/api/notion/callback"
  [ -n "$FRONTEND_URL" ] && echo "     Stripe : ${FRONTEND_URL}/api/auth/stripe/callback"
fi

# ------------------------------------------------------------ 4. IAM ---------
# Cloud Run's default runtime identity is the compute default service account
# unless the service overrides it. It needs read access to the secrets above.
RUNTIME_SA="${RUNTIME_SA:-}"
if [ -z "$RUNTIME_SA" ]; then
  PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
  RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
fi
log "granting secretAccessor to $RUNTIME_SA"
run gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/secretmanager.secretAccessor" \
  --condition=None >/dev/null

# Signed URLs for PDF downloads. Cloud Run credentials are token-only, so the
# blob is signed through the IAM SignBlob API — which requires the runtime SA to
# be able to create tokens for ITSELF. Without this every invoice/report download
# 500s with "you need a private key to sign credentials".
log "granting serviceAccountTokenCreator on $RUNTIME_SA to itself (signed URLs)"
run gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_SA" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/iam.serviceAccountTokenCreator" \
  --project="$PROJECT_ID" >/dev/null

# Vertex AI (KORA_AI_BACKEND=vertex). The Gemini transport authenticates with
# Application Default Credentials — on Cloud Run that is this service account,
# and it holds no aiplatform role by default. Without this every agent call
# fails 403 while the service itself stays healthy, so the app looks up but
# every AI feature is dead.
log "granting aiplatform.user to $RUNTIME_SA (Vertex AI)"
run gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/aiplatform.user" \
  --condition=None >/dev/null

# Cloud Build deploys the services and calls `gcloud secrets describe` to work out
# which secrets exist (ops/secrets.sh), so the build identity needs Run admin, the
# ability to act as the runtime SA, registry write, and secret *metadata* read.
# Note secretmanager.viewer, not accessor: the build never reads a secret's value,
# it only asks whether one exists.
#
# Which identity runs a build changed: projects created after the 2024 default
# switch run builds as the COMPUTE default SA, older ones as the legacy
# <number>@cloudbuild SA. Granting both is harmless and avoids a confusing
# 403-on-source-upload depending on when the project was created.
PROJECT_NUMBER="${PROJECT_NUMBER:-$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')}"
BUILD_SAS=(
  "${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
  "${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"
)
# storage + logging are for the build itself: it reads the uploaded source tarball
# from the _cloudbuild bucket and streams logs. Without them the build fails before
# running a single step.
BUILD_ROLES=(
  roles/run.admin
  roles/iam.serviceAccountUser
  roles/artifactregistry.writer
  roles/secretmanager.viewer
  roles/storage.objectAdmin
  roles/logging.logWriter
)
for sa in "${BUILD_SAS[@]}"; do
  gcloud iam service-accounts describe "$sa" --project="$PROJECT_ID" >/dev/null 2>&1 || {
    log "skipping $sa (does not exist in this project)"; continue; }
  log "granting build roles to $sa"
  for role in "${BUILD_ROLES[@]}"; do
    run gcloud projects add-iam-policy-binding "$PROJECT_ID" \
      --member="serviceAccount:${sa}" \
      --role="$role" --condition=None >/dev/null
  done
done

echo
log "bootstrap complete."
log "  local docker:  bash ops/deploy.sh staging"
log "  cloud build:   gcloud builds submit --config cloudbuild.yaml --substitutions=..."
