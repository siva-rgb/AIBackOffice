# `feature/gaps-improvement` — Code Review & Follow-up Gap List

> Analysis of `feature/gaps-improvement` vs `feature/project-management`.
> Date: 2026-07-31. Reviewer: automated deep-dive (3 parallel code audits + before/after diff).
> Branch HEAD: `5921f22`. Scope: 180 files, +25,572 / −5,100.

## TL;DR

`feature/project-management` = **what KORA does** (agent-maintained client/project intelligence).
`feature/gaps-improvement` = the same codebase hardened to **enterprise-grade**: milestones
**M1–M11 built**, M12–M16 planned. It is a *superset* — all PM feature services (pm_agent,
rollup, butler_comms, notion_ingest) are present and were hardened, not removed.

**Verification state (local):**
- Backend: `428 passed, 2 skipped`; 2 env-gated tests can't run locally (`test_rate_limit` needs
  Redis, `test_perf_m8::test_supabase_client_is_singleton` needs live Supabase). Matches the
  branch's own checkpoints.
- Frontend (after `npm install`): `tsc --noEmit` 0 errors; `jest` 5/5.

**One CRITICAL regression found** — see §1. Everything else is either a documented follow-up or a
minor hardening nit.

---

## 1. 🔴 CRITICAL — M1 refactor dropped `user_id` on destructive store writes  ✅ FIXED 2026-07-31

> **Status: fixed on `feature/gaps-improvement` (uncommitted working tree).** All 8 functions below
> now carry `.eq("user_id", user_id)`. New regression suite
> `backend/tests/security/test_tenant_isolation_destructive_writes.py` (8 tests) injects a recording
> fake Supabase client and asserts every destructive write is user-scoped; verified load-bearing by
> mutation (reverting a fix turns it red). Suite: 436 passed / 2 skipped; black + flake8 clean.
> A **9th** function — `delete_agent_memory(kind=...)`, the Notion-disconnect purge — was found to
> have the same defect during the fix and is included below.


The M1 tenant-isolation work rewrote `supabase_store.py` from `_sb.table(...)` to
`repo(user_id).raw_table(...)`. **`raw_table()` is the escape hatch — it does NOT auto-scope by
`user_id`** (unlike the wrapper's `.select()/.update()/.delete()`). In six functions the manual
`.eq("user_id", user_id)` that existed on `feature/project-management` was **not carried over**.
Because the store runs under the **service-role key (RLS bypassed)**, these become table-wide
operations across every tenant.

| Function | Line | `project-management` | `gaps-improvement` | Blast radius |
|---|---|---|---|---|
| `update_stripe_connection` | 808 | `.update(u).eq("user_id")` | `.update(u)` | overwrites **all** tenants' Stripe rows |
| `delete_stripe_connection` | 813 | `.delete().eq("user_id")` | `.delete()` | deletes **all** tenants' Stripe rows |
| `update_notion_connection` | 834 | `.update(u).eq("user_id")` | `.update(u)` | overwrites **all** tenants' Notion rows |
| `delete_notion_connection` | 839 | `.delete().eq("user_id")` | `.delete()` | deletes **all** tenants' Notion rows |
| `delete_kg_for_user` | 960–961 | `.delete().eq("user_id")` ×2 | `.delete()` ×2 | wipes **all** tenants' `kg_edges` + `kg_nodes` |
| `delete_agent_memory_for_user` | 1071 | `.delete().eq("user_id")` | `.delete()` | wipes **all** tenants' `agent_memory` |
| `delete_agent_memory(kind=…)` | 1106 | base query `.eq("user_id")` | *(no user filter)* | Notion-disconnect purge wipes **all** tenants' `notion` memories |

**Why it's severe, not theoretical:**
- `delete_kg_for_user` and `delete_agent_memory_for_user` are invoked by **M9's GDPR
  account-deletion** (`routers/account.py DELETE /api/account/delete` → `store.delete_user_data`).
  So **one user exercising their right-to-erasure destroys every other user's knowledge graph and
  semantic memory.**
- `delete_stripe_connection` / `delete_notion_connection` fire on integration **disconnect** — any
  user disconnecting Stripe/Notion disconnects everyone.
- These only affect the Supabase (production) backend; mock mode is unaffected, which is why the
  test suite is green — no test exercises the multi-tenant destructive path against a real DB.

**Fix (one line each):** append `.eq("user_id", user_id)` to each `raw_table(...)` chain, e.g.
```python
def delete_agent_memory_for_user(user_id: str) -> None:
    repo(user_id).raw_table("agent_memory").delete().eq("user_id", user_id).execute()
```
**Regression test to add:** seed two tenants, delete one, assert the other's rows survive
(the M1 gate `test_tenant_isolation.py` should cover destructive writes, not just reads).

### 1b. 🟠 MEDIUM — same class, narrower blast radius
| Function | Line | Change | Note |
|---|---|---|---|
| `delete_stories_for_task` | 511 | dropped `.eq("user_id")`, kept `.eq("task_id")` | Task-id-scoped so not table-wide, but no longer verifies the task belongs to the caller. Restore the `user_id` filter. |

---

## 2. 🟠 M1 gate only partially enforced ("single choke point" doesn't hold)

The `repo()` wrapper is real, but **~72 direct `.table()` calls across 18 files bypass it**,
relying on manual `.eq("user_id")`:

```
services:  meeting_agent(13) drive_intel(7) google_auth(6) gmail_intel(6) calendar_intel(3)
           butler(3) calendar_agent(2) gmail_agent(2) butler_comms(1) memory_recall(1) supervisor(1)
routers:   meetings(8) auth_google(7) gmail_intel(3) drive_intel(2)
workers:   butler_google_sync(2)   scripts: backfill_agent_memory_vectors(3) seed_supabase(2)
```
- `repo()` is adopted **only inside `supabase_store.py`** + one test. No service/router imports it.
- Some of these are legitimately cross-tenant (`butler_google_sync` iterates all users;
  `seed_supabase`), but most should route through the wrapper.
- The narrow literal invariant ("no `_sb.table(` outside the store") *does* hold — but that's not
  the same as "no query can bypass tenant scoping."
- Already tracked by the branch as `FU-M1-followup`. §1 is the urgent subset of this.

---

## 3. 🟡 Per-milestone minor caveats (non-blocking)

| # | Milestone | Caveat | Where |
|---|---|---|---|
| 3.1 | M8 perf | **Background jobs are in-memory** (`_jobs` module dict) — single-worker, lost on restart, not shared across containers. Needs a durable queue for multi-worker prod. | `services/import_jobs.py` |
| 3.2 | M8 perf | **Async LLM path has no retry** — sync `chat()` has tenacity `@retry` on 429/5xx; `achat()`/`achat_messages()` do not (and `max_retries=0`). | `services/llm.py` |
| 3.3 | M8 perf | `download_pdf` still generates **synchronously** as a fallback when `pdf_path` missing — create/regenerate are off-path, this one isn't. | `routers/invoices.py:236` |
| 3.4 | M10 pgvector | If `AGENT_MEMORY_VECTOR_BACKEND=pgvector` is set **in mock mode**, `recall()` short-circuits to `[]` instead of the documented Python-cosine fallback. Harmless under the `jsonb` default. | `memory_recall.py:220`, `memory_store.py:1059` |
| 3.5 | M7c pubsub | JWT verify checks signature + audience but **not** the token's `email`/`sub` (service-account identity) — slightly loose. | `services/pubsub_auth.py` |
| 3.6 | M7e PII | Docstring says "bank/payment details" but only **tax_id + invoice_footer** are actually encrypted — no bank fields in code. Doc/impl mismatch. | `services/pii_fields.py` |
| 3.7 | M7d headers | `Expect-CT` is deprecated/obsolete in modern browsers — harmless but dead. | `middleware/security_headers.py` |
| 3.8 | M1 RLS | RLS migration covers **only `stripe_connections`** (the one table lacking a prior policy). Defense-in-depth is thin; and it's inert under the service-role key anyway. | `migrations/2026-07-27_tenant_isolation_rls.sql` |

---

## 4. ⏳ Documented "done" items still pending a human / live step

These are marked done at the file level but need an action no code change can complete:

- **M2.3** — set the CI workflow as a **required status check** in GitHub branch protection (manual toggle).
- **M6** — multi-worker Redis **load test** to prove global enforcement (needs a running Redis).
- **M10** — live **pgvector latency benchmark** vs the recorded JSONB baseline (p50 2.6ms / p95 3.0ms),
  and `FU-M10-rpc-auth-model` (probe the RPC with a forged `p_user_id`, assert `[]`) — both need live Supabase.
- **M4.2** — regex sanitizer is applied consistently, but the planned swap to a structured
  classifier (Guardrails/LlamaGuard-style) is deferred (`structured-sanitizer-library`).
- **M11** — L4 VERIFY still pending a separate model / fresh context (L1 build complete).

---

## 5. Recommended action order

1. ~~**Fix §1 immediately** — restore `.eq("user_id", user_id)` and add a destructive-write test.~~
   ✅ **Done 2026-07-31** (9 functions + 8-test regression suite, mutation-verified).
2. Migrate the highest-traffic §2 bypass sites (routers first) onto `repo()`, or add a lint that
   fails CI on new `.table(` calls outside the store layer.
3. Address §3 items opportunistically (3.1 and 3.2 matter most for production correctness).
4. Close the §4 human/live steps as the environments become available.

---

## Appendix — what this branch adds over `feature/project-management`

Security: tenant-isolation wrapper + RLS (M1), fail-closed token encryption (M3), consistent LLM
injection sanitizer + adversarial suite (M4), signed OAuth state (M7b), Pub/Sub JWT (M7c),
nonce CSP + COOP/COEP (M7d), app-level PII field encryption (M7e).
Infra/perf: Redis rate limiting (M6), connection pooling + request cache + background PDF/CSV jobs
+ async LLM + dashboard indexes (M8), pgvector recall with SECURITY-DEFINER RPC (M10).
Compliance/observability: GDPR export/delete/consent (M9), correlation-id access logging + PII
scrubber + KPI dashboard (M11).
Process: GitHub Actions CI (flake8/black/mypy/pytest+coverage), frontend jest, regenerated
`schema.sql`, `.env.example`, billing CHECK fix (M2, M5).
