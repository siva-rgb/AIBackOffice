#!/usr/bin/env bash
#
# Single source of truth for Kora's runtime secrets. Sourced by:
#   ops/gcp_bootstrap.sh  — creates one Secret Manager secret per key
#   ops/deploy.sh         — binds them onto the Cloud Run backend service
#   cloudbuild.yaml       — same, for the manual one-shot build
#
# Not executable on its own.
#
# Only *secret* values belong here. Plain config (ENVIRONMENT, MODEL_NAME,
# KORA_DATA_BACKEND, FRONTEND_ORIGIN, GOOGLE_CLOUD_*) is passed as --set-env-vars
# by the caller — there is no reason to pay Secret Manager for non-secrets.
#
# GOOGLE_APPLICATION_CREDENTIALS is deliberately absent: on Cloud Run the service
# authenticates as its attached service account, so a key file would be both
# redundant and one more credential that can leak.

KORA_SECRET_KEYS=(
  TOKEN_ENCRYPTION_KEY
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY
  MODEL_API_KEY
  BASE_URL
  STRIPE_SECRET_KEY
  STRIPE_WEBHOOK_SECRET
  STRIPE_PUBLISHABLE_KEY
  STRIPE_CONNECT_CLIENT_ID
  STRIPE_CONNECT_REDIRECT_URI
  STRIPE_STARTER_PRICE_ID
  STRIPE_PRO_PRICE_ID
  STRIPE_CONTRACT_PRICE_ID
  GOOGLE_OAUTH_CLIENT_ID
  GOOGLE_OAUTH_CLIENT_SECRET
  GOOGLE_OAUTH_REDIRECT_URI
  NOTION_API_KEY
  NOTION_OAUTH_CLIENT_ID
  NOTION_OAUTH_CLIENT_SECRET
  NOTION_OAUTH_REDIRECT_URI
  NOTION_PARENT_PAGE_ID
  RESEND_API_KEY
  FROM_EMAIL
  CRON_SECRET
  SENTRY_DSN
  CLOUD_STORAGE_BUCKET
  DOCUMENT_AI_PROCESSOR_ID
)

# Keys whose correct value DEPENDS ON THE DEPLOYMENT, not on the developer's
# machine. `backend/.env` holds `http://localhost:8000/...` for these, which is
# right for local dev and guarantees a redirect_uri mismatch anywhere else — so
# gcp_bootstrap.sh must never sync them from .env. It derives them from the
# deployed service URLs instead.
#
# Caveat worth knowing before production goes up: Secret Manager holds ONE value
# per key, so staging and production cannot both be served by these as-is. When a
# second environment appears, split them (e.g. GOOGLE_OAUTH_REDIRECT_URI_STAGING)
# or move them to plain per-service env vars, which is what they really are.
KORA_ENV_SPECIFIC_KEYS=(
  GOOGLE_OAUTH_REDIRECT_URI
  NOTION_OAUTH_REDIRECT_URI
  STRIPE_CONNECT_REDIRECT_URI
)

kora_is_env_specific() {
  local needle="$1" k
  for k in "${KORA_ENV_SPECIFIC_KEYS[@]}"; do
    [ "$k" = "$needle" ] && return 0
  done
  return 1
}

# kora_secret_flag <project_id>
#
# Prints a `--set-secrets=K=K:latest,...` flag covering only the secrets that
# actually exist in the project. A project with no Notion or Stripe configured
# still deploys; it just gets fewer bindings.
#
# TOKEN_ENCRYPTION_KEY is the exception — the backend refuses to start without it
# (M3 fail-closed), so its absence is a hard error here. Failing at the CLI is far
# cheaper to diagnose than a Cloud Run revision that never becomes ready.
kora_secret_flag() {
  local project="${1:?kora_secret_flag needs a project id}"
  local pairs="" k
  for k in "${KORA_SECRET_KEYS[@]}"; do
    if gcloud secrets describe "$k" --project="$project" >/dev/null 2>&1; then
      pairs="${pairs:+$pairs,}${k}=${k}:latest"
    elif [ "$k" = "TOKEN_ENCRYPTION_KEY" ]; then
      echo "FATAL: secret TOKEN_ENCRYPTION_KEY does not exist in ${project}." >&2
      echo "       The backend fails closed without it — the revision would never" >&2
      echo "       become ready. Run: bash ops/gcp_bootstrap.sh" >&2
      return 1
    fi
  done
  printf -- '--set-secrets=%s' "$pairs"
}
