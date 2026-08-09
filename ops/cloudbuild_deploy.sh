#!/usr/bin/env bash
#
# Deploy via Cloud Build — the path that works without a local Docker daemon.
#
#   bash ops/cloudbuild_deploy.sh staging
#   bash ops/cloudbuild_deploy.sh production
#
# `ops/deploy.sh` builds images locally and needs Docker Desktop running. This
# wrapper hands the build to Cloud Build instead, so the only local requirement
# is gcloud. Same cloudbuild.yaml, same secret bindings, same service naming.
#
# NEXT_PUBLIC_* values are read from frontend/.env.local because Next inlines them
# into the client bundle at BUILD time — they are not runtime env vars, so changing
# one means rebuilding the image (DEPLOY.md).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENVIRONMENT="${1:?usage: cloudbuild_deploy.sh <staging|production>}"
case "$ENVIRONMENT" in
  staging)    BACKEND_SVC="kora-backend-staging";  FRONTEND_SVC="kora-frontend-staging" ;;
  production) BACKEND_SVC="kora-backend";          FRONTEND_SVC="kora-frontend" ;;
  *) echo "unknown environment: $ENVIRONMENT (want staging|production)" >&2; exit 2 ;;
esac

PROJECT_ID="${GCP_PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"
: "${PROJECT_ID:?set GCP_PROJECT_ID or run: gcloud config set project <id>}"

TAG="${TAG:-$(git rev-parse --short HEAD 2>/dev/null || echo manual)}"
FE_ENV="${FE_ENV:-frontend/.env.local}"

# Read one key out of an env file without sourcing it — values contain '=', '#'
# and quotes that a `source` would execute or mangle.
read_env() {
  local key="$1" file="$2" line
  # LAST match — dotenv gives a later duplicate precedence (see gcp_bootstrap.sh).
  line="$(grep -E "^[[:space:]]*${key}=" "$file" 2>/dev/null | tail -n1 || true)"
  [ -z "$line" ] && return 1
  line="${line#*=}"; line="${line%$'\r'}"
  line="${line#\"}"; line="${line%\"}"
  line="${line#\'}"; line="${line%\'}"
  printf '%s' "$line"
}

SUPABASE_URL="$(read_env NEXT_PUBLIC_SUPABASE_URL "$FE_ENV" || true)"
SUPABASE_ANON="$(read_env NEXT_PUBLIC_SUPABASE_ANON_KEY "$FE_ENV" || true)"
STRIPE_STARTER="$(read_env NEXT_PUBLIC_STRIPE_STARTER_PRICE_ID "$FE_ENV" || true)"
STRIPE_PRO="$(read_env NEXT_PUBLIC_STRIPE_PRO_PRICE_ID "$FE_ENV" || true)"

if [ -z "$SUPABASE_URL" ] || [ -z "$SUPABASE_ANON" ]; then
  echo "!! NEXT_PUBLIC_SUPABASE_URL / _ANON_KEY missing from $FE_ENV." >&2
  echo "   The frontend would build with no Supabase config and every login would fail." >&2
  exit 1
fi

# A comma is the substitution separator, so a value containing one would silently
# corrupt the whole flag. Fail loudly instead.
for v in "$SUPABASE_URL" "$SUPABASE_ANON" "$STRIPE_STARTER" "$STRIPE_PRO"; do
  case "$v" in *,*) echo "!! a NEXT_PUBLIC_* value contains a comma; pass it via --substitutions manually" >&2; exit 1 ;; esac
done

# FRONTEND_ORIGIN is a chicken-and-egg: the backend needs the frontend's URL for
# CORS, but the frontend URL only exists after it deploys. Reuse the existing one
# if the service is already up; otherwise deploy once and re-run (the script
# prints the follow-up command).
FRONTEND_ORIGIN="${FRONTEND_ORIGIN:-$(gcloud run services describe "$FRONTEND_SVC" \
  --region="$REGION" --project="$PROJECT_ID" --format='value(status.url)' 2>/dev/null || true)}"

echo "▸ project=$PROJECT_ID region=$REGION env=$ENVIRONMENT tag=$TAG"
echo "▸ services: $BACKEND_SVC / $FRONTEND_SVC"
echo "▸ FRONTEND_ORIGIN=${FRONTEND_ORIGIN:-<unknown — first deploy; re-run after to fix CORS>}"

gcloud builds submit --config cloudbuild.yaml --project="$PROJECT_ID" \
  --substitutions="_REGION=${REGION},_TAG=${TAG},_ENVIRONMENT=${ENVIRONMENT},_BACKEND_SERVICE=${BACKEND_SVC},_FRONTEND_SERVICE=${FRONTEND_SVC},_FRONTEND_ORIGIN=${FRONTEND_ORIGIN},_NEXT_PUBLIC_SUPABASE_URL=${SUPABASE_URL},_NEXT_PUBLIC_SUPABASE_ANON_KEY=${SUPABASE_ANON},_NEXT_PUBLIC_STRIPE_STARTER_PRICE_ID=${STRIPE_STARTER},_NEXT_PUBLIC_STRIPE_PRO_PRICE_ID=${STRIPE_PRO}"

BE_URL="$(gcloud run services describe "$BACKEND_SVC"  --region="$REGION" --project="$PROJECT_ID" --format='value(status.url)')"
FE_URL="$(gcloud run services describe "$FRONTEND_SVC" --region="$REGION" --project="$PROJECT_ID" --format='value(status.url)')"

echo
echo "▸ backend  : $BE_URL"
echo "▸ frontend : $FE_URL"

if [ "$FRONTEND_ORIGIN" != "$FE_URL" ]; then
  echo
  echo "!! FRONTEND_ORIGIN was '${FRONTEND_ORIGIN:-empty}' but the frontend is at $FE_URL."
  echo "   The backend will reject the browser's requests until CORS matches. Re-run:"
  echo "     FRONTEND_ORIGIN=$FE_URL bash ops/cloudbuild_deploy.sh $ENVIRONMENT"
fi

echo
echo "▸ now verify:  bash ops/uat.sh smoke --target $BE_URL --frontend $FE_URL"
