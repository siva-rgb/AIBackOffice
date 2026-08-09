#!/usr/bin/env bash
#
# Kora UAT gate runner — the automated half of docs/uat/UAT_PLAN.md.
#
#   bash ops/uat.sh all                      G0..G3, the pre-deploy gate
#   bash ops/uat.sh preflight                G0 only
#   bash ops/uat.sh backend                  G1 only
#   bash ops/uat.sh frontend                 G2 only
#   bash ops/uat.sh e2e                      G3 only
#   bash ops/uat.sh smoke --target <url>     G5, against a deployed environment
#
# smoke also accepts --frontend <url> to check the deployed UI alongside the API.
#
# Exit codes:  0 = every gate passed   1 = a gate failed   2 = bad usage
#
# A failing gate stops the run — you do not deploy on a red gate (UAT_PLAN §1).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MODE="${1:-all}"; shift || true

TARGET=""       # backend/API base url for smoke
FRONTEND=""     # frontend base url for smoke
while [ $# -gt 0 ]; do
  case "$1" in
    --target)   TARGET="${2:?--target needs a url}"; shift 2 ;;
    --frontend) FRONTEND="${2:?--frontend needs a url}"; shift 2 ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
done

# ---------------------------------------------------------------- reporting --
PASS=0; FAIL=0; SKIP=0
declare -a FAILED_CHECKS=()

c_g=$'\033[32m'; c_r=$'\033[31m'; c_y=$'\033[33m'; c_b=$'\033[1m'; c_0=$'\033[0m'

gate()  { printf '\n%s══ %s %s\n' "$c_b" "$*" "$c_0"; }
ok()    { PASS=$((PASS+1)); printf '  %sPASS%s  %s\n' "$c_g" "$c_0" "$*"; }
bad()   { FAIL=$((FAIL+1)); FAILED_CHECKS+=("$*"); printf '  %sFAIL%s  %s\n' "$c_r" "$c_0" "$*"; }
skip()  { SKIP=$((SKIP+1)); printf '  %sSKIP%s  %s\n' "$c_y" "$c_0" "$*"; }

# check <label> <command...>  — runs quietly, reports pass/fail, keeps going.
check() {
  local label="$1"; shift
  local out
  if out="$("$@" 2>&1)"; then
    ok "$label"
  else
    bad "$label"
    printf '%s\n' "$out" | tail -20 | sed 's/^/        /'
  fi
}

# Python interpreter for the backend venv (Windows layout first, then POSIX).
pyexe() {
  if   [ -x "$ROOT/backend/venv/Scripts/python.exe" ]; then echo "$ROOT/backend/venv/Scripts/python.exe"
  elif [ -x "$ROOT/backend/venv/bin/python"         ]; then echo "$ROOT/backend/venv/bin/python"
  else echo python
  fi
}

# Run python from backend/ — pydantic resolves `.env` relative to the working
# directory, and the container's WORKDIR is the backend root. Running from the
# repo root would silently test a different configuration than we ship.
py() { ( cd "$ROOT/backend" && "$(pyexe)" "$@" ); }

have() { command -v "$1" >/dev/null 2>&1; }

# ------------------------------------------------------------------ G0 pre --
g0_preflight() {
  gate "G0 · preflight"

  check "python available"           py --version
  check "pytest importable"          py -m pytest --version
  check "node available"             node --version
  check "backend app imports"        py -c "import app.main"

  if [ -d frontend/node_modules ]; then ok "frontend deps installed"
  else bad "frontend deps installed (run: npm --prefix frontend ci)"; fi

  # Migrations present — MEM-*/GRAPH-*/TASK-*/STORY-* silently misbehave without them.
  local n
  n="$(ls backend/migrations/*.sql 2>/dev/null | wc -l | tr -d ' ')"
  if [ "$n" -gt 0 ]; then ok "migrations present ($n files) — confirm they are APPLIED to the target db"
  else bad "no migration files found under backend/migrations/"; fi

  # Fail-closed startup contract (M3): no key ⇒ refuse to start, not a silent boot.
  # settings already merged backend/.env, so blank the setting itself — otherwise a
  # local .env would mask the regression this check exists to catch.
  local out
  out="$(py -c "
import os
try:
    from app.services import token_encryption as t
except Exception:
    print('FAILCLOSED'); raise SystemExit(0)
os.environ.pop('TOKEN_ENCRYPTION_KEY', None)
t.settings.TOKEN_ENCRYPTION_KEY = ''
try:
    t.load_key(); print('BOOTED')
except Exception:
    print('FAILCLOSED')
" 2>&1 | tail -1)"
  case "$out" in
    FAILCLOSED) ok "token encryption fails closed without a key (M3)" ;;
    BOOTED)     bad "token encryption booted WITHOUT a key — M3 regression" ;;
    *)          skip "token encryption fail-closed probe inconclusive ($out)" ;;
  esac
}

# -------------------------------------------------------------- G1 backend --
g1_backend() {
  gate "G1 · backend — unit · integration · security · perf"

  check "pytest: security suite"      py -m pytest tests/security -q -p no:warnings
  check "pytest: integration suite"   py -m pytest tests/integration -q -p no:warnings
  check "pytest: observability suite" py -m pytest tests/observability -q -p no:warnings
  check "pytest: perf suite"          py -m pytest tests/perf -q -p no:warnings
  check "pytest: full suite"          py -m pytest -q -p no:warnings

  if py -m flake8 --version >/dev/null 2>&1; then
    check "flake8 clean" py -m flake8 app
  else skip "flake8 not installed"; fi

  if py -m black --version >/dev/null 2>&1; then
    # --line-length must match .github/workflows/test.yml (no pyproject.toml pins it).
    check "black --check clean" py -m black --check --line-length=155 app
  else skip "black not installed"; fi
}

# ------------------------------------------------------------- G2 frontend --
g2_frontend() {
  gate "G2 · frontend — unit · lint · production build"

  check "jest unit tests" npm --prefix frontend test --silent -- --ci
  check "next lint"       npm --prefix frontend run lint --silent

  # The build must succeed with the same NEXT_PUBLIC_* shape the image bakes in.
  check "next build" env \
    NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-http://localhost:8000}" \
    NEXT_PUBLIC_SUPABASE_URL="${NEXT_PUBLIC_SUPABASE_URL:-http://localhost:54321}" \
    NEXT_PUBLIC_SUPABASE_ANON_KEY="${NEXT_PUBLIC_SUPABASE_ANON_KEY:-uat-anon-key}" \
    npm --prefix frontend run build --silent
}

# ------------------------------------------------------------------ G3 e2e --
g3_e2e() {
  gate "G3 · end-to-end user journeys (playwright)"

  if ! ( cd frontend && npx playwright --version >/dev/null 2>&1 ); then
    skip "playwright not installed (npm --prefix frontend ci)"
    return
  fi

  local out
  if out="$( ( cd frontend && npx playwright test ) 2>&1 )"; then
    ok "playwright user journeys"
    return
  fi

  # Browser binaries download separately from the npm package. Without them every
  # test fails with a launch error that reads like a product regression — say so.
  if printf '%s' "$out" | grep -q "Executable doesn't exist"; then
    bad "playwright browsers not installed — run: npm --prefix frontend exec playwright install chromium"
    return
  fi
  bad "playwright user journeys"
  printf '%s\n' "$out" | tail -25 | sed 's/^/        /'
}

# ----------------------------------------------------------------- G4 auth --
# Authenticated assertions against a deployed environment (ops/uat_auth.py).
# Everything here needs a real session, so it cannot live in the anonymous smoke
# gate. Credentials come from the environment — never from the repo.
g4_auth() {
  gate "G4-auto · authenticated UAT${TARGET:+ — $TARGET}"

  if [ -z "$TARGET" ]; then
    echo "  usage: bash ops/uat.sh auth --target <backend-url>" >&2
    exit 2
  fi
  if [ -z "${UAT_A_EMAIL:-}" ] || [ -z "${UAT_A_PASSWORD:-}" ]; then
    skip "authenticated UAT" "set UAT_A_EMAIL/UAT_A_PASSWORD (and UAT_B_* for isolation + gating cases)"
    return
  fi

  # Runs its own reporting, so surface it directly rather than through check().
  if py "$ROOT/ops/uat_auth.py" --target "$TARGET"; then
    ok "authenticated UAT suite"
  else
    bad "authenticated UAT suite (see cases above)"
  fi
}

# ---------------------------------------------------------------- G5 smoke --
# Post-deploy verification against a real URL. Read-only: it never mutates data.
g5_smoke() {
  gate "G5 · post-deploy smoke${TARGET:+ — $TARGET}"

  if [ -z "$TARGET" ]; then
    echo "  usage: bash ops/uat.sh smoke --target https://kora-backend-xxx.run.app [--frontend https://...]" >&2
    exit 2
  fi
  have curl || { bad "curl not available"; return; }

  local body code hdrs
  # Cloud Run scales to zero, and a cold start can exceed the per-check timeout —
  # which would fail the gate for a reason that has nothing to do with the build.
  # Warm the instance first, with a generous budget, and don't score this attempt.
  printf '  ....  warming %s (cold starts can take ~30s)\n' "$TARGET"
  curl -s -o /dev/null --max-time 120 "$TARGET/health" || true
  # -- OBS-05: health is up and does not leak config secrets ------------------
  body="$(curl -fsS --max-time 20 "$TARGET/health" 2>&1)"
  if [ $? -eq 0 ] && printf '%s' "$body" | grep -q '"status"[[:space:]]*:[[:space:]]*"ok"'; then
    ok "health returns status ok"
    printf '        %s\n' "$body"
  else
    bad "health endpoint (got: ${body:0:200})"
  fi

  if printf '%s' "$body" | grep -Eqi 'secret|service_role|api_key|password|eyJ[A-Za-z0-9_-]{10}'; then
    bad "OBS-05 health response looks like it leaks a secret"
  else
    ok "OBS-05 health leaks no secret material"
  fi

  # -- AUTH-04: protected endpoints reject anonymous callers -----------------
  local ep
  for ep in /api/invoices /api/clients /api/tasks /api/bookkeeping/transactions /api/stories; do
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$TARGET$ep")"
    case "$code" in
      401|403) ok "AUTH-04 $ep rejects anonymous ($code)" ;;
      200)     bad "AUTH-04 $ep returned 200 to an ANONYMOUS caller — S1 auth bypass" ;;
      *)       skip "AUTH-04 $ep returned $code" ;;
    esac
  done

  # -- AUTH-08: security headers --------------------------------------------
  hdrs="$(curl -sSI --max-time 20 "$TARGET/health" 2>/dev/null | tr 'A-Z' 'a-z')"
  local h
  for h in x-content-type-options x-frame-options strict-transport-security content-security-policy; do
    if printf '%s' "$hdrs" | grep -q "^$h:"; then ok "AUTH-08 header $h present"
    else bad "AUTH-08 header $h missing"; fi
  done

  # -- stack traces must never reach the client (OBS-06) ---------------------
  body="$(curl -sS --max-time 20 "$TARGET/api/definitely-not-a-real-route" 2>&1)"
  if printf '%s' "$body" | grep -Eqi 'traceback|File "/|line [0-9]+, in '; then
    bad "OBS-06 a stack trace leaked to the client"
  else
    ok "OBS-06 no stack trace leaked on an unknown route"
  fi

  # -- frontend reachability + API wiring ------------------------------------
  if [ -n "$FRONTEND" ]; then
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 "$FRONTEND/")"
    [ "$code" = "200" ] && ok "frontend / returns 200" || bad "frontend / returned $code"

    for ep in /login /signup /privacy /terms; do
      code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 "$FRONTEND$ep")"
      [ "$code" = "200" ] && ok "public page $ep returns 200" || bad "public page $ep returned $code"
    done

    # AUTH-04 at the edge: middleware must bounce anonymous users off /dashboard.
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 "$FRONTEND/dashboard")"
    case "$code" in
      200) bad "AUTH-04 /dashboard served 200 to an anonymous browser — middleware gate broken" ;;
      3*|401|403|307|302) ok "AUTH-04 /dashboard redirects anonymous users ($code)" ;;
      *) skip "/dashboard returned $code" ;;
    esac

    # CORS: the deployed frontend origin must be allowed by the backend.
    hdrs="$(curl -sS -o /dev/null -D - --max-time 20 -H "Origin: $FRONTEND" "$TARGET/health" 2>/dev/null | tr 'A-Z' 'a-z')"
    if printf '%s' "$hdrs" | grep -q 'access-control-allow-origin'; then
      ok "CORS allows the deployed frontend origin"
    else
      bad "CORS: backend did not allow origin $FRONTEND — set FRONTEND_ORIGIN and redeploy"
    fi
  else
    skip "frontend checks (pass --frontend <url> to enable)"
  fi
}

# ------------------------------------------------------------------- driver --
case "$MODE" in
  preflight) g0_preflight ;;
  backend)   g1_backend ;;
  frontend)  g2_frontend ;;
  e2e)       g3_e2e ;;
  auth)      g4_auth ;;
  smoke)     g5_smoke ;;
  verify)    g5_smoke; g4_auth ;;
  all)       g0_preflight; [ $FAIL -eq 0 ] && g1_backend
             [ $FAIL -eq 0 ] && g2_frontend
             [ $FAIL -eq 0 ] && g3_e2e ;;
  *) echo "usage: bash ops/uat.sh <all|preflight|backend|frontend|e2e|auth|smoke|verify> [--target url] [--frontend url]" >&2; exit 2 ;;
esac

printf '\n%s── UAT summary ──%s\n' "$c_b" "$c_0"
printf '  passed %s  failed %s  skipped %s\n' "$PASS" "$FAIL" "$SKIP"
if [ "$FAIL" -gt 0 ]; then
  printf '\n%sfailed checks:%s\n' "$c_r" "$c_0"
  printf '  · %s\n' "${FAILED_CHECKS[@]}"
  printf '\n%sGATE RED — do not deploy.%s See docs/uat/UAT_PLAN.md\n' "$c_r" "$c_0"
  exit 1
fi
printf '\n%sGATE GREEN.%s Automated gates pass — now run the manual matrix (UAT_PLAN §4) before promoting.\n' "$c_g" "$c_0"
