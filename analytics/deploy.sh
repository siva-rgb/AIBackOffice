#!/usr/bin/env bash
#
# Deploy kora-analytics to Cloud Run.
#
#   bash analytics/deploy.sh
#
# Independent of ops/deploy.sh on purpose. This service has its own image, its
# own lifecycle and its own failure domain — a bad analytics deploy must not be
# able to touch the product, and the surest way to guarantee that is for the two
# never to share a deploy path.
#
# Builds via Cloud Build rather than a local `docker build`, so it needs no
# Docker daemon on the machine running it.
set -euo pipefail

PROJECT="${GCP_PROJECT_ID:-auto-business-prod}"
REGION="${REGION:-us-central1}"
REPO="${REPO:-kora}"
SERVICE="kora-analytics"
TAG="${TAG:-$(git rev-parse --short HEAD 2>/dev/null || echo manual)}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${SERVICE}:${TAG}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "▸ build ${IMAGE}"
gcloud builds submit "${HERE}" \
  --tag="${IMAGE}" \
  --project="${PROJECT}" \
  --quiet

echo "▸ deploy ${SERVICE}"
# SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY come from Secret Manager, where the
# backend's bootstrap already created them. The key is bound, never printed and
# never baked into the image.
#
# --allow-unauthenticated: no login, by request. The mitigation lives in the
# app — email addresses are masked unless ANALYTICS_SHOW_EMAILS is set, and no
# route takes input that reaches a query.
gcloud run deploy "${SERVICE}" \
  --image="${IMAGE}" \
  --project="${PROJECT}" \
  --region="${REGION}" \
  --platform=managed \
  --allow-unauthenticated \
  --min-instances=0 \
  --max-instances=3 \
  --memory=512Mi \
  --set-env-vars="^@^ANALYTICS_PRODUCT_URL=${ANALYTICS_PRODUCT_URL:-}@ANALYTICS_SHOW_EMAILS=${ANALYTICS_SHOW_EMAILS:-false}@ANALYTICS_TEST_ACCOUNTS=${ANALYTICS_TEST_ACCOUNTS:-demo@kora.app,tester@kora.app,uat-tenant-b@kora.app,pandasivananda0@gmail.com}" \
  --set-secrets="SUPABASE_URL=SUPABASE_URL:latest,SUPABASE_SERVICE_ROLE_KEY=SUPABASE_SERVICE_ROLE_KEY:latest" \
  --quiet

URL="$(gcloud run services describe "${SERVICE}" --project="${PROJECT}" --region="${REGION}" --format='value(status.url)')"
echo "▸ live: ${URL}"
