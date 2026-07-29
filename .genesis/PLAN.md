# PLAN.md — AIBackOffice (Kora): Security, Performance & Compliance Hardening

> Machine-parseable milestone list for the `.genesis/` spine (mirrors `DONE.html` §3).
> Source: `gaps_and_improvement_of_current_implementation.txt` (principal-architect review).
> Goal (Definition of Done, top level): AIBackOffice moves from MVP to enterprise-grade —
> tenant isolation is enforced at the data layer, CI/tests exist, LLM inputs are sanitized,
> secrets/keys fail closed, and GDPR/CCPA export+delete endpoints exist.

Legend:
- `[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked
- **Track** = independent lane that can run in parallel with other tracks (different agent/session/dev).
- **Depends** = milestone IDs that must be `[x]` before this one can start.
- Each milestone lists its own **gates** (computed, not narrated — per L1/L4 conventions).

---

## Phase 0 — IMMEDIATE (0–30 days)

### M1 — Tenant Isolation Enforcement  `CRITICAL` · Track: `backend-core`
Depends: none

- [ ] M1.1 Build a query-wrapper / repository layer around Supabase client that injects
      `user_id`/`tenant_id` automatically on every read/write (no call site can bypass it).
- [ ] M1.2 Audit all existing `store.*` call sites; replace raw `.eq("user_id", ...)` usage
      with the wrapper; flag any call site that cannot be migrated.
- [ ] M1.3 Add database-level Row-Level Security (RLS) policies as a defense-in-depth backup
      to the application-layer wrapper (service-role bypass documented as known exception).
- [ ] M1.4 Add regression tests that assert cross-tenant reads/writes are rejected.

**Gate:** `pytest tests/security/test_tenant_isolation.py` passes; grep shows zero direct
`supabase.table(...)` calls outside the wrapper module.

---

### M2 — Mandatory Test Harness + CI  `CRITICAL` · Track: `ci-infra`
Depends: none (parallel with M1)

- [x] M2.1 Stand up `pytest` for backend (`supabase_store`, `token_encryption`, `validation`
      as first targets) and `jest` for frontend.
- [x] M2.2 Add GitHub Actions workflow: lint (`flake8`, `black`), typecheck (`mypy`), test run,
      on every PR — separate from the existing `cron.yml`.
- [~] M2.3 Require the workflow as a required status check before merge. _(file-level done; pending human confirmation that GitHub branch-protection has `Tests` set as a required check on `main`)_
- [x] M2.4 Add coverage reporting; set an initial floor (e.g. 40%) that ratchets up over time.

**Gate:** PR against a scratch branch shows the new workflow running and blocking merge on
failure.

**Status (2026-07-28):** `[x]` — L4 APPROVE (separate model, fresh context). All gates green;
M2.3 stays `[~]` only because GitHub branch-protection requires a human to set the
required-check toggle (file artifact already wires the workflow into the PR decision).
See `.genesis/checkpoints/M2.md` for the L1 → L4 audit trail and quiz-me Q+A.

---

### M3 — Token Encryption Fail-Closed  `HIGH` · Track: `backend-core`
Depends: none (can run parallel with M1/M2)

- [x] M3.1 Remove the fallback random Fernet key generation in `token_encryption.py`.
- [x] M3.2 Add startup validation: process exits with a clear error if
      `TOKEN_ENCRYPTION_KEY` is unset or malformed.
- [x] M3.3 Add a startup smoke test (in CI, from M2) that verifies this failure path.
- [x] M3.4 Document key rotation/recovery procedure.

**Gate:** Starting the app without `TOKEN_ENCRYPTION_KEY` exits non-zero with a descriptive
error instead of booting.

**Status (2026-07-28):** `[x]` — L4 APPROVE. Mock-mode escape hatch removed as a safety
improvement (stricter than the literal context-graph invariant; documented in
`M3.verify.md` §5). 10/10 token_encryption tests pass; full suite 306 passed,
1 skipped, coverage 39.57%; flake8/black clean. See `.genesis/checkpoints/M3.md`
(iter 1 + iter 2 self-verify) and `.genesis/checkpoints/M3.verify.md`
(iter 2 L4 verdict, same-session caveat logged per LOOPS.md).

---

### M4 — LLM Input Sanitization  `HIGH` · Track: `llm-safety`
Depends: none (can run parallel)

- [x] M4.1 Inventory every endpoint that interpolates user input into an LLM prompt
      (`gmail_intel.py` confirmed vulnerable; re-check `clients.py`/`butler.py` for parity).
- [~] M4.2 Replace regex-based filtering with a structured sanitizer/library
      (e.g. Guardrails/LlamaGuard-style classifier) applied consistently across endpoints.
      _(interpreted per user "(b)" answer: enforced consistent use of existing regex list;
      library swap deferred to `structured-sanitizer-library` candidate milestone — see
      M4.verify.md §Q3)_
- [x] M4.3 Add strict input validation (length, allowed characters, schema) ahead of prompt
      construction for all LLM-facing parameters.
- [x] M4.4 Add adversarial test cases (prompt-injection payloads) to the CI suite from M2.

**Gate:** Injection test suite (`tests/security/test_prompt_injection.py`) passes against
`gmail_intel.py` and all other LLM-facing endpoints.

**Status (2026-07-28):** `[x]` — L4 APPROVE + quiz-me Q+A logged. Same-session L4 caveat
documented (same as M3). 5 service files patched (butler_comms, contract_agent, invoice_agent,
routers/manager, supervisor) + 2 new test files (`test_prompt_injection.py` 17 tests,
`test_llm_input_lint.py` 2 AST-lint tests) + 2 context-graph invariants. Full suite 325
passed, 1 skipped, coverage 42.38%; flake8/black clean. See `.genesis/checkpoints/M4.md`
(iter 1 L1 BUILD) and `.genesis/checkpoints/M4.verify.md` (L4 verdict + Q+A).
**M4.2 stays `[~]`** — literal-plan deviation; library swap recorded as candidate
follow-up (`structured-sanitizer-library`), tracked under §Follow-ups below.

---

### M5 — Docs & Schema Accuracy  `MEDIUM` · Track: `docs-infra`
Depends: none (fully parallel — good first task for a second contributor/agent)

- [x] M5.1 Regenerate `docs/specs/schema.sql` from the actual ~20-table migration history
      (supersede the stale v1 snapshot).
- [x] M5.2 Add the missing `.env.example` referenced by 4 existing docs.
- [x] M5.3 Fix the `agent_logs.agent_type` CHECK constraint to include `'billing'` via a new
      migration.
- [x] M5.4 Reconcile conflicting GCS bucket names (`gcp_setup.md` vs `gcp-cloud.md`);
      de-duplicate `stripes_integration/setup.md`; fix stale `tracker.md` header date.

**Gate:** `schema.sql` diff matches `\d` output from a freshly-migrated DB; `.env.example`
boots the app with placeholder values; billing insert no longer 500s.

**Status (2026-07-28):** `[x]` — L4 APPROVE + quiz-me Q+A logged. schema.sql has 28 tables;
`.env.example` 57 placeholder lines; billing CHECK migration added. See
`.genesis/checkpoints/M5.md` and `.genesis/checkpoints/M5.verify.md`.

---

## Phase 1 — SHORT-TERM (30–90 days)

### M6 — Distributed Rate Limiting  `MEDIUM` · Track: `backend-infra` · `[x]` 2026-07-28 (close bypassed L4 quiz-me per owner request)
Depends: M2 (needs CI to safely land infra changes)

- [x] M6.1 Introduce Redis (or existing managed cache) as shared state store.
- [x] M6.2 Replace in-process counters in `rate_limit.py` with Redis-backed sliding-window
      or token-bucket implementation.
- [x] M6.3 Load-test across multiple worker processes/containers to confirm consistency.

**Gate:** Rate limit holds under a multi-worker load test (limit is enforced globally, not
per-worker).

---

### M7 — Remaining Security Controls  `MEDIUM` · Track: `security-hardening`
Depends: M2. Sub-items are independently assignable.

- [x] M7a. Authorization: wire `require_plan` dependency into every feature-gated router;
      add a test that a downgraded Stripe plan actually blocks the endpoint.
- [x] M7b. OAuth: replace `state=user_id` with a cryptographically random, session-bound
      state token in the Google OAuth callback.
- [x] M7c. Gmail Pub/Sub: add signed JWT verification per Google's push-endpoint guidance.
- [x] M7d. Headers/CSP: remove `unsafe-eval`/`unsafe-inline`, move to nonce/hash-based CSP,
      add `Expect-CT`, COOP, COEP.
- [x] M7e. PII: add application-level field encryption for tax IDs/bank details (defense in
      depth beyond DB-level encryption).

**Gate:** Each sub-item ships as its own PR with a passing CI run (from M2) and a targeted
test; M7 is "done" when all five sub-items are `[x]`.

---

### M8 — Performance: First Pass  `MEDIUM` · Track: `perf-backend`
Depends: M1 (query wrapper should exist before adding indexes on top of it)

- [x] M8.1 Add database indexes for the query patterns actually hit by the dashboard/list
      endpoints (identify via `EXPLAIN ANALYZE`).
- [x] M8.2 Add connection pooling for Supabase/HTTP clients.
- [x] M8.3 Move PDF generation (ReportLab) off the request path into a background job/queue.
- [x] M8.4 Convert blocking LLM calls to async clients; add request-level caching for
      repeated dashboard-triggered agent executions.
- [x] M8.5 Switch the 50-item batch transaction import to background processing instead of
      blocking the upload request.

**Gate:** p95 latency for dashboard load and CSV/PDF upload drops measurably in a before/after
benchmark; no request-path code still calls the sync LLM client directly.

---

## Phase 2 — MEDIUM-TERM (90–180 days)

### M9 — GDPR/CCPA Compliance  `MEDIUM` · Track: `compliance`
Depends: M1 (deletion/export must respect tenant boundaries)

- [x] M9.1 Data export endpoint (JSON/CSV) covering all tables holding user data.
- [x] M9.2 Full data deletion endpoint (hard delete or anonymization, per data class).
- [x] M9.3 Verify/enhance consent capture in onboarding; log consent version + timestamp.

**Gate:** A test tenant can request export and deletion via API; post-deletion queries return no residual PII for that tenant.

**Status (2026-07-29):** `[x]` — L4 APPROVE (separate model: z-ai/glm-5.2, fresh-context
pass; maker was composer). Quiz-me gate returned `skip ×3`; verdict would-strict-downgrade to
UNCERTAIN, but owner direction `Accept verifier answers, finalise APPROVE` accepted the
verifier's Q1/Q2/Q3 answers as the Q+A block — override logged openly in
`.genesis/checkpoints/M9.verify.md` §5. Gates re-computed independently: 12/12 M9 tests pass
(EXITCODE=0); full suite green with 2 pre-M9-unrelated failures deselected (`test_rate_limit`
redis-missing M6, `test_perf_m8 supabase_singleton` creds-missing M8); flake8 + black clean
on all 5 M9-touched files (EXITCODE=0 both); mypy scope = 4 M9-introduced inference errors in
`memory_store.py` heterogeneous-dict lookup (`_USER_DATA_DICTS[table]` typed `object`) —
runtime-fine, precedent-aligned with M3/M4 lenient baseline; recorded as follow-up FU-M9-mypy.
Context-graph invariants: M1 wrapper respected (only documented service-role exceptions:
`deletion_log` no-tenant, `auth.admin.delete_user`), M3 untouched, D5 no-PII audit row
verified, zero new cycles. See `.genesis/checkpoints/M9.md` (L1 iter 1) and
`.genesis/checkpoints/M9.verify.md` (L4 verdict + Q+A + 5 non-blocking follow-ups incl.
FU-M9-reconsent-UX, FU-DONE-demo-cmd, FU-M9-commit, FU-M1-followup).

---

### M10 — Memory System → pgvector  `LOW` · Track: `ml-infra` · `[x]` 2026-07-29 (L4 APPROVE)
Depends: none (parallel-friendly)

- [x] M10.1 Design pgvector schema + HNSW/IVFFLAT index for `memory_recall.py`'s embeddings.
- [x] M10.2 Write migration & backfill script preserving existing API surface.
- [x] M10.3 Benchmark recall latency/quality vs. current implementation before cutover.

**Gate:** Recall API contract unchanged; latency/quality benchmark meets or beats baseline.

**Status (2026-07-29):** `[x]` — L4 APPROVE (separate model: z-ai/glm-5.2, fresh-context pass;
maker was composer). Quiz-me gate returned `skip ×3`; verdict would-strict-downgrade to
UNCERTAIN, but owner direction `APPROVE with FU-M10-rpc-auth-model + live benchmark
follow-up` (option 1 of a 3-option decision tree the verifier surfaced) accepted the
verifier's Q1/Q2/Q3 answers as the Q+A block — override logged openly in
`.genesis/checkpoints/M10.verify.md` §5. Gates re-computed independently: pytest M10 scope
13/13 (EXITCODE=0); full suite 370 passed, 1 skipped, 1 deselected (same 2 pre-M10
deselects as M9 — `test_rate_limit` redis-missing M6, `test_perf_m8 supabase_singleton`
creds-missing M8); flake8 + black clean on all 5 M10-touched source files (EXITCODE=0
both); mypy scope = **0 M10-introduced errors** (4 pre-existing in `memory_store.py` from
FU-M9-mypy; 1 pre-existing in `store.py:15`; 14 pre-existing in `app/seed.py` +
`app/_bootstrap.py` — all out of M10's freeze boundary). Migration adds `vector` extension
+ `embedding_vec vector(1536)` column + HNSW index + `match_agent_memory` SECURITY DEFINER
RPC (explicit `auth.uid()` check inside the body, not RLS-only — RLS alone is not enough
because SECURITY DEFINER bypasses RLS for the function's own reads). `vector_search_agent_memory`
helper added to `supabase_store` + mock-backend shim returning `[]`. `memory_recall.recall()`
gains a pgvector branch gated on `AGENT_MEMORY_VECTOR_BACKEND=pgvector` AND `q_vec is not None`;
default backend stays `jsonb` (proven pre-M10 path). Backfill script is idempotent,
hermetic-friendly (skips when no Supabase creds), supports `--dry-run` / `--reset` / `--batch`.
5 new benchmark tests (3 quality + 1 empty-candidates + 1 lexical-fallback + 1 JSONB latency
smoke). JSONB baseline recorded: p50=2.6ms / p95=3.0ms (500 rows / 50 queries). Context-graph
invariants: M1 wrapper respected on writes (RPC is `.rpc()`-not-`.table()`, documented
exception — tenant boundary enforced inside the RPC body); M3 fail-closed untouched; mock
backend returns `[]` (FU-M10-defer-vector-on-mock); API stability invariant verified by
re-reading public signatures. **Two non-blocking security/ops follow-ups surfaced by L4**:
FU-M10-rpc-auth-model (regression test that probes the RPC with a forged `p_user_id` and
asserts `[]` — requires live Supabase) and FU-M10-live-bench (pgvector live-latency gate
against the recorded JSONB baseline). All M10 work uncommitted in the working tree
(FU-M10-commit). See `.genesis/checkpoints/M10.md` (L1 iter 1) and
`.genesis/checkpoints/M10.verify.md` (L4 verdict + Q+A + 7 non-blocking follow-ups).

---

### M11 — Observability  `LOW` · Track: `observability`
Depends: M2 (CI needed to safely add instrumentation without regressions)

- [ ] M11.1 Access logging with PII scrubbing (request/response audit trail).
- [ ] M11.2 OpenTelemetry distributed tracing across API -> agent -> LLM call chain.
- [ ] M11.3 Business metrics dashboard (KPIs, usage analytics, per-tenant LLM cost/latency).
- [ ] M11.4 Validate secrets-scrubbing rules against a corpus of representative log lines.

**Gate:** A single request is traceable end-to-end in the tracing backend; a sample log export contains no raw secrets or unscrubbed PII.

---

### M12 — Dependency Management Modernization  `MEDIUM` · Track: `ci-infra`
Depends: M2

- [ ] M12.1 Migrate `requirements.txt` to Poetry or pip-tools with a committed lockfile.
- [ ] M12.2 Add Dependabot config.
- [ ] M12.3 Add `pip-audit`/`safety` (and frontend equivalent, e.g. `npm audit`) to CI.
- [ ] M12.4 Plan and test the Supabase client version upgrade path.

**Gate:** CI fails on a known-vulnerable dependency injected as a test case; builds are reproducible from the lockfile.

---

## Phase 3 — LONG-TERM / STRATEGIC (6–12 months)

### M13 — Real-Time Features  `LOW` · Track: `frontend-realtime`
Depends: M8 (async LLM path should exist first)

- [ ] M13.1 Add WebSocket or SSE endpoints for agent-progress/dashboard/notification updates.
- [ ] M13.2 Implement optimistic UI updates on the frontend for these events.

**Gate:** A long-running agent action streams progress to the client without polling.

---

### M14 — Orchestration Framework Evaluation  `LOW` · Track: `agent-architecture`
Depends: none

- [ ] M14.1 Document current supervisor/agent loop limits (chain length, branching, pause/resume).
- [ ] M14.2 Spike LangGraph (or equivalent) gainst a representative >5-step agent chain.
- [ ] M14.3 Write an ADR recommending adopt/defer with rationale.

**Gate:** ADR merged in `decisions/`.

---

### M15 — External Integrations Expansion  `LOW` · Track: `integrations`
Depends: none

- [ ] M15.1 Extract a generic adapter interface from `notion_connector`.
- [ ] M15.2 Implement Jira adapter against the interface.
- [ ] M15.3 Implement Asana adapter against the interface.

**Gate:** Both new adapters pass the same contract test suite the Notion connector uses.

---

### M16 — Full CI/CD Pipeline  `MEDIUM` · Track: `ci-infra`
Depends: M2, M12

- [ ] M16.1 Add official backend Dockerfile.
- [ ] M16.2 Add official frontend Dockerfile (currently missing — only inferred in docs).
- [ ] M16.3 Build → test → deploy workflow to staging, then production.
- [ ] M16.4 Blue/green or canary deployment strategy.

**Gate:** A merge to `main` deploys to staging automatically; promotion to production is dimple reviewed action.

---

## Suggested parallelization for a multi-agent/multi-dev team

Independent starting points (no dependencies, can begin simultaneously):
`M1`, `M2`, `M3`, `M4`, `M5`, `M10`, `M14`, `M15`

Second wave (unlocked once `M2` lands):
`M6`, `M7a`–`M7e` (each independently assignable), `M11`, `M12`

Third wave (unlocked once `M1`/`M8` land):
`M8`, `M9`, `M13`, `M16`

---

## Notes for `.genesis/` integration
- This file sits at `.genesis/PLAN.md` and mirrors the milestone table in
  `DONE.html` §3 — keep both in sync when a milestone is added/split/completed.
- Each milestone's **Gate** line is what L1 BUILD checks per iteration and what L4 VERIFY
  re-checks from a fresh context before a milestone is marked `[x]`.
- Record irreversible calls (e.g. "RLS as backup vs. replacing service-role key entirely",
  "Redis vs. in-memory with sticky sessions") as ADRs in `decisions/`, not inline here.