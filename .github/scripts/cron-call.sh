#!/usr/bin/env bash
#
# Fire one scheduled agent endpoint on the deployed backend.
#
#   usage: cron-call.sh /api/butler/run
#   env:   KORA_API_URL, KORA_CRON_SECRET  (repository secrets)
#
# This exists because the nine jobs in cron.yml had the same three faults, and
# fixing them in one place is the only way they stay fixed.
#
#   1. Neither secret was configured, so the URL expanded to bare "/api/..." and
#      curl exited 3 (malformed URL) with nothing in the log explaining why.
#      GitHub redacts a real secret as ***, so a BLANK expansion means the secret
#      does not exist — the check below says that outright instead of leaving it
#      to be inferred from an exit code.
#
#   2. `curl -X POST` with no body sends no Content-Length, and Cloud Run answers
#      411 Length Required before the request ever reaches the app. The empty
#      JSON body is what makes these POSTs legal, not decoration.
#
#   3. On a non-200 the job printed only the status code. The response body is
#      where the actual reason lives, so it is captured and echoed on failure.

set -euo pipefail

PATH_SUFFIX="${1:?usage: cron-call.sh /api/<endpoint>}"

missing=""
[ -n "${KORA_API_URL:-}" ]     || missing="$missing KORA_API_URL"
[ -n "${KORA_CRON_SECRET:-}" ] || missing="$missing KORA_CRON_SECRET"
if [ -n "$missing" ]; then
  echo "::error::Missing repository secret(s):$missing"
  echo "Set them under Settings ▸ Secrets and variables ▸ Actions ▸ Repository secrets."
  echo "These are REPOSITORY secrets — this workflow declares no 'environment:',"
  echo "so secrets scoped to the staging/production environments are not visible here."
  exit 1
fi

# Strip a trailing slash so "https://host/" + "/api/x" doesn't become "//api/x".
BASE="${KORA_API_URL%/}"
URL="$BASE$PATH_SUFFIX"

BODY_FILE="$(mktemp)"
trap 'rm -f "$BODY_FILE"' EXIT

# --max-time: the briefing and supervisor passes call an LLM and are genuinely
# slow. Long enough for a real run, bounded so a hung backend fails the job
# rather than burning the runner's full timeout.
STATUS=$(curl -sS -o "$BODY_FILE" -w "%{http_code}" -X POST "$URL" \
  -H "x-cron-secret: $KORA_CRON_SECRET" \
  -H "Content-Type: application/json" \
  -d '{}' \
  --max-time 600 \
  --retry 2 --retry-connrefused --retry-delay 10)

echo "POST $PATH_SUFFIX -> HTTP $STATUS"

if [ "$STATUS" != "200" ]; then
  echo "::error::$PATH_SUFFIX returned HTTP $STATUS"
  echo "--- response body ---"
  head -c 2000 "$BODY_FILE"
  echo
  exit 1
fi

head -c 500 "$BODY_FILE"
echo
