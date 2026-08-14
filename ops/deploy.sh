#!/usr/bin/env bash
#
# Kora deploy driver for the GitHub Actions CI/CD pipeline (M16.3 + M16.4).
#
# One script, four modes — invoked as `bash ops/deploy.sh <mode>`:
#   staging       Build + push both images, deploy to the *-staging Cloud Run
#                 services at 100% traffic. Runs automatically on merge to main.
#   prod-canary   Build + push, deploy a new PRODUCTION revision with NO live
#                 traffic under the `canary` tag, then shift CANARY_PERCENT of
#                 traffic to it. The rest stays on the current stable revision.
#   prod-promote  Blue/green cutover: route 100% of production traffic to the
#                 newest (canary) revision. It becomes the new stable.
#   prod-rollback Instant rollback: set the canary tag to 0% — 100% returns to
#                 the prior stable revision (which never stopped serving).
#
# Backend-first ordering is preserved (Next inlines NEXT_PUBLIC_API_URL at build
# time, so the frontend image must bake the backend URL). See DEPLOY.md.
#
# Required env (set by the workflow, scoped per GitHub Environment):
#   GCP_PROJECT_ID, REGION, SHA
#   FRONTEND_ORIGIN, NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY,
#   NEXT_PUBLIC_STRIPE_STARTER_PRICE_ID, NEXT_PUBLIC_STRIPE_PRO_PRICE_ID
#   CANARY_PERCENT (default 10)
set -euo pipefail

MODE="${1:?usage: deploy.sh <staging|prod-canary|prod-promote|prod-rollback>}"

: "${GCP_PROJECT_ID:?}"
REGION="${REGION:-us-central1}"
REPO="${REPO:-kora}"
SHA="${SHA:-manual}"
CANARY_PERCENT="${CANARY_PERCENT:-10}"

REGISTRY="${REGION}-docker.pkg.dev/${GCP_PROJECT_ID}/${REPO}"

# Environment → service names. Staging and production are fully isolated
# services (a *-staging suffix), so a bad staging deploy can never touch prod.
case "$MODE" in
  staging)
    ENVIRONMENT="staging"
    BACKEND_SVC="kora-backend-staging"
    FRONTEND_SVC="kora-frontend-staging"
    ;;
  prod-canary | prod-promote | prod-rollback)
    ENVIRONMENT="production"
    BACKEND_SVC="kora-backend"
    FRONTEND_SVC="kora-frontend"
    ;;
  *)
    echo "unknown mode: $MODE" >&2
    exit 2
    ;;
esac

BACKEND_IMG="${REGISTRY}/${BACKEND_SVC}:${SHA}"
FRONTEND_IMG="${REGISTRY}/${FRONTEND_SVC}:${SHA}"

log() { echo "▸ $*"; }

# Runtime secrets, created in Secret Manager by `ops/gcp_bootstrap.sh` and bound
# here as env vars of the same name. The list lives in ops/secrets.sh so this
# script, the bootstrap, and cloudbuild.yaml can never drift apart.
# shellcheck source=ops/secrets.sh
. "$(dirname "${BASH_SOURCE[0]}")/secrets.sh"

build_push_backend() {
  log "build backend → ${BACKEND_IMG}"
  docker build -t "${BACKEND_IMG}" ./backend
  docker push "${BACKEND_IMG}"
}

# $1... extra `gcloud run deploy` flags (e.g. --no-traffic --tag=canary)
deploy_backend() {
  log "deploy backend service=${BACKEND_SVC} ($*)"
  gcloud run deploy "${BACKEND_SVC}" \
    --image="${BACKEND_IMG}" \
    --region="${REGION}" \
    --platform=managed \
    --allow-unauthenticated \
    --no-cpu-throttling \
    --min-instances="${MIN_INSTANCES:-1}" \
    --set-env-vars="^@^ENVIRONMENT=${ENVIRONMENT}@ALLOW_DEMO_USER=false@KORA_DATA_BACKEND=supabase@FRONTEND_ORIGIN=${FRONTEND_ORIGIN:-}@KORA_AI_BACKEND=${KORA_AI_BACKEND:-vertex}@MODEL_NAME=${MODEL_NAME:-gemini-2.5-flash}@GOOGLE_CLOUD_PROJECT_ID=${GCP_PROJECT_ID}@GOOGLE_CLOUD_LOCATION=${REGION}@PROTECTED_TENANT_IDS=${PROTECTED_TENANT_IDS:-}@SEED_SAMPLE_DATA_ON_SIGNUP=${SEED_SAMPLE_DATA_ON_SIGNUP:-false}@SCHEDULER_USER_ID=${SCHEDULER_USER_ID:-}" \
    "$(kora_secret_flag "${GCP_PROJECT_ID}")" \
    "$@"
}

# Prints the URL the frontend should call: always the STABLE service URL.
#
# This used to return the canary-tagged revision URL during a canary deploy, so
# that canary frontend traffic would hit canary backend traffic. That reasoning
# is right about intent and wrong about lifetime. NEXT_PUBLIC_API_URL is inlined
# into the frontend bundle at BUILD time, and the canary image is the very image
# `prod-promote` later routes 100% of traffic to — so promoting shipped a
# production frontend permanently hard-wired to a tagged revision URL. Every CI
# run then re-pointed the live site at whatever the tag meant that day, which is
# what kept having to be untangled by hand after each deploy.
#
# Pointing at the stable URL loses nothing: the backend service itself is split
# `canary=${CANARY_PERCENT}`, so that share of requests to the stable URL are
# already served by the canary revision. Canary backend code still gets real
# traffic — through the split that exists for exactly this, rather than through
# a hostname frozen into a bundle.
backend_url() {
  gcloud run services describe "${BACKEND_SVC}" --region="${REGION}" \
    --format='value(status.url)'
}

build_push_frontend() {
  local api_url="$1"
  # FRONTEND_ORIGIN is a comma-separated CORS allow-list: one deployment answers
  # on both its legacy *.a.run.app name and its newer *.run.app name, and the
  # browser sends whichever the user typed. NEXT_PUBLIC_APP_URL is a single URL
  # the app builds links from, so it takes the FIRST entry — the canonical
  # public address — rather than the whole list, which would bake
  # "https://a,https://b" into every generated link.
  local app_url="${FRONTEND_ORIGIN%%,*}"
  log "build frontend → ${FRONTEND_IMG} (NEXT_PUBLIC_API_URL=${api_url}, NEXT_PUBLIC_APP_URL=${app_url})"
  docker build \
    --build-arg NEXT_PUBLIC_API_URL="${api_url}" \
    --build-arg NEXT_PUBLIC_APP_URL="${app_url}" \
    --build-arg NEXT_PUBLIC_SUPABASE_URL="${NEXT_PUBLIC_SUPABASE_URL:-}" \
    --build-arg NEXT_PUBLIC_SUPABASE_ANON_KEY="${NEXT_PUBLIC_SUPABASE_ANON_KEY:-}" \
    --build-arg NEXT_PUBLIC_STRIPE_STARTER_PRICE_ID="${NEXT_PUBLIC_STRIPE_STARTER_PRICE_ID:-}" \
    --build-arg NEXT_PUBLIC_STRIPE_PRO_PRICE_ID="${NEXT_PUBLIC_STRIPE_PRO_PRICE_ID:-}" \
    -t "${FRONTEND_IMG}" \
    ./frontend
  docker push "${FRONTEND_IMG}"
}

# $1... extra `gcloud run deploy` flags
deploy_frontend() {
  log "deploy frontend service=${FRONTEND_SVC} ($*)"
  gcloud run deploy "${FRONTEND_SVC}" \
    --image="${FRONTEND_IMG}" \
    --region="${REGION}" \
    --platform=managed \
    --allow-unauthenticated \
    "$@"
}

shift_traffic() {   # $1 service, $2... update-traffic flags
  local svc="$1"; shift
  gcloud run services update-traffic "${svc}" --region="${REGION}" "$@"
}

case "$MODE" in
  staging)
    build_push_backend
    deploy_backend
    api="$(backend_url)"
    build_push_frontend "${api}"
    deploy_frontend
    log "staging live: $(gcloud run services describe "${FRONTEND_SVC}" --region="${REGION}" --format='value(status.url)')"
    ;;

  prod-canary)
    # New revision, zero live traffic, reachable only at its canary tag URL.
    build_push_backend
    deploy_backend --no-traffic --tag=canary
    # Stable URL, not the canary tag — see backend_url(). The canary revision
    # still gets its share via the backend traffic split below.
    api="$(backend_url)"
    build_push_frontend "${api}"
    deploy_frontend --no-traffic --tag=canary
    # Send a slice of real traffic to the canary; remainder stays on stable.
    shift_traffic "${BACKEND_SVC}" --to-tags="canary=${CANARY_PERCENT}"
    shift_traffic "${FRONTEND_SVC}" --to-tags="canary=${CANARY_PERCENT}"
    log "canary at ${CANARY_PERCENT}% — verify, then run the workflow with action=promote (or rollback)"
    ;;

  prod-promote)
    # Blue/green cutover: 100% to the newest (canary) revision.
    shift_traffic "${BACKEND_SVC}" --to-latest
    shift_traffic "${FRONTEND_SVC}" --to-latest
    log "promoted: 100% traffic on the latest revision"
    ;;

  prod-rollback)
    # Canary never took the stable revision offline, so zeroing it is a
    # complete, instant rollback.
    shift_traffic "${BACKEND_SVC}" --to-tags="canary=0"
    shift_traffic "${FRONTEND_SVC}" --to-tags="canary=0"
    log "rolled back: canary drained to 0%, 100% on prior stable"
    ;;
esac
