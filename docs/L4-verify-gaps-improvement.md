# L4 VERIFY — `feature/gaps-improvement`

> Independent, adversarial review (maker≠checker). 4 parallel reviewers (security, correctness,
> tests/gates, data/compliance) + reviewer synthesis. Date 2026-07-31. Branch HEAD `5921f22`.
> Suite: **1 failed, 436 passed, 2 skipped** (mock mode; the 1 failure is env-gated, needs live creds).

## Verdict per milestone

| Milestone | L4 verdict | Basis |
|---|---|---|
| **M3** Token fail-closed | ✅ **APPROVE** | real subprocess exit-code test; no `StartupError` swallow anywhere |
| **M4** LLM injection | ✅ **APPROVE** | tests call real service fns, assert the pre-LLM sanitized payload |
| **M7a–e** Security controls | ✅ **APPROVE** (1 trap) | all 5 wired + tested; M7c fail-open trap (see S3) |
| **M1** Tenant isolation | ❌ **REJECT** | gate requires *zero* `.table()` bypass — **67 exist**; 2 exploitable cross-tenant writes still open; the only real-wrapper test is `skipif(True)` |
| **M9** GDPR/CCPA | ❌ **REJECT** | erasure returns `deleted:True` while leaving PII + live Google token; export omits the `users` row |
| **M8** Performance | ⚠️ **CHANGES REQUIRED** | async path still blocks the loop on DB I/O; in-memory jobs break multi-worker; no benchmark |
| **M11** Observability | ⚠️ **CHANGES REQUIRED** | PLAN says "pending", CURRENT says "approved"; the load-bearing concurrency test silently skips |
| **M2.3 / M5 / M6 / M10** | ⏳ **INCOMPLETE** | gates need a live step (branch-protection / migrated DB / Redis / pgvector) never run |

**Overall: NOT ready to call "enterprise-grade / done."** M3/M4/M7 are solid. M1 and M9 — the two milestones whose entire purpose is protecting tenant data — do not hold.

---

## CRITICAL / HIGH findings (all CONFIRMED)

> **C1 + C2 FIXED 2026-07-31** (working tree). Restored `.eq("user_id", user_id)` on both, plus
> hardened **4 more** id-scoped updates (kg_nodes/kg_edges/agent_memory/business_playbook-decay) and
> a **6th** the new lint caught (business_playbook save path). Added
> `tests/security/test_raw_table_tenant_lint.py` — an AST lint that fails CI on ANY
> `raw_table(...).delete()/.update()` chain missing an `.eq(…, user_id)` predicate — plus 2 behavioral
> tests. Both mutation-verified load-bearing. Suite 440 passed / 2 skipped; black + flake8 clean.
> **H1 (the 67 non-store bypass sites) remains OPEN** — the lint only covers `supabase_store.py`.

### C1 🔴 HIGH — Cross-tenant UPDATE, directly exploitable: `update_playbook_entry`  ✅ FIXED
`backends/supabase_store.py:759` — `raw_table("business_playbook").update(patch).eq("id", entry_id)`, **no `user_id`**. `entry_id` comes straight from `PATCH /api/playbook/{entry_id}` (`routers/playbook.py:54`). Any authenticated user overwrites another tenant's playbook entry (value/summary/confidence) by supplying its id. Sibling `delete_playbook_entry` uses the auto-scoping wrapper — this one was missed. **Same M1 regression class as the 9 fixed earlier; this is the 10th.** Fix: `.eq("user_id", user_id)`.

### C2 🟠 MEDIUM — Cross-tenant DELETE: `delete_client_view`
`backends/supabase_store.py:650` — `delete().eq("client_id", client_id)`, no `user_id`. Bounded (recomputable cache, UUID client_id) but a real hole and the **11th** dropped-filter function. Fix: `.eq("user_id", user_id)`.

> **Correction to the prior fix:** the M1 refactor dropped `.eq("user_id")` on **11** functions, not 9. The earlier pass fixed 9 and missed C1 + C2. Under the service-role key (RLS bypassed), the app-layer filter is the *only* guard — see M1-gate below.

> **H1 destructive-write subset FIXED 2026-07-31** (working tree). Audited all **20** destructive
> `.table().delete()/.update()` chains outside the store: 14 were already user-scoped, `auth_google`'s
> `users` update is correctly keyed by `user.id`, and **5** (`meeting_agent` ×4, `gmail_intel` ×1)
> updated `clients`/`meetings` by record-id with no tenant filter — hardened with `.eq("user_id", …)`
> (closes the foreign-`client_id` timestamp-bump the security reviewer flagged). Added
> `tests/security/test_table_tenant_lint.py` — an app-wide AST lint that fails CI on any destructive
> `.table()` write outside `backends/` lacking an `.eq(…, user_id | user.id)` predicate (with a
> `# tenant-lint: allow` escape for deliberate cross-tenant ops). Mutation-verified. Suite 444 passed.
> **Still partially open:** `.select()` **reads** via raw handles are not yet linted, and the broader
> "adopt `repo()` everywhere" refactor is deferred — but no unscoped destructive write can now land.

### H1 🔴 HIGH — M1 gate is unmet; the checkpoint overstates it  ⚠️ WRITES FIXED + ENFORCED
Gate: "zero direct `supabase.table()` outside the wrapper." Reality: **67 direct `.table()` calls across 16 files** (routers `auth_google`, `gmail_intel`, `meetings`, `drive_intel`; services `butler`, `calendar_*`, `gmail_*`, `google_auth`, `meeting_agent`, `memory_recall`, `supervisor`). `gmail_intel.py:123` even spins up a fresh service-role `create_client()` inline. `repo()` is adopted only inside `supabase_store`. Most manually append `.eq("user_id")`, but **nothing tests that**, and C1/C2 prove the pattern fails silently. `M1.md` claims "zero bypass … kept 9" — false. The one real-wrapper test (`test_tenant_isolation.py:373`) is `@skipif(True)` — permanently dead.

> **H2 + H3 + D1 FIXED 2026-07-31** (working tree). `DELETE /account/delete` now (1) actually calls
> Google's `/revoke` with the decrypted token *before* wiping the connection row; (2) returns an
> **honest** `deleted` flag — `false` with an `errors` list if the auth-identity delete fails (login
> email would survive), best-effort failures surfaced in `warnings`; (3) reports truthful per-step
> statuses (`revoked` / `cancelled` / `not_applicable: …` / `failed: …`). Export (H3) now returns the
> **full `users` record** (profile JSONB incl. tax_id/address, billing ids, google_email, consent) +
> butler/manager memory — not 5 flat fields. `deletion_log` (D1) persists the PII-free `side_effects`
> map (+ migration `2026-07-31_deletion_log_side_effects.sql`). New store fn `get_google_token`
> (both backends). +3 GDPR tests incl. a mutation-verified honest-`deleted`-flag test. Suite 442 passed.

### H2 🔴 HIGH — GDPR erasure tells the user "deleted" while leaving PII + a live token  ✅ FIXED
`routers/account.py:137` returns `{"deleted": True}` **unconditionally**; every side-effect and per-table delete is `try/except`-swallowed. Specifically:
- **Google token NOT revoked** — step 1 is a no-op string (`account.py:79`); a working `/revoke` exists at `auth_google.py:179` but is never called. KORA stays authorized on the user's Google account after "erasure."
- **`auth.users` identity (email + name) can survive** — the admin delete only runs if Supabase creds are set (`account.py:111`), else skipped with no error entry; `public.users`→`auth.users` cascade doesn't run that direction.
- **Stripe keeps billing** (`account.py:86` swallowed) and **GCS docs orphaned** (`account.py:99` swallowed) → post-deletion charges + residual document PII, with `deleted:True`.

### H3 🟠 HIGH — GDPR export omits the user's own profile
`_export_payload` (`account.py:33`) hand-copies 5 flat fields; `store.list_user_data` iterates `USER_DATA_TABLES`, which **excludes `users`**. So the `profile` JSONB (full BusinessProfile: personas/goals/financials), `butler_memory`, `manager_memory`, `tax_id`, plan/stripe ids are **never exported** — yet the whole `users` row *is* deleted. Deletable-but-not-exportable = incomplete portability.

### R1 🔴 HIGH — In-memory background jobs break under multiple workers  ✅ FIXED
> **FIXED 2026-07-31.** Import-job state now persists via the store (`import_jobs` table, migration
> `2026-07-31_import_jobs.sql`, RLS + FK cascade; both backends) instead of a per-process dict — status
> is shared across workers and survives restart. `import_jobs.py` rewritten to the store; +3 tests
> (completes / store-backed / tenant-scoped). Suite 447.

`services/import_jobs.py:12` (`_jobs` dict), `routers/bookkeeping.py`. Upload lands on worker A; frontend polls `GET /upload/{job_id}` → LB routes to worker B → `get_job` returns None → **permanent 404 for an import that actually succeeded**. All job state lost on restart.

### R2 🔴 HIGH — The "async" chat path still blocks the event loop on DB I/O  ✅ FIXED
> **FIXED 2026-07-31.** `chat_agentic_async` now wraps the blocking `store.get_user`, each tool
> `handler`, and `agent_logger.log_action` in `asyncio.to_thread`, so DB round-trips no longer stall
> the event loop. +1 mutation-verified test (asserts `get_user` runs off the main thread).

`services/supervisor.py:1281` `chat_agentic_async` awaits only the LLM call; `store.get_user`, every tool handler, the `list_*` Supabase round-trips, and `agent_logger.log_action` run **synchronously on the loop** (no `to_thread`). One slow Supabase call stalls every concurrent request on that worker — defeating M8.4's stated goal.

### R3 🔴 HIGH — pgvector recall silently returns empty (no JSONB fallback)
`memory_recall.py:220` — with `AGENT_MEMORY_VECTOR_BACKEND=pgvector`, a failed/empty `match_agent_memory` RPC (`supabase_store.py` swallows to `[]`) makes `recall()` return `[]` and never degrade to the retained JSONB+cosine path. Migration-not-applied, un-backfilled `embedding_vec`, or a dimension mismatch → agent reports "no past context" for every query though rows exist. Undocumented.

---

## MEDIUM findings (CONFIRMED unless noted)

- **S3 — Pub/Sub push fails OPEN on misconfig.** `pubsub_auth.py:22` returns `True` when `GMAIL_PUBSUB_AUDIENCE=""`. `GMAIL_PUBSUB_TOPIC` (enables push) and the audience are independent settings. Prod with push on but audience unset ⇒ **unauthenticated** POSTs to `/api/gmail/push` trigger forced syncs / mailbox-existence oracle.
- **R4 — Redis outage 500s every AI endpoint.** `utils/rate_limit.py` falls back to in-memory only when `REDIS_URL` is *unset*, never on a connection error; `pipe.execute()` is unguarded and the client has no `socket_timeout`. A Redis blip → unhandled 500 on `/upload`, `/follow-up`, `/manager/chat` for under-limit users (and can hang against a blackholed host).
- **R5 — `download_pdf` still generates synchronously** (`routers/invoices.py:235,259`), blocking the loop on first uncached download — defeats M8.3 for that path.
- **R6 — Background PDF errors swallowed** (`routers/invoices.py:31` `except: pass`); no job record, user never learns it failed.
- **R7 — Async LLM helpers lack tenacity retry** (`llm.py`); a transient 429 that one retry would absorb instead drops all tool-calling to a degraded generic answer (mitigated, not silent).
- **R8 — pgvector dimension mismatch silently breaks memory** — hardcoded `vector(1536)`; a non-1536 `EMBEDDING_MODEL` makes writes (swallowed) and reads (→`[]`) fail with no surfaced error.
- **D1 — `deletion_log` can't prove what happened** — stores counts only, not the `side_effects` map; combined with H2 a partial deletion leaves a clean-looking audit row.
- **D2 — AgentType enum drift** — schema CHECK allows `email_delivery`/`morning_digest`; the Pydantic `AgentType` enum (`models.py:38`) omits both, so `agent_logger` (which swallows validation errors) **silently drops those logs**. (`billing` fix *is* correct.)
- **D3 — `schema.sql` won't apply** — `ADD CONSTRAINT IF NOT EXISTS` (`schema.sql:495,628`) is invalid Postgres; `psql < schema.sql` aborts there.
- **D4 — `backend/migrations/` isn't self-contained** — base tables (`users`, `clients`, `invoices`, …) live only in `schema.sql`/older `docs/specs/migrations`; applying `backend/migrations/` alone on a fresh DB fails on missing parents.
- **D5 — `stripe_connections` has no `CREATE TABLE` anywhere** — the RLS migration only `ALTER`s it inside `IF EXISTS`; provisioning from schema/migrations leaves it absent → Stripe Connect writes fail, export/delete silently skip it.
- **D6 — `.env.example` omits many read vars** — `TOKEN_ENCRYPTION_KEY`, `STRIPE_WEBHOOK_SECRET`, `REDIS_URL`, `GMAIL_PUBSUB_*`, `AGENT_MEMORY_VECTOR_BACKEND`, etc. (silent misconfig, not hard boot fail).
- **M11 contradiction** — `PLAN.md:248` marks M11 `[~]` "L4 pending"; `CURRENT.md` marks it `[x]` "APPROVED". The gate's core proof — `test_concurrent_requests_do_not_leak` (`tests/observability/test_request_context.py:87`) — is an undecorated `async def` that pytest **silently skips** (STRICT asyncio mode). The one test that would catch a request-context leak never runs.

---

## LOW findings

- OAuth `state` nonce is generated but never verified (`oauth_state.py:37`) → replayable within the 600 s TTL (low impact; Google's `code` is single-use).
- `/docs` CSP nonce is dead code (`security_headers.py:19`) — FastAPI's default Swagger HTML carries no matching `nonce=`; the control adds no real value as wired.
- Meeting `client_id` not ownership-checked on `/quick-note` (`routers/meetings.py:154`) → cross-tenant `last_activity_at` bump + client-name leak into the AI summary.
- Unsafe defaults: `CRON_SECRET="dev-cron-secret-change-me"`, `ALLOW_DEMO_USER=True` (`config.py`).
- **Junk file `backend/2.118.0`** committed in M1 (`988d39c`) — captured `pip` stderr; leaks another contributor's local path. Delete + gitignore.
- `tests/test_rate_limit.py` can't be collected (top-level `import redis` with the pkg absent kills the whole module — even its in-memory tests). `tests/test_perf_m8.py::test_supabase_client_is_singleton` fails without live creds.

---

## Recommended fix order

1. **C1 (+ C2)** — close the two remaining cross-tenant writes; then add an AST/lint gate that fails CI on any `raw_table(...).update()/.delete()` without a following `.eq("user_id")`, and on new `.table(` outside the store. (Turns H1 from "trust the reviewer" into "enforced.")
2. **H2/H3** — make GDPR deletion honest: actually call Google `/revoke`, don't return `deleted:True` when any step is skipped/failed, persist `side_effects` in `deletion_log`; add `users` to the export.
3. **R1/R2** — move job state to a shared store (or document single-worker); offload sync I/O on the async path (`to_thread`) or make the endpoint sync.
4. **R3/R8** — pgvector recall must fall back to JSONB on empty/error; validate embedding dim vs `vector(1536)` at startup.
5. **S3/R4** — require `GMAIL_PUBSUB_AUDIENCE` whenever the topic is set; guard the Redis call and fall back (or fail cleanly) on connection error.
6. **M11** — add `@pytest.mark.asyncio` (or `asyncio_mode=auto`) so the concurrency test runs; reconcile PLAN vs CURRENT.
7. **D3/D4/D5** — make schema/migrations provisionable from scratch; add `CREATE TABLE stripe_connections`.
8. Housekeeping: enum drift (D2), `.env.example` (D6), delete `backend/2.118.0`, fix `test_rate_limit` import guard.
