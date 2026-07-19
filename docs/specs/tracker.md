# Kora — Build Tracker

_Last updated: 2026-07-10 (backlog logged in §5 — plan gating §5.10, follow-up/digest email wiring §5.11, GCP Cloud Run containerized deployment for frontend+backend §5.9; corrected Stripe/Playbook/Resend status to reflect actual code). Prior: 2026-06-27 security hardening + GDPR endpoints §2.15._

AI-native back-office SaaS for freelancers & small businesses (hacker.fund 90-day hackathon MVP).

**Stack:** Next.js 14 (App Router, TS) frontend + FastAPI (Python 3.12) backend · Supabase (Postgres + Auth) · OpenAI-compatible PwC LLM gateway (Vertex AI deferred to GCP phase).

**Legend:** ✅ done & verified · 🟡 partial · ⬜ not started

---

## 1. Architecture & Infrastructure

| Item | Status | Notes |
|---|---|---|
| Next.js + FastAPI split (per SKILL.md §2/§3) | ✅ | `kora/frontend/` + `kora/backend/` |
| Pydantic v2 models (CamelModel, camelCase aliases) | ✅ | `app/models.py` |
| Data-backend dispatcher (`store.py`) | ✅ | `KORA_DATA_BACKEND` → `memory_store` or `supabase_store` |
| LLM provider abstraction | ✅ | `services/llm.py` + `vertex_ai.py`; `KORA_AI_BACKEND=auto/openai/mock/vertex` |
| Corporate TLS interception fix — Python | ✅ | `app/_bootstrap.py` → `truststore.inject_into_ssl()` |
| Corporate TLS interception fix — Node | ✅ | `NODE_OPTIONS=--use-system-ca` in `package.json` scripts |
| Agent audit logging | ✅ | `services/agent_logger.py` → `agent_logs` (model, tokens, latency, cost) |
| Security primitives | ✅ | prompt sanitization, rate limit, plan gate, CORS, error handler, security headers, Sentry scrubbing |

---

## 2. Modules (SKILL.md §5)

| # | Module | Status | What works |
|---|---|---|---|
| M1 | Auth + Billing | 🟡 | **Auth ✅** (email/password + Google OAuth, middleware guard, JWT forwarding). **Billing ⬜** (Stripe not started) |
| M2 | Bookkeeper | ✅ | CSV upload → AI categorization → persisted; P&L |
| M3 | Invoice agent | ✅ | Create/list invoices, PDF generation, AI follow-up emails (drafted, contract-grounded on final notice), overdue tracking, **payment-demand letter** |
| M4 | Alerts / digest | ✅ | Alert agent, run-digest button, unread alerts on dashboard |
| M5 | Contracts | ✅ | Contract wizard, AI draft generation (**per-type clause scaffolds + auto risk-review on generation**), milestones, PDF, AI risk reviewer (Kora + uploaded/received contracts) |
| M6 | Cross-module | ✅ | Contract signed → auto-creates milestone invoices; overdue invoice → contract-grounded payment-demand letter; **payment reconciliation (bookkeeping income → marks invoice paid, stops follow-ups)** (`cross_module.py`) |
| M7 | Cash-flow forecast | ✅ | 90-day 3-scenario projection + AI risks/actions (fixed object→string crash 2026-05-30) |
| M8 | Agent log dashboard | ✅ | Agent explorer, per-agent stats |
| M9 | Butler (AI business partner) | ✅ | Clients + engagements + notes, quick capture (AI-parsed), morning briefing, proposals (→ contract), retainers (→ draft invoice), deterministic client health, supervisor integration — see §2.12 |
| M10 | Google Butler (Gmail / Drive / Calendar) | ✅ | Google OAuth (connect/status/disconnect), Fernet token encryption, Gmail intel sync + email drafts, Drive doc cache, Calendar intel, Meeting transcript upload + quick-note, action items — see §2.14 |

### 2.1 AI agents coverage (vs `agents.md`)

| # | Agent | Status |
|---|---|---|
| 1 | Transaction categorization | ✅ |
| 2 | Invoice follow-up (3-tier) | ✅ (final notice now grounded in contract clause) |
| 3 | Contract generation | ✅ |
| 4 | Cash-flow analysis | ✅ |
| 5 | Daily digest / alerts | ✅ |
| 6 | **Payment demand letter** | ✅ _done 2026-05-30_ — `generate_payment_demand` (both providers), `POST /api/invoices/{id}/demand`, contract-clause extraction, demand-letter button on overdue invoices, logged as `cross_module` when grounded |
| 7 | Conversational chat | ⬜ **not started** — only `AgentType.chat` enum exists; needs `/api/chat` + context injection + chat UI |

> Demo data: seed now has **INV-2026-021 (Harbor Co, overdue, linked to a signed contract)** so the contract-grounded demand letter shows by default; INV-2026-009 (no contract) demonstrates the ungrounded path.

### 2.6 Supervisor Phase 2 — Conversational Manager (chat) — _done 2026-05-31_
- **What:** the "Ask your manager" chat (also closes agents.md **#7 Conversational Chat** — the last unbuilt agent). Natural-language Q&A grounded in the owner's **live data** (income vs goal, overdue invoices, cash flow, contracts), with **suggested-action chips** (Run review / open invoices / contracts / cash flow / bookkeeping).
- **Backend:** `chat_reply()` in both providers (real returns `{reply, suggested_actions}` JSON; mock keyword-based). `supervisor.chat()` injects a compact cross-module context, logs as `chat` agent type (already allowed — **no migration**). `POST /api/manager/chat` (rate-limited, input sanitized).
- **Frontend:** chat panel on `/manager` (`ManagerChat`) — message thread, starter suggestions, action chips wired to run-review / navigation.
- **Works without the pending migrations** (reads live data only). Verified in mock mode (overdue / goal / cash-flow questions answered with real numbers); typecheck + build pass.
- _Phase 2b (tool-calling) now built — see §2.7. Still deferred: preference learning._

### 2.9 Supervisor — Broadened actions (§5) — _done 2026-05-31_
- **Auto-categorize (AUTO):** `bookkeeper.recategorize_uncategorized()` re-runs AI categorization over never-categorized transactions during each supervisor pass (reversible/internal); surfaced in "Handled automatically".
- **Write-off proposal (APPROVAL):** `assess()` proposes `writeoff_invoice` for invoices >60 days overdue after 3 reminders; approve → invoice set to `cancelled` (logged). New `Ban` icon + generic approve message in the queue.
- **Agentic `propose_write_off` tool** added to the chat tool registry (queues for approval, never cancels directly).
- Fixed a refactor bug (`label`→`verb`) that briefly broke agentic queueing for all three propose tools; re-verified follow-up/demand/write-off agentic queueing works.
- _Contract send/sign reminders deferred_ — need email (Resend); unsigned contracts already surface as an advisory.
- Verified (mock + real gateway): write-off proposed/approved → invoice cancelled; auto-categorize count; agentic write-off queues cleanly. typecheck + build pass.

### 2.8 Supervisor — Manager memory + Advisories — _done 2026-05-31_
- **Migrations applied** (live, verified): `users.profile`, `users.manager_memory`, `manager_tasks`. Supervisor now runs end-to-end on real Supabase.
- **Manager memory / continuity (§4a L5):** new `users.manager_memory` JSONB (separate from user-editable `profile` to avoid round-trip loss) + `get/set_manager_memory` store helpers. `run_supervisor` persists last briefing + rolling summary; `GET /api/manager` returns `lastBriefing` so the Manager page **shows the briefing on load**; the previous summary is fed into the next briefing for continuity.
- **Advisory findings (§3):** `_advisories()` surfaces cash-flow danger, unsigned contracts, and uncategorized/low-confidence transactions in the run result + `GET` snapshot + briefing narrative; a deduped `cashflow_danger` alert is raised. New **"Heads up"** section on `/manager`.
- Verified live (tester): run → briefing persisted + advisories; GET returns lastBriefing + advisories without an LLM call. typecheck + build pass.

### 2.7 Supervisor Phase 2b — Agentic tool-calling — _done 2026-05-31_
- **What:** the manager chat now uses **true LLM function-calling** — the model autonomously calls tools to ground answers in live data and to act, instead of just suggesting chips.
- **Tools (`supervisor.py` registry):** read = auto-run (`get_financial_summary`, `list_overdue_invoices`, `list_contracts`, `get_cashflow`); **action = approval-gated** (`propose_follow_up`, `propose_payment_demand` only **queue** a `manager_task`, never send); plus `run_full_review`. System prompt enforces the safety rule.
- **Loop:** `llm.chat_messages()` (OpenAI `tools`/`tool_calls` round) + `supervisor.chat_agentic()` (≤5 iterations, executes tools, feeds results back). **Graceful fallback** to the Phase-2a suggestion chat when the mock provider is active or the gateway lacks function-calling.
- **Frontend:** chat refreshes the approval queue when an action is queued (`onActed`).
- **Verified live on the gateway (azure.gpt-4o-mini):** "how am I doing + what's overdue" → model called read tools, answered with real numbers; "chase INV-2026-009" → called `propose_follow_up` → **queued for approval, not sent** (safety boundary intact). Mock mode correctly falls back. typecheck + build pass.

### 2.5 Supervisor / AI Business Manager (Phase 1) — _done 2026-05-31_ ⚠️ needs 1 migration
- **What:** goal-aware orchestration layer over the point agents (per `supervisor-design.md`). Reconciles
  payments + refreshes forecast automatically, **queues client-facing/irreversible actions for approval**,
  and writes a manager's briefing prioritized by the owner's goals.
- **Backend:** `services/supervisor.py` (`gather_state` → `assess` → reconcile/auto → queue → `compose_manager_briefing`
  one LLM call → log). `manager_tasks` approval-queue table (+ store CRUD in both backends, idempotent queueing).
  `compose_manager_briefing` in both providers. Single-invoice `send_follow_up_for()` for approve-dispatch.
- **Endpoints:** `GET /api/manager` (cheap snapshot, no LLM), `POST /api/manager/run` (full pass; user + cron),
  `POST /api/manager/tasks/{id}/approve` (→ runs the agent: send follow-up / demand), `…/dismiss`.
- **Frontend:** `/manager` "Business Manager" page (sidebar top item): briefing + priorities, "Handled
  automatically" list, monthly-goal progress, overdue/cash stats, and the **approval queue** (Approve/Dismiss).
- **Safety:** conservative — only reversible/internal actions auto-run; all client comms & money moves are
  approval-gated. Audited as `cross_module` (source_record_type=`supervisor`). HITL approval is the control surface.
- **Migration required:** `migrations/2026-05-31_add_manager_tasks.sql` (the profile migration §2.4 is also a prereq for goal-awareness).
- Verified end-to-end in **mock mode**: run → briefing + auto-actions + 1 queued demand (escalation logic correct) → re-run idempotent → approve → demand letter generated → task done → queue cleared. typecheck + build pass.

### 2.4 Business Profile (owner + business context) — _done 2026-05-31_ ⚠️ needs 1 migration
- **Purpose:** rich owner + business profile (business type, industry, offerings, payment prefs, financial goals, brand tone) — the context the upcoming **supervisor agent** will read to manage finances/invoices/contracts.
- **Storage:** single `profile` JSONB column on `users` (flexible, future-proof). `BusinessProfile` model (all optional) + `User.profile` field (coerces null→{}). Added to `schema.sql`; **migration `migrations/2026-05-31_add_user_profile.sql` must be run once** in the Supabase SQL editor for the existing DB (DDL can't run via the service client).
- **Endpoints:** `GET /api/profile`, `PATCH /api/profile` (merges only client-provided keys into the JSONB; never wipes other fields). `User`/`/api/me` now carry `profile`.
- **UI:** `/settings` "Business profile" page (sidebar link) — sectioned form: Owner · Business · Financial preferences · Goals · Communication. Onboarding now saves the chosen business type into the profile (best-effort).
- Verified: reads default to empty profile pre-migration; camelCase parsing + partial-merge logic confirmed offline; typecheck + build pass. **Live write verified only after the migration is applied.**

### 2.10 Contract generation strengthened — _done 2026-05-31_
- **Per-type clause scaffolds (#1):** `_CONTRACT_SECTIONS` in `vertex_ai.py` defines the required numbered sections per type (freelance 13, NDA 8, service 12, IP transfer 9, refund policy 8 — from agents.md). Injected into the real generation prompt ("MUST include these sections… substantive clauses, not placeholders"); mock builder now uses the same scaffolds.
- **Auto risk-review on generation (#3):** `contract_agent.generate_contract` runs the Reviewer on the fresh draft and embeds it in `terms._review` (camelCase, persists, no migration). Contract preview shows the review inline; the manual "Review" button still re-runs on demand.
- Verified live: freelance agreement generated all 13 sections; auto-review embedded (flagged high risk / 3 findings / 3 missing — the gen→review loop working). typecheck + build pass.
- _Note: each generation now makes 2 LLM calls (draft + review). Jurisdiction clause library ✅ added 2026-06-27 (see §8 + `vertex_ai.py` `_JURISDICTION_CLAUSES`)._

### 2.11 Contract generation — structured per-type inputs — _done 2026-05-31_
- **Wizard rewritten** ([contract-wizard.tsx]): the single free-text terms box is replaced with **structured fields per contract type** (freelance: project/deliverables/dates/fee type/amount/schedule/Net-days/revisions/IP ownership; NDA: type/scope/purpose/duration; service: services/term/fee/billing/auto-renew; refund: window/conditions/non-refundable/method; IP transfer: work/consideration/date/moral-rights), driven by a `FIELDS` schema with text/textarea/number/date/select controls + an optional "Anything else?" note.
- Required primary field gates the Generate button; selects default sensibly; values submit as well-named `terms` keys → much stronger LLM signal. Backend unchanged (`terms` already a flexible dict).
- Verified: freelance (13 sections) + NDA (8 sections) generate from structured inputs with auto-review embedded. typecheck + build pass.
- Closes §8 strengthen-item (2). Remaining: (4) stronger model + jurisdiction clause library.

### 2.3 Contract Reviewer (risk / loophole analysis) — _done 2026-05-31_
- **Two entry points:** (1) **Review a Kora contract** — button on each contract → `POST /api/contracts/{id}/review`. (2) **Review a received contract** — `/contracts/review` page with **upload (PDF/DOCX/txt) or paste** → `POST /api/contracts/review/upload` / `POST /api/contracts/review`.
- **Reviewer agent** `review_contract` in both providers (`vertex_ai.py`); real provider prompts for `overall_risk`, `summary`, `findings[]` (severity·category·issue·recommendation·clause ref), `missing_clauses[]`, `favorable_points[]`. Analyzes from the *recipient's* perspective; contract text wrapped as untrusted data (prompt-injection-safe). Mock fallback included.
- **Text extraction:** `utils/document_text.py` (pypdf for PDF, python-docx for DOCX, decode for txt; friendly errors for scanned/unsupported). Deps added to `requirements.txt` + installed.
- **Service** `contract_agent.review_contract` normalizes the model output (severity coercion, string-lists), logs as `contract_generator` (no `contract_reviewer` value in the `agent_logs` CHECK — reused; action text marks it as a review). Rate-limited 15/hr.
- **UI** `ContractReviewView` (risk banner, findings sorted by severity, missing protections, favorable points, not-legal-advice disclaimer) + `ContractReviewer` (upload/paste tabs).
- **Not persisted on the contract row** (avoids the `terms` JSONB `_provider_name` round-trip) — review is returned + logged to `agent_logs`. *Future:* dedicated `contract_reviews` table for history.
- Verified live: risky sample → high risk, flagged unlimited liability / termination-for-convenience / Net-90 / unlimited revisions + missing late-fee/confidentiality/IP; seeded Harbor contract → high risk, 3 findings.

### 2.12 Butler — AI business partner (manager_skill) — _done 2026-06-02_ ⚠️ needs 1 migration (live/Supabase only)

Built the full 6-phase Butler from `manager_skill/SKILL.md`, adapted to Kora's real conventions (the skill's reference code targeted a different stack — async `ClientStore`/`create_client`/`getGeminiForAgent`/Shadcn/`ti-` icons — none of which exist here). All 6 phases implemented + verified end-to-end in mock mode (TestClient) and `next build` clean.

- **Phase 1 — Client entity:** `clients`, `engagements`, `client_notes` tables; models (`Client`/`Engagement`/`ClientNote` + create/update bodies); store CRUD in **both** backends; `routers/clients.py` (CRUD + engagements + notes + health). Clients enriched with financials by **case-insensitive client-name match** to invoices/contracts (no FK on hot tables → backward compatible).
- **Phase 2 — Quick capture:** `quick_captures` table; `CaptureCreate`; AI `parse_capture` (real + deterministic mock) parses freeform notes → intent/entities and applies safe actions (create note, bump engagement status at ≥0.7 confidence); **inline** parse (Kora has no worker runtime) — raw text never lost, low-confidence flagged for review. Injection attempts rejected (400), not stored. 50/day rate-limit.
- **Phase 3 — Morning briefing:** `services/butler.py` gather→assess→**one LLM call** (`compose_butler_briefing`); persists `users.butler_memory` (rolling continuity) + a daily `morning_briefing` alert; `routers/butler.py` GET snapshot (no LLM) + POST run (user + cron).
- **Phase 4 — Proposals:** `proposals` table; `proposal_agent.py` (generate via 1 LLM call; **accept → auto-generates a contract** via `contract_agent`, which auto-reviews it); `routers/proposals.py` (list/get/generate/accept/send). **Send is HITL** — queues a `send_proposal` manager_task; approval wired into `supervisor.approve_task`.
- **Phase 5 — Retainers:** `retainers` table; `routers/retainers.py` (list/create/patch + **`/invoice` on-demand** — the worker-equivalent: creates a draft invoice + advances `next_invoice_date`).
- **Phase 6 — Supervisor integration:** `supervisor.gather_state` now includes `client_context` (at-risk + silent clients); surfaced as advisories (`at_risk_clients`, `silent_clients`) and in the manager briefing payload.
- **Deterministic client health** (server-side only, never trusted from client): score from overdue money + at-risk engagements + silence; persisted on the client.
- **Frontend:** sidebar "Butler" entry; `/butler` (briefing + stats + client health list + quick-capture bar), `/butler/clients/new`, `/butler/clients/[id]` (Overview/Engagements/Notes/Financials tabs), `/butler/proposals` (+ `/new`, `/[id]`), `/butler/retainers`, `/butler/capture` (review queue). All RSC-loaded; types in `lib/api/types.ts`.
- **Migration:** `artifacts/migrations/2026-06-02_add_butler.sql` (7 tables + `users.butler_memory` + `agent_logs` CHECK adds `'butler'`). **Mock mode works with no migration** (seeded demo clients/engagements/notes/proposal/retainer). Live Supabase needs this applied.
- **Deviations from skill (deliberate, adapt-to-Kora):** no FK columns on `invoices`/`contracts`/`transactions` (name-match linkage instead — safer, no risk to working inserts); health computed deterministically (cheaper/offline-demoable) rather than per-client LLM call; capture parsed inline rather than in a background worker; Cloud Scheduler jobs not added (deferred with the rest of deployment).

### 2.14 Google Butler (Gmail / Drive / Calendar / Meetings) — _done 2026-06-10; migration + fixes 2026-06-17_

Full 8-phase email_skill wired into the Kora codebase. Adapted from the reference design to Kora's stack (FastAPI, service-role Supabase client, existing auth/store patterns).

- **Phase 1 — Google OAuth:** `routers/auth_google.py` — `/api/auth/google/connect` (returns auth URL), `/callback` (exchanges code, stores encrypted tokens, updates `users.google_connected`), `/status`, `/disconnect` (revokes token + clears row).
- **Phase 2 — DB migration:** `migrations/2026-06-10_add_google_butler.sql` — 5 new tables (`google_connections`, `email_intel_cache`, `meetings`, `drive_doc_cache`, `meeting_action_items`) + column additions to `users`, `client_notes`, `manager_tasks`, `agent_logs`.
- **Phase 3 — Gmail intel:** `services/gmail_intel.py` + `routers/gmail_intel.py` — syncs email threads per client, caches sentiment/relationship health/commitments in `email_intel_cache`; `/api/gmail/sync`, `/intel`, `/draft/{client_id}` (HITL-gated via `queue_gmail_send`).
- **Phase 4 — Drive intel:** `services/drive_intel.py` + `routers/drive_intel.py` — scans Drive for transcripts/SOWs, routes transcript files to meeting agent.
- **Phase 5 — Calendar intel:** `services/calendar_agent.py` + `routers/calendar_intel.py` — reads upcoming events, surfaces client meetings.
- **Phase 6 — Meeting agent:** `services/meeting_agent.py` + `routers/meetings.py` — transcript upload (.txt/.vtt/.srt/.docx/.pdf, 2 MB limit) + quick-note → AI extracts summary/decisions/commitments/action items; stores in `meetings` + `meeting_action_items`; action items patchable.
- **Phase 7 — Token encryption:** `services/token_encryption.py` — Fernet symmetric encryption; `TOKEN_ENCRYPTION_KEY` in `.env`; used in OAuth callback (encrypt) and `google_auth.get_user_credentials()` (decrypt + auto-refresh).
- **Phase 8 — Actions dispatch:** `manager_tasks.kind` CHECK extended for `send_email_gmail`, `create_calendar_event`, `send_meeting_followup`; `agent_logs.agent_type` CHECK extended for `butler_gmail`, `butler_drive`, `butler_calendar`, `meeting_agent`, `gmail_agent`, `calendar_agent`.
- **Frontend:** Google Connect card on `/settings` (connect / status / disconnect); OAuth callback banners (`?google_connected=true` / `?google_error=...`).
- **Fixes applied 2026-06-17:** (1) `GOOGLE_OAUTH_REDIRECT_URI` corrected to port 8000 in `.env`; (2) `User` model + `Me` TS type now include `google_connected`/`google_email`; (3) `AgentType` enum now includes `supervisor` and `butler_calendar`; (4) `_get_fernet()` caches a single Fernet instance at module load (was generating a new temp key per call).

### 2.15 Security hardening + GDPR compliance — _done 2026-06-27_

Implemented all items from `privacy_artifacts/` that were designed but not yet wired into the codebase.

- **Security headers middleware** (`middleware/security_headers.py`): `SecurityHeadersMiddleware` adds HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, X-XSS-Protection, and a tight Content-Security-Policy to every response. Registered in `main.py` above the CORS middleware.
- **Sentry with data scrubbing** (`main.py`): `sentry_sdk.init()` added, enabled only when `SENTRY_DSN` env var is set (silent in dev). `_scrub_sensitive_data` `before_send` hook strips all keys containing `amount`/`total`/`token`/`email_body`/`transcript`/etc. from Sentry payloads, and redacts request bodies. `SENTRY_DSN` + `ENVIRONMENT` added to `config.py`.
- **Account deletion endpoint** (`routers/account.py` — `DELETE /api/account/delete`): GDPR right to erasure. Ordered deletion: revokes Google OAuth token → cancels Stripe subscription → deletes GCS files (`delete_user_data`) → wipes 20 DB tables → deletes user row → deletes Supabase auth identity → appends a no-PII audit row to `deletion_log`.
- **Data export endpoint** (`routers/account.py` — `GET /api/account/export`): GDPR right to portability. Returns all user data (profile, clients, invoices, contracts, transactions, engagements, proposals, retainers, meetings, quick captures, playbook) as a timestamped JSON payload. Agent log count included (not full logs, to keep response size reasonable).
- **Google disconnect cache cleanup** (`routers/auth_google.py`): disconnect now deletes `email_intel_cache` and `drive_doc_cache` rows for the user after revoking the token. Required by Google's Limited Use Requirements.
- **Bug fix — Invoice `amount_paid` null** (`models.py`): `amount_paid: float = 0` → `amount_paid: float | None = 0`. Pydantic rejected DB rows where the column is NULL (older invoices); the `or 0` fallback in payment logic already handles None safely.

### 2.24 Task / project ledger + Notion connector — _done 2026-07-17_

Closes the "nothing gets missed on client work" gap. Previously the only project object was `Engagement` (coarse status label, no sub-tasks) and "tasks" were scattered across `manager_tasks` (approval queue), `meeting_action_items` and quick captures — so a commitment made in an email or meeting had no guaranteed home. Decision (logged §5.12): **KORA is canonical**, Notion mirrors. Built in two phases.

**Phase 1 — native task ledger (canonical)**
- **Models**: `Task` + `TaskCreate`/`TaskUpdate`; `TaskStatus` (todo|in_progress|blocked|done|cancelled), `TaskPriority`, `TaskSource` (manual|meeting|email|contract|agent|notion). Migration `2026-07-17_add_tasks.sql` — client/engagement FKs, RLS, **partial unique indexes on `(user_id, source_ref)` and `(user_id, external_ref)`** (the two idempotency keys).
- **Store**: `list/get/insert/update/delete_task` + `find_task_by_source_ref` / `find_task_by_external_ref` in both backends; re-exported in `store.py`.
- **`services/task_ledger.py`**: `create_task` (upserts on `source_ref` → auto-capture is idempotent), `update_task` (stamps/clears `completed_at` on status transitions), `stats`, `is_overdue`, and **`build_task_brief`** (prompt block; overdue → blocked → rest, each task listed exactly once).
- **Auto-capture — the core of the feature**: `auto_capture_from_meeting` (action items, hooked in `meeting_agent._create_action_items`), `auto_capture_from_email` (pending commitments, hooked in `playbook.observe_email_intel`), `auto_capture_from_contract` (signed-contract milestones → delivery tasks, hooked in `cross_module.on_contract_signed` — the invoices cover money owed, these cover *work* owed).
- **Agent wiring**: new **tasks tier in `playbook.assemble_context`** (before the recall tier, so an agent never promises something blocked or forgets an overdue commitment); **`list_tasks` + `propose_task` tools** on the supervisor (propose_task applies directly — internal tracking only, never contacts a client — with system-prompt guidance); **task nodes in `graph_memory.sync_graph`** (`HAS_TASK`, overdue/blocked carry higher salience); `butler.get_client_detail` → `tasks` + `openTaskCount`.
- **API** `routers/tasks.py`: `GET /api/tasks` (client/engagement/status/open_only filters), `GET /api/tasks/stats`, `POST`, `PATCH /{id}`, `DELETE /{id}`.
- **UI**: new **Tasks tab** in `client-workspace.tsx` (second, after Overview) — inline add, optimistic done/blocked toggles, overdue badge, and a provenance chip ("from meeting/email/contract", "added by Kora"). Types `Task/ClientTask/TaskStats` + `ClientDetail.tasks`.

**Phase 2 — Notion connector (mirror)**
- **Decision: KORA PROVISIONS the database.** `provision_tasks_db` creates a "KORA — Client Tasks" DB under `NOTION_PARENT_PAGE_ID` with our own schema (Name/Status/Priority/Due/Client/Owner/Source/**KoraId**) — chosen over mapping to a user-built DB so a renamed property can't silently break sync.
- **`services/notion_connector.py`**: pure, unit-testable mapping (`task_to_properties`, `page_to_patch`, `page_kora_id`) separated from a thin httpx layer (`_request`). `push_task` (create/update by `external_ref`), `pull_changes` (query sorted by `last_edited_time` — polling, since Notion webhooks aren't guaranteed per workspace), `sync` (push changed → pull edits; skips rows where `updated_at <= synced_at`), OAuth (`oauth_authorize_url`/`exchange_code`, token Fernet-encrypted) **or** a server-level `NOTION_API_KEY` internal integration.
- **Conflict model**: Notion may override only the human "working" fields — title/status/priority/due. **Linkage + provenance (client_id, engagement_id, source, source_ref) are KORA-owned**, so an edit in Notion can never re-parent a task.
- **Store/migration**: `notion_connections` (`2026-07-17_add_notion_connection.sql`, encrypted token, RLS) + `upsert/get/update/delete_notion_connection` in both backends.
- **API** `routers/notion.py`: `/status`, `/connect`, `/callback`, `/provision`, `/sync`, `/run` (cron), `DELETE /disconnect`. New `notion` cron job (7:10 UTC daily). **UI**: `NotionConnectCard` in Settings → Integrations (connect → create database → sync now, with status/last-sync/error) + `?notion=connected|error` banners.
- **Verified**: py_compile all touched files; app imports (**143 routes**; 5 `/api/tasks` + 7 `/api/notion`; 13 agent tools with `_TOOLS`/`_HANDLERS` asserted in sync). Mock smoke: CRUD; **all 3 auto-capture paths produce exactly the expected 7 tasks and are idempotent on re-run**; stats (overdue/blocked/dueToday); `build_task_brief`; task tier present in `assemble_context`. Notion: graceful degradation when unconfigured (no exception), **full property round-trip** (KORA→Notion→patch→ledger, incl. `completed_at` stamping) and an assertion that linkage/provenance is *not* overridable. `npx tsc --noEmit` exit 0.
- **Found & fixed during the build**: `build_task_brief` listed a task twice when it was both overdue *and* blocked — now bucketed so each task appears exactly once (as overdue, the more urgent framing).
- **Needs migrations**: `2026-07-17_add_tasks.sql` (required) and `2026-07-17_add_notion_connection.sql` (only if using Notion). To use Notion set either `NOTION_API_KEY` or `NOTION_OAUTH_CLIENT_ID/SECRET`, plus `NOTION_PARENT_PAGE_ID` (a page shared with the integration).

### 2.23 Hybrid semantic memory — recall (agent_memory) — _done 2026-07-16_

The persistent, meaning-based recall layer the agents were missing. Previously all retrieval was heuristic (exact key / normalized-name match, confidence/salience thresholds, top-N) — no way to fetch relevant PAST context by meaning. This adds a durable `agent_memory` index the agents query for planning/decisions, hybrid-ranked. **No new infra**: embeddings stored as JSONB, scored in Python (same small-per-user assumption as the graph); pgvector ANN is a drop-in optimization later behind the same interface.

- **Embeddings** (`services/embeddings.py`, new): thin best-effort wrapper over the existing OpenAI-compatible gateway (`embed`/`embed_batch`, content-hash cache). Never raises — returns None when disabled/on error. Config `EMBEDDING_MODEL` (default **`azure.text-embedding-3-small`** — confirmed available on the dev gateway via `/v1/models`; 1536-dim). Empty/unavailable model → semantic term drops out, recall falls back to lexical-only.
- **Store** (`agent_memory`): `upsert_agent_memory` (idempotent on kind+ref_id), `get_agent_memory` (client/kind/limit filters), `delete_agent_memory_for_user` in **both** backends; re-exported in `store.py`. Migration `2026-07-16_add_semantic_memory.sql` (JSONB embedding, RLS `auth.uid()=user_id`, unique `(user_id,kind,ref_id)`).
- **Recall service** (`services/memory_recall.py`, new): `remember()` (embed + upsert, best-effort, `defer_embed` for bulk); `recall()` **hybrid score = 0.60·cosine + 0.20·lexical + 0.12·salience + 0.08·recency** (lexical-only fallback = 0.70/0.18/0.12; 30-day recency half-life); `build_recall_brief()` (prompt block); `reindex()` (backfills from Playbook summaries + graph fact nodes + email-intel summaries, then batch-embeds missing) + `stats()`.
- **Writers** (live, best-effort): `graph_memory.ingest_fact` → remember(kind=graph_fact, ref_id=fact node id — matches reindex so no dupes), captures all email/meeting client commitments already bridged there; `gmail_intel` → remember(kind=email_intel) per client summary. Playbook covered by the daily reindex.
- **Readers**: new **recall tier in `playbook.assemble_context`** (task+client-synthesized query → the single injection channel all agents share); **`recall_memory` agentic tool** on the supervisor (LLM forms its own query for "have we handled X before?" type questions) + system-prompt guidance; `butler_comms.draft_client_email` grounds drafts in recalled context.
- **API** (`routers/memory.py`, registered): `POST /api/memory/recall` (debug/UI), `GET /api/memory/stats`, `POST /api/memory/reindex` (cron via x-cron-secret + user path inline). New `memory` reindex cron job (6:55 UTC daily, after graph).
- **UI** (`components/settings/memory-recall.tsx` on the *What Kora knows* page, `settings/playbook`): a "Recall memory" search box — meaning-based query → ranked hits with per-result **match %**, semantic/lexical breakdown and kind tag; a **Semantic/Lexical-only** badge from `/stats` (shows whether embeddings are active); example-query chips; a **Reindex** button. Types `MemoryHit/MemoryRecallResult/MemoryStats` in `lib/api/types.ts`. Verified: `npx tsc --noEmit` exit 0.
- **Verified**: py_compile all touched files; `app.main` imports (131 routes; `/api/memory/*` register; tool in `_HANDLERS`/`_TOOLS`). Mock smoke: lexical recall ranks the right memory; client scoping; **semantic ranking with injected vectors** puts the cosine-match on top; reindex pulls Playbook. **Live gateway test**: real 1536-dim embeddings; a **paraphrased query with ZERO lexical overlap** ("client refusing to settle their invoice") correctly retrieved "Harbor Studios… unpaid bill… overdue" as top (sim 0.46, lex 0.0) — true meaning-based recall. Graceful degradation proven live (bad model name → lexical fallback, no crash).
- **Needs migration**: apply `2026-07-16_add_semantic_memory.sql` in Supabase (mock mode needs none). Set `EMBEDDING_MODEL` if your key uses a different embedding deployment.

### 2.22 Butler communication hub (Calendar · Meetings · Email · Drive) — _done 2026-07-16_

Reorganized the four Google/comms surfaces under the Butler and made the Butler run client communication on the owner's behalf (HITL). Plan: `~/.claude/plans/robust-sprouting-tiger.md`. Decisions: Butler hub (four sidebar items removed), HITL sending, add Drive client linkage now, phased.

**Phase A — navigation reorg + per-client tabs:**
- **Nav**: moved `/calendar`,`/email`,`/meetings`,`/drive` page wrappers to `/butler/{...}` (view components unchanged); new `app/(dashboard)/butler/layout.tsx` tab bar (Clients · Calendar · Meetings · Email · Drive; hidden on `/butler/clients/...`); removed the four entries from `components/sidebar.tsx`; fixed internal links (`drive-view` "View meeting", `about` page hrefs) to `/butler/...`.
- **Per-client tabs**: `components/butler/client-workspace.tsx` gained **Email · Calendar · Drive** tabs (Meetings already existed). Email = `GET /api/gmail/intel?client_id=` (new filter); Calendar = client-side filter of `/api/calendar/today`+`/unlogged` by name/clientIds; Drive = `GET /api/drive/cache?client_id=` (new filter).
- **Drive client linkage** (the one schema gap — Drive had none): migration `2026-07-16_drive_client_link.sql` adds `drive_doc_cache.client_id`; `drive_intel._resolve_client_id()` (file-name match, else body email/name) sets client_id on the cache upsert + transcript→meeting insert + brief→note insert; router `/cache` selects & filters by `client_id` (camelized → `clientId`); `DriveDoc.clientId` type added.

**Phase B — Butler runs communication (HITL):**
- **`services/butler_comms.py`** (new): `draft_client_email()` composes in the client's brand voice grounded in `build_profile_brief` + `graph_memory.query_subgraph` + email-intel context (returns draft, no send); `queue_client_email()` → `gmail_agent.queue_gmail_send()` (existing `send_email_gmail` manager-task → approved → `execute_gmail_send`). Degrades gracefully (no email on file / Gmail not connected).
- **Endpoints** (`routers/clients.py`): `POST /api/clients/{id}/compose`, `POST /api/clients/{id}/queue-email`.
- **UI**: client workspace Email tab has a **"Ask Butler to draft…"** panel (intent + tone → editable draft → **Approve & queue**); `butler-home` client rows gained a **Draft** (Mail) action deep-linking `/butler/clients/{id}?tab=email` (workspace now reads `?tab=`). **Nothing sends without an approved task.**
- **Verified**: py_compile + `app.main` import; `/compose`, `/queue-email`, `/api/{drive/cache,gmail/intel}?client_id=` all register/filter; mock smoke (Drive resolver name+email match; Butler draft returns subject/body; queue degrades when Gmail off); frontend `tsc --noEmit` exit 0 (cleared stale `.next`).
- **Needs migration**: apply `2026-07-16_drive_client_link.sql` in Supabase (per-client Drive empty until a post-migration sync runs).
- **Live browser test (2026-07-16, demo@kora.app on real Supabase)**: logged in via Playwright/Chromium and drove the UI. ✅ sidebar no longer lists the 4 comms items; ✅ Butler hub tab bar (Clients·Calendar·Meetings·Email·Drive) renders and is correctly hidden on the client-detail page; ✅ client workspace shows all per-client tabs (Overview·Engagements·Notes·Meetings·Email·Calendar·Drive·Financials); ✅ Profile v2 tabbed form + completeness meter (13%) + 7 tabs; ✅ **Butler compose worked end-to-end in-browser** — real LLM draft to the real contact ("Hi Bikash… website redesign and brand refresh…") with editable subject/body + "Approve & queue". Found **CORS gap**: only `:3000/:3001` are allowed origins (compose failed from `:3030`, worked from `:3001`) — fine for the real app on :3000. **Drive defensive fix**: `GET /api/drive/cache` now falls back to the pre-`client_id` column set so the Drive page doesn't 500 before `2026-07-16_drive_client_link.sql` is applied.

### 2.21 Agent Graph Memory (kg_nodes + kg_edges) — _done 2026-07-16_

Part 2 of the profile+memory effort. A per-user knowledge graph the agents traverse for entities and their relationships — the first true relationship layer (previously client↔invoice↔contract↔meeting was recomputed per request in Python, split between name-match and client_id FKs). **Postgres adjacency tables, no graph DB / no new infra** — same dual-backend + RLS pattern as `business_playbook`. Plan: `~/.claude/plans/robust-sprouting-tiger.md`.

- **Schema** (`migrations/2026-07-16_add_graph_memory.sql`): `kg_nodes` (node_type, entity_id, label, props, salience) + `kg_edges` (src/dst, rel, weight, props); partial unique indexes for entity vs concept nodes; unique edge (user,src,dst,rel); RLS `auth.uid()=user_id`.
- **Store** (dual backend + `store.py` re-exports): `upsert_kg_node/edge` (idempotent — salience nudges up, edge weight uses max so re-sync doesn't inflate), `get_kg_nodes/edges`, `delete_kg_for_user`.
- **Service `services/graph_memory.py`**: `sync_graph` (idempotent materialization — business/owner/goals/offerings/personas from the v2 profile; clients as hubs; invoices ISSUED/PAID, contracts SIGNED, engagements/proposals/retainers; invoices/contracts resolved to the client hub via `butler._norm` name-match — **this is the identity-resolution that unifies name-matched and id-linked records**, killing the "Manager says 2 clients, Butler shows 4" class of bug); `ingest_fact`/`ingest_client_fact` (bridged from Playbook observers); `build_graph_brief` (focused subgraph → prompt text); `query_subgraph` (structured). Small per-user graphs → loads whole graph + traverses in Python (no CTEs).
- **Retrieval wiring**: graph tier added to `playbook.assemble_context` (rides the existing `business_context` channel into supervisor/butler/generation prompts); `query_graph` tool added to `supervisor.chat_agentic` (+ handler + system prompt) so the Manager answers "what has <client> been involved in?"; `butler.get_client_detail` returns `graphFacts`; `observe_email_intel`/`observe_meeting` now bridge learned facts into the graph; `run_supervisor` best-effort `sync_graph` at the top of every run.
- **API `routers/graph.py`** (registered in `main.py`): `GET /api/graph` (camelized nodes+edges), `POST /api/graph/sync` (rebuild), `POST /api/graph/run` (cron-gated), `GET /api/graph/client/{id}`. New **graph** job in `cron.yml` (6:50 UTC daily) + workflow_dispatch option.
- **UI**: "Relationship memory" section on the **What Kora knows** page (`settings/playbook`) — a **Rebuild memory** button + per-client grouped relation list (`components/settings/graph-view.tsx`), tolerant of a missing table (empty graph). `KgNode/KgEdge/KgGraph` TS types.
- **Verified**: py_compile + `app.main` import (112 routes; all `/api/graph/*` register); mock-mode smoke (sync 18n/17e from seed; idempotent re-sync; client-focus + briefing briefs; fact ingest traversable; label not clobbered; assemble_context carries the graph tier); frontend `tsc --noEmit` exit 0.
- **Needs migration**: apply `2026-07-16_add_graph_memory.sql` in Supabase for supabase-mode. Documented future upgrades (not built): NetworkX in-process ranking; pgvector semantic recall.

### 2.20 Business Profile v2 (standardized, 6-domain, type-aware) — _Phase 1 done 2026-07-16_

Turned the shallow ~25-field profile into a standardized, business-type-aware, six-domain profile, and actually wired the rich context into the agents (previously only ~5 scalar fields reached the LLMs). Part 1 of a 2-part effort (Part 2 = agent graph memory, §2.21, not started). Plan: `~/.claude/plans/robust-sprouting-tiger.md`; resume detail: `artifacts/CHECKPOINT_2026-07-16.md`.

- **Standardized business types** (`models.py`): `BusinessType` enum `freelancer | online_seller | small_business | agency | startup` + `normalize_business_type()` (legacy values like etsy_seller/micro_business normalized on read, non-destructive). Type drives which profile tabs surface (frontend `templates.ts`) and how the AI weights context (`profile_context._TYPE_SECTIONS`).
- **Six nested domains** added to `BusinessProfile` (additive/optional, JSONB — no migration): `brand` (mission/vision/values/USP/voice/colors/logo/style), `offerings[]`, `customers` (buyer personas, industries, locations, pain points, goals), `operations` (team, hours, tools, workflows, SOPs), `marketing` (competitors, channels, socials, testimonials, case studies, sales scripts), `legal_financial`. All existing flat fields kept as the canonical invoice/contract source.
- **Agent wiring**: new `services/profile_context.build_profile_brief(profile, task_type)` renders a compact, task-aware brief; `playbook.assemble_context` Tier 1 now uses it (so supervisor/butler/contract/proposal/cashflow inherit it via the existing `business_context` channel). Invoice follow-up/demand emails (`invoice_agent` + `vertex_ai`) now write in the brand voice. `seed_from_onboarding` seeds voice/USP/primary offering/persona.
- **Completeness**: `GET /api/profile/completeness` + a live client-side meter in the Settings UI.
- **UI**: tabbed, type-driven Settings profile (`components/settings/profile-form.tsx` rewritten + `profile/templates.ts`, `profile/fields.tsx` with a reusable `RowsEditor`); onboarding step-1 type list aligned to the 5 canonical values.
- **Verified**: backend py_compile + `app.main` import + runtime smoke (legacy normalization, brief output); frontend `tsc --noEmit` exit 0. **No migration** (JSONB) — just restart backend.
- **Live-run fix (2026-07-16)**: driving `GET /api/profile/completeness` against a running server surfaced a crash when `user.profile` is a raw JSONB dict (mock `update_user` path; Supabase mode always coerces via `User(**row)`). Made the endpoint coerce `BusinessProfile(**(profile or {}))` defensively. Re-verified live: PATCH a brand/offerings slice → completeness returns `25%` with correct per-section flags; `businessType` normalized (`agency`) and `brand.voice` round-trips.

### 2.19 Google Drive completion — _done 2026-07-15_

Closed the Drive gaps found in the audit (was backend-only, invisible, unscheduled, two dead-end routes).

- **`review_contract` executor** (`supervisor.approve_task`): approving a Drive-detected contract/invoice now **actually runs the reviewer** — `drive_intel.download_drive_file_text()` (Google Doc export / PDF·DOCX·txt via `utils/document_text.extract_text`) → `contract_agent.review_contract(source="drive")` → returns the review in the task result. Previously hit "No executor for this task kind." `_queue_document_review` now stores `mimeType` in the payload so the download picks the right method.
- **Scheduled sync**: `POST /api/drive/run` (cron-secret gated, `_scheduler_user_id`) + a **6:45 UTC daily** `drive` job in `.github/workflows/cron.yml` (+ workflow_dispatch option). Previously manual-only.
- **camelize** applied to `GET /api/drive/cache` (same snake→camel fix as §2.18).
- **Drive UI (new)**: `/drive` page + sidebar entry (`HardDrive` icon) + `components/drive/drive-view.tsx` — a **Scan Drive** button (`POST /api/drive/sync`) and a list of processed files (icon + doc-type badge + date + "View meeting →" link for transcripts). Previously there was **no Drive UI at all**. `DriveDoc` TS type added.
- **Still working as before**: the Meet-transcript → meeting-intel pipeline (`sync_drive_intel`), dedup cache, filename classification, brief/scope → client note.
- **Known limits (documented, not blocking):** scope is `drive.readonly`, so the "Kora folder" scan (`kora_folder_id`) still can't be created/set — only the Meet-transcript + broad-name search paths run. Real-time Drive push not implemented. Verified: frontend typecheck clean; backend py_compile clean; all `/api/drive/*` routes register.

### 2.18 Meeting & calendar completion — _done 2026-07-15_

- **🐛 Systemic snake_case/camelCase bug fixed (high impact):** the Butler endpoints (meetings, calendar, gmail intel) returned **raw Supabase/dict rows (snake_case)** but the frontend types/components are camelCase and `serverGet`/`authedFetch` do **no conversion**. Result: calendar today's-meetings **crashed** (`ev.clientNames.length` on undefined), email intel showed blank client names, and meetings **couldn't expand** (`m.parseStatus` undefined → Details button never rendered). Fix: new `utils/casing.py` `camelize()` (recursive, idempotent) applied to `list_meetings`, `list_all_action_items`, `list_action_items`, calendar `/today` `/unlogged` `/availability`, and gmail `/intel`. This makes all three features actually render.
- **A — Manager meeting-awareness:** `supervisor._gather_meeting_context()` (today's client meetings, unlogged count, open/overdue action items) added to `gather_state`; surfaced as advisories (`todays_meetings`, `overdue_action_items`, `unlogged_meetings`), in the briefing LLM payload, and in the chat `_compact_context`. Previously only the Butler was meeting-aware.
- **C — Aggregated action items:** `GET /api/meetings/action-items?status=open` returns every open item across meetings with parent meeting + client (distinct from `/{id}/action-items`).
- **B — Meetings tab on the client workspace:** `MeetingsTab` in `client-workspace.tsx` (fetches `/api/meetings?client_id=…`) lists that client's meetings + action items with formatted summaries.
- **C(ui) — Tasks tab on the Meetings page:** new "Tasks" tab lists open action items across all meetings (client · meeting · due · priority, overdue in red) with one-click complete (optimistic PATCH `status=done`).
- Verified: frontend typecheck clean; backend py_compile clean; `camelize` unit-checked (meeting_date→meetingDate, meeting_action_items→meetingActionItems, meet_link→meetLink, nested clients.name preserved); new routes register.
- **Deferred (optional):** pre-meeting prep brief (surface last email intel / open items / outstanding invoices before a client meeting).

### 2.17 Owner notifications + email polish — _done 2026-07-15_

Completes the email story so the agents reach the **owner**, not just clients (closes §5.11).

- **Owner-email helper** (`services/owner_notify.py`): `send_owner_email()` delivers via the owner's **connected Gmail first**, **Resend fallback** (`email_service._send`), else graceful no-op — never raises. Logged as `email_delivery`.
- **Daily digest email** (Phase 2): `send_daily_digest()` composes the Manager briefing (statusLine/summary/priorities/auto/pending) → emailed to the owner. Wired into `POST /api/manager/run` **scheduler branch only** (manual runs don't spam). Note: `email_service.send_morning_digest` (Resend) existed but was never wired — this supersedes it with Gmail-first.
- **Critical alert emails** (Phase 3): `notify_critical_alert()` emails the owner on fresh **cashflow-danger** (`supervisor.py`, behind the existing 3-day dedup) and **Stripe payment-failed** (`stripe_billing.py`). Only fires when a new alert is raised.
- **Meeting follow-up UI** (Phase 4): `meeting_agent.queue_followup_for_meeting()` rebuilds a follow-up from a meeting's stored action items → `POST /api/meetings/{id}/followup` (HITL: queues `send_email_gmail` for approval, never sends directly). "Draft follow-up email" button on each parsed meeting in `meetings-view.tsx` (guards: needs a linked client with an email).
- **Gmail watch auto-renewal** (Phase 5): `gmail_intel.renew_watch_if_configured()` re-registers the ~7-day push watch; runs in the daily `POST /api/gmail/run` scheduler branch (no-op unless `GMAIL_PUBSUB_TOPIC` set).
- **Resend fallback** (Phase 6): built into `send_owner_email` (Gmail → Resend → no-op).
- **Notification preferences** (added 2026-07-15): `BusinessProfile.notify_daily_digest` / `notify_critical_alerts` (opt-out, default True) in `users.profile` JSONB. `owner_notify._pref()` gates both send paths (handles model or dict profile; existing users default to on). Settings → Business profile has an **"Email notifications"** card with two toggles (`profile-form.tsx` + `BusinessProfile` TS type). Verified: opt-out respected via model and dict profile; frontend typecheck clean.
- Verified: full backend import + py_compile clean; all new routes register; owner-email degrades to no-op with no owner email / no channel; frontend typecheck clean.

### 2.16 Gmail intel upgrades (domain matching · scheduled · deeper · real-time) — _done 2026-07-15_

Four upgrades to the client-email intelligence sync (`services/gmail_intel.py` + `routers/gmail_intel.py`):

- **Feature 1 — Domain + multi-contact matching:** clients now match by their **corporate domain** (`from:acme.com`) and **multiple contact addresses**, not one exact address — captures a client's 2nd address and colleagues at the same company. New `contact_emails text[]` on `clients` (+ `Client`/`ClientCreate`/`ClientUpdate` models). `_client_search_terms()` merges primary email + `contact_emails` + derived domains; **public providers (gmail/outlook/…) are excluded** so domain matching never matches strangers. `_build_gmail_query()` builds the OR query.
- **Feature 2 — Daily scheduled sync:** new `POST /api/gmail/run` (cron-secret gated, mirrors `/manager/run`/`/butler/run`; `_scheduler_user_id()` → DEMO_EMAIL user). Added a **06:30 UTC daily** `gmail` job to `.github/workflows/cron.yml` (+ `workflow_dispatch` option). Previously sync was manual-only despite the docstring.
- **Feature 3 — Deeper analysis:** the LLM now reads **full message bodies** (`_get_message_body()` decodes `text/plain` from the full payload) instead of snippets; caps raised (15 fetched / 5 analyzed / 3 msgs each / 8000-char combined). Higher token cost, richer intel.
- **Feature 4 — Real-time push (Gmail watch + Pub/Sub):** `register_gmail_watch()` calls `users().watch(INBOX → GMAIL_PUBSUB_TOPIC)`; `POST /api/gmail/watch` (authed) registers it; `POST /api/gmail/push` (no auth) receives Pub/Sub push, decodes `{emailAddress, historyId}`, maps mailbox→user, force-refreshes intel. New `GMAIL_PUBSUB_TOPIC` setting + `google_connections.watch_history_id`/`watch_expiration` columns. **Code-complete but inert until deployed** (Pub/Sub can't reach localhost) — needs the infra in `gmail-realtime-setup.md`.
- **Migration:** `backend/migrations/2026-07-15_gmail_intel_upgrades.sql` (clients.contact_emails + google_connections watch columns). Verified: app imports, all 6 `/api/gmail/*` routes register, matching logic (domain exclusion + dedup) unit-checked.
- **Frontend (done 2026-07-15):** "Additional contacts" input on the Add-client form (`client-form.tsx`, comma/space/semicolon-separated → `contactEmails`); `Client` TS type + `create_client` handler carry `contact_emails` (normalized lowercase). PATCH `/api/clients/{id}` already accepts `contactEmails` for later edits (no dedicated edit-client UI yet).
- **Edit-client UI (done 2026-07-15):** "Edit" button on the client detail header (`client-workspace.tsx`) opens a pre-filled `EditClientForm` (name, primary email, additional contacts, company, industry, status, type, what-we-do) → `PATCH /api/clients/{id}` → `router.refresh()`. Contacts editable/clearable after creation; header now also shows the contact-email count. Verified: frontend typecheck clean; `ClientUpdate` camelCase→snake_case patch mapping confirmed.
- **Remaining (optional):** watch auto-renewal (7-day expiry) via the daily cron.

### 2.13 Received-contract intake → Butler + Cloud Storage — _done 2026-06-04_

When a user reviews a contract a **client sent them**, it can now be saved so the Butler tracks it.

- **GCS Cloud Storage wired** (`services/storage.py`): lazy client built from `GOOGLE_APPLICATION_CREDENTIALS` (resolved repo-root/backend-relative, since pydantic reads `.env` into settings, not `os.environ`). `is_configured()` gate; degrades gracefully (503 / inline fallback) with no creds. Routes: `/api/storage/{status,exports/agent-log,receipts/...}`. **Verified live**: contract PDF + received-contract file upload to bucket `aims_data_stroage`, round-trip download, signed URLs, cross-tenant guard.
- **`contract_agent.save_received_contract()`**: persists a received contract as a `Contract` row (marked `terms._received`, `status="sent"` = awaiting the owner's signature, embeds `_review` + `_gcs_path`), uploads the original file to `users/{uid}/received-contracts/{id}.{ext}` (best-effort), and — when linked to a client — creates an **Engagement** so the Butler tracks the deliverable. Logged under `agent_type="butler"`.
- **Routes** `/api/contracts/review` (paste) + `/review/upload` now accept `clientId` / `save` (upload saves by default) and return the review plus a `saved` block (`contractId`, `clientId`, `engagementId`, `savedFile`). Backward compatible (extra keys ignored by old callers).
- **Frontend reviewer**: client picker ("Which client is this from?") + "Save so the Butler knows" toggle; success banner links to the client and notes the created engagement. The received contract then surfaces in the client's Butler workspace (Contracts + Engagements tabs) via name-match.
- Config: added `GOOGLE_APPLICATION_CREDENTIALS` + `CLOUD_STORAGE_BUCKET` settings. Manual/infra steps (bucket, IAM, CORS) remain the user's per `gcp-cloud.md §1`.

### 2.2 Payment reconciliation (bookkeeping ↔ invoices) — _done 2026-05-30_
- **Closes the loop you flagged:** when a client pays and the income lands in bookkeeping, Kora matches it to the open invoice, marks it **paid**, and **stops the follow-up cadence** — no more dunning a client who already paid.
- `reconcile_payments()` in `cross_module.py`. **Conservative**: auto-marks paid only on exact amount + client-name token **and** payment dated on/after the invoice was sent. Ambiguous (≥2 open invoices match) → "needs review" warning alert, never auto-applied.
- Runs **at the start of the follow-up agent** (scheduler + demo button) and **after each CSV upload** (surfaced in the upload result). Idempotent via consumed-transaction tracking in `agent_logs`.
- Verified live: fresh payment → invoice flips overdue→paid, no follow-up; a genuinely-unpaid invoice still gets dunned; same-amount/same-client collision → review alert, no auto-mark.

---

## 3. Persistence & Auth (verified)

- ✅ Supabase connectivity + schema applied (`schema.sql`)
- ✅ Supabase persistence backend (`backends/supabase_store.py`) — survives restart
- ✅ JSONB workarounds: `agent_logs._cost_usd`, `contracts._provider_name`
- ✅ `@supabase/ssr` cookie sessions (browser/server/middleware clients)
- ✅ Login + signup pages, OAuth callback route, route-guard middleware
- ✅ JWT forwarded: RSC `serverGet`, client `authedFetch`, authed blob downloads, sign-out
- ✅ Per-user data isolation + invalid-token rejection verified
- ✅ Seed tooling: `python -m app.seed_supabase [email password name business]`
- ✅ Test user: `tester@kora.app` / `Tester@123`

---

## 4. Frontend pages

✅ `/` landing · `/about` · `/login` · `/signup` · `/auth/callback` · `/onboarding` · `/privacy` · `/terms` · dashboard, bookkeeping, invoices, contracts, cashflow, agents, calendar, email intel, meetings, butler (full suite).

### 4.1 ✅ Onboarding flow (SKILL.md §18) — _done 2026-05-30_
- 5-step wizard at `/onboarding`: business type → profile → CSV import (optional) → first client (optional) → ready screen with 4 agent status cards.
- Backend `GET`/`PATCH /api/me` profile endpoint (`routers/users.py`); camelCase in, persists `full_name`/`business_name`/`country`/`currency`/`onboarding_completed`. `business_type` accepted but not persisted (no column yet).
- Middleware **onboarding gate**: authed users with `onboarding_completed=false` → `/onboarding`; finished users bounced off it. Reads own row via RLS.

### 4.2 ✅ Legal pages (SKILL.md §22) — _done 2026-05-30_
- `/privacy` (data collected, AI disclosure, GDPR basis, processors, retention, rights) + `/terms` (AI-content disclaimer, payment/refund, liability cap, governing law). Public routes.
- Signup form now has a required **"I agree to Terms & Privacy"** checkbox linking both pages (GDPR consent).

---

## 5. Remaining features & their requirements

> **Backlog (logged 2026-07-10).** These are the outstanding tasks agreed with the user.
> _Working agreement: log now, implement only when the user explicitly asks._
> Note: §5.1 (Stripe) and much of §5.3/§5.7 are now BUILT — corrected below to reflect actual code.

### 5.1 ✅ Stripe billing (M1) — DONE (post-tracker)
- Built: `routers/stripe_billing.py` (checkout, customer portal, cancel/reactivate, plan upgrade w/ proration, signature-verified webhook) + `routers/stripe_connect.py` (Connect OAuth so users get paid) + `/pricing` and `/settings/billing` pages + `stripe_sync.py`/`billing.py` services.
- **⚠️ Gap remaining (→ task 5.10):** `require_plan` / `contract_credits` are only referenced in `stripe_billing.py` — **no premium route is actually gated by plan.** Billing plumbing exists but restricts nothing.
- **Live-mode setup (user):** live keys, Products/Prices, register webhook endpoint.

### 5.2 ⬜ Google OAuth provider enablement (user action, ~10 min)
- **Requirements:** Google Cloud OAuth Client ID + secret; add to Supabase → Auth → Providers → Google; redirect `https://<project>.supabase.co/auth/v1/callback`.
- **Note:** Frontend button already built; only dashboard config remains.

### 5.3 🟡 Transactional email (Resend) — PARTIALLY WIRED
- **Built:** `services/email_service.py` (Resend, graceful degrade). **Invoice sending** is wired (`routers/invoices.py:176` → `send_invoice_email`).
- **⬜ Remaining code (→ task 5.11):** AI **follow-up letters and daily digests are still draft-only** — `invoice_agent.send_follow_up_for` generates text but never calls `email_service`; digests don't send either.
- **Requirements (user):** `RESEND_API_KEY`, verified sending domain (DNS SPF/DKIM, ~1–2 wk warmup).

### 5.4 ✅ Onboarding flow (SKILL.md §18) — DONE (see §4.1)

### 5.5 ✅ Legal pages (SKILL.md §22) — DONE (see §4.2)

### 5.6 ⬜ Automated tests (SKILL.md §20) — NONE EXIST
- **Requirements:** `pytest`; fixtures using `memory_store` backend.
- **Work:** webhook signature, agent logger, CSV parser, forecast string-coercion, cross-module invoice creation, playbook observers, plan gating.

### 5.7 🟡 Autonomous scheduled runs — cron workflow BUILT, needs deploy
- **Built:** `.github/workflows/cron.yml` (supervisor 07:00 UTC daily · butler briefing 07:30 Mon–Fri · invoice follow-ups 09:00 Mon–Fri) hitting the cron routes with `x-cron-secret`.
- **Remaining (user):** set `KORA_API_URL` + `KORA_CRON_SECRET` repo secrets once the backend is deployed (depends on §5.9).

### 5.8 ⬜ Vertex AI / GCP LLM migration (deferred — post-MVP)
- **Requirements:** GCP project, Vertex AI enabled, service-account creds.
- **Work:** flip `KORA_AI_BACKEND=vertex`; `services/vertex_ai.py` provider already stubbed.

### 5.9 ⬜ **NEW — Deploy to GCP Cloud Run (containerized: frontend + backend)** — logged 2026-07-10
- **Goal (user):** host BOTH the Next.js frontend and FastAPI backend on **GCP Cloud Run** (containerized), not Vercel.
- **What exists:** backend `Dockerfile` (Cloud Run-ready, uses `$PORT`); `artifacts/cloud-scheduler.yaml`; GCS storage docs (`gcp-cloud.md`).
- **What's missing / to build (me, when asked):**
  - **5.9a** Frontend `Dockerfile` (multi-stage, production).
  - **5.9b** `output: 'standalone'` in `next.config.mjs` (lean container).
  - **5.9c** `.dockerignore` for both apps (exclude `venv/`, `node_modules/`, `.next/`).
  - **5.9d** `cloudbuild.yaml` + `deploy.sh` — build → push to Artifact Registry → deploy both Cloud Run services.
  - **5.9e** Env/secret plumbing — Cloud Run env vars + Secret Manager refs (Supabase, LLM gateway, Stripe, Resend, `TOKEN_ENCRYPTION_KEY`, `CRON_SECRET`, `GOOGLE_*`).
  - **5.9f** `DEPLOY.md` runbook (gcloud command sequence).
- **User-side GCP steps:** create project + enable billing; enable Cloud Run/Build/Artifact Registry/Secret Manager APIs; create service account + IAM (GCS objectAdmin on bucket, `aiplatform.user`, secret accessor); push secrets to Secret Manager; custom domain + update `FRONTEND_ORIGIN` / Google / Stripe redirect URIs to prod.
- **Gotchas to handle:** (1) `NEXT_PUBLIC_API_URL` is **build-time** baked → deploy backend first, get its Cloud Run URL, then build the frontend image with it as a build-arg. (2) backend `main.py` CORS hardcodes `localhost:3000` → add prod frontend origin via `FRONTEND_ORIGIN`.

### 5.10 ⬜ **NEW — Enforce plan gating** — logged 2026-07-10
- Billing exists but no premium route restricts by plan. Add `require_plan(...)` dependency / `contract_credits` checks to premium endpoints (contracts, cashflow, Google Butler, etc.) so the free/paid distinction is real.

### 5.11 🟡 **Wire follow-up & demand emails to actually send** — invoices done via Gmail 2026-07-15
- **Done (2026-07-15):** approved **follow-up** and **payment-demand** letters now actually send through the owner's **connected Gmail** (not Resend — reuses the working Google Butler send infra). New `gmail_agent.send_via_gmail()` + `is_gmail_connected()`; `invoice_agent._maybe_send()` helper; `generate_demand_letter(..., deliver=True)` and `send_follow_up_for(..., deliver=True)`; `supervisor.approve_task` passes `deliver=True` for `send_demand`/`send_followup`. HITL preserved (the human approval IS the gate). Degrades gracefully to draft-only when Gmail not connected / no client email / API error, with a clear note; agent log + returned `note` say **Sent** vs **Drafted** and carry the `gmailMessageId`. Preview button (`POST /invoices/{id}/demand`) and bulk/cron paths stay **draft-only** (deliver defaults False) so nothing mass-emails by surprise.
- **Still ⬜:** daily **digest / alert** emails are not wired to send (only in-app alerts). Optional: a Resend path for users who haven't connected Gmail.

### 5.12 ✅ **Task / project ledger + Notion connector** — BUILT 2026-07-17 (see §2.24)
> Both phases implemented and verified. Design notes below kept for context; the open sub-decision was resolved as **provision** (KORA creates the Notion DB with its own schema).


> Goal: give agents a durable, granular task/progress ledger so nothing on client work is missed. Today the only project object is `Engagement` (coarse status label, no sub-tasks) — "tasks" are scattered across `manager_tasks` (approval queue), `meeting_action_items`, and quick captures.
- **Decision (2026-07-16, with user):** KORA is the **canonical** source of truth (native `tasks` layer), with a **connector to Notion** (user already uses Notion; chosen for cross-role legibility). NOT external-canonical, NOT build-nothing.
- **Native side (connector-agnostic):** new `tasks` table — `client_id` + `engagement_id`, `status` (todo/in_progress/blocked/done), `priority`, `due_date`, `source` (manual/meeting/email/agent), `external_ref` (tool + page id for idempotent sync). Task nodes in `graph_memory` (hang off client/engagement hub; overdue/blocked → higher salience). New tasks tier in `playbook.assemble_context`. Agent tools `list_tasks` / `propose_task` (HITL) / `update_task_status`. Cross-module auto-capture: `meeting_action_items` → tasks, email commitments → tasks, contract signed → delivery tasks (this is where "nothing missed" comes from). Butler client workspace Tasks/Progress tab + engagement progress %.
- **Notion connector:** OAuth public integration (per-user workspace connect); tasks DB = Notion database, task = page. Push KORA→Notion on create/update (store `external_ref`); pull Notion→KORA via **webhook + `last_edited_time` polling fallback** (Notion webhooks are new; ~3 req/sec rate limit → batched/throttled sync). KORA-canonical conflict model: Notion may override shared fields (status/due) last-write-wins by timestamp; KORA owns agent-managed fields (links/source).
- **Open sub-decision:** **provision** the Notion DBs with KORA's schema (recommended — robust, avoids schema-drift) vs **map to user's existing DB** (flexible, fragile, needs mapping/repair UI).
- **Risks:** source-of-truth drift (mitigated by KORA-canonical + `external_ref`); Notion schema drift; rate limits; multi-tenant OAuth token storage/refresh.

---

## 6. Tech debt / known issues

- ⚠️ **Secrets committed** in `backend/.env.example` (`SUPABASE_SERVICE_ROLE_KEY`, `MODEL_API_KEY`). **Action:** move to gitignored `backend/.env` and **rotate before sharing repo with judges.**
- 🟡 Cashflow page calls the LLM synchronously on every load (~5s, `no-store`). **Improvement:** cache forecast per-user + refresh via scheduled agent.
- 🟡 Performance: dashboard RSC fetches are serial; consider parallelizing.

---

## 7. Suggested next order

_Backlog logged 2026-07-10 — implement only on explicit request._
1. **Plan gating (§5.10)** — makes billing meaningful. Pure code, no external accounts.
2. **Wire follow-up/digest emails (§5.11)** — pure code, graceful no-op without a key.
3. **GCP Cloud Run deployment (§5.9)** — build Dockerfile/config/scripts (me) → user runs GCP steps → live demo link.
4. **Automated tests (§5.6)** — judging credibility.
5. External setup: Resend domain · Google OAuth provider · Stripe live keys · Vertex migration (DNS warmup / dashboards).

> Perf note: the onboarding gate adds one `users` row read per protected navigation. Fine for the MVP; cache in a cookie later if it matters.

---

## 8. Functional Feature Reviews

> **Convention (per user, 2026-05-30):** when a functional feature is discussed, verify against the actual code whether it's implemented, and log the finding here. **Discussion entries are analysis only — no code changes** unless the user explicitly asks to build.

Each entry: date · the question/feature · verdict (✅ implemented · 🟡 partial · ⬜ missing) · where it lives / what's missing.

| Date | Feature discussed | Verdict | Findings |
|---|---|---|---|
| 2026-05-30 | Does bookkeeping reconcile payments back to invoices — i.e. client pays, income lands in bookkeeping, does the follow-up agent know and mark the invoice paid? | ⬜→✅ | **At discussion time: not implemented** — `Transaction` had no invoice link; follow-up agent selected invoices by status only, so a paid invoice could still be dunned. User asked to build it → now ✅ (see §2.2 payment reconciliation). |
| 2026-05-30 | Where is the data shown in the UI stored — Supabase or local? | ✅ | **All business data is in Supabase Postgres.** `KORA_DATA_BACKEND=supabase` (`.env` + `.env.example`); live `store` → `backends/supabase_store.py`. UI renders API responses (Supabase → FastAPI → Next.js); holds no DB. Client-side only: the Supabase **auth JWT in cookies** (`@supabase/ssr`) + ephemeral React state per page view. The in-memory `memory_store.py` backend exists but is **inactive** (only used when `KORA_DATA_BACKEND=mock`; data would be wiped on restart). No `localStorage`/`sessionStorage` in app source. |
| 2026-05-31 | How does CSV upload recognize fields across different bank-statement schemas? | 🟡 | **Keyword-based column auto-detection in `utils/csv_parser.py` — heuristic, not AI, no manual mapping UI.** Matches headers (exact then substring) against candidate lists: Date (`date`/`transaction date`/`posted`), Description (`description`/`memo`/`details`/`narrative`/`name`), Amount (`amount`/`value`), Debit (`debit`/`withdrawal`), Credit (`credit`/`deposit`), Type. Handles **signed-amount OR debit/credit split**, type-column-or-sign inference, `$£€`/commas/`()` cleanup, BOM. **Gaps:** uncommon headers (`Narration`/`Particulars`) → rejected; preamble rows before header → fails; `DD/MM/YYYY` dates silently mis-parsed (`dayfirst=False`); non-comma delimiters (`;`) unsupported; no manual column-mapping fallback UI. **Proposed upgrade (not built):** LLM-assisted header→field mapping + detected date format/delimiter, with a confirm-mapping UI fallback. |
| 2026-05-31 | Contracts has a generator — is there a contract *reviewer* (flag risky clauses / loopholes in an existing contract)? | ⬜→✅ | **At discussion time: not implemented.** User asked to build → now ✅ (see §2.3 Contract Reviewer). Two entry points: review a Kora-generated contract, and review any contract the user *receives* (upload PDF/DOCX/txt or paste). |
| 2026-05-31 | How effective is contract *generation*? Does it use standard legal templates / is it jurisdiction-aware / foolproof? | 🟡→✅ | **AI drafting starting point — not a template engine.** (1) per-type clause scaffolds ✅ 2026-05-31 (§2.10). (2) structured per-type inputs ✅ 2026-05-31 (§2.11). (3) auto-review on generation ✅ 2026-05-31 (§2.10). **(4) jurisdiction clause library ✅ 2026-06-27** — `_JURISDICTION_CLAUSES` dict in `vertex_ai.py` covers US / US-CA / US-NY / GB / EU / DE / FR / CA / AU / IN / SG / AE; each entry specifies governing law, dispute resolution mechanism, mandatory statutory clauses, and late-payment interest rate. `_resolve_jurisdiction()` resolves ISO keys, aliases, and sub-national prefixes; fallback to international default. `_jurisdiction_prompt_block()` injects the resolved clauses verbatim into the `generate_contract` system prompt so the LLM drafts jurisdiction-accurate governing-law, dispute-resolution, and late-payment sections instead of generic ones. |
| 2026-06-02 | Build the "Butler" — the AI business partner from `manager_skill` (clients, engagements, quick capture, morning briefing, proposals, retainers, supervisor integration). | ⬜→✅ | **User asked to implement.** Built all 6 phases adapted to Kora's conventions (the skill's reference code assumed a different stack). New tables (clients/engagements/quick_captures/proposals/retainers/client_notes) + `users.butler_memory`; services `butler.py` + `proposal_agent.py`; routers `clients`/`butler`/`proposals`/`retainers`; AI methods `parse_capture`/`compose_butler_briefing`/`generate_proposal` (real + mock); full frontend under `/butler`. Verified end-to-end in mock mode + `next build` clean. See §2.12. Live Supabase needs `migrations/2026-06-02_add_butler.sql`. |
| 2026-05-31 | Is there a personalized supervisor / business-manager agent that understands the user's business & financial goals, orchestrates all the other agents, manages tasks on the user's behalf, and escalates critical decisions to the human (HITL)? | ⬜→✅ | Designed (`supervisor-design.md`) + **Phase 1 built** (see §2.5). Hybrid orchestrator + HITL approval queue + Manager view. (Phase 2 — chat + LLM tool-calling — still pending.) Original finding: **Not implemented — biggest architectural gap.** Zero source refs to supervisor/orchestrator/planner/goal/approval/HITL. Architecture is **independent point agents**, each fired by its own route; cross-module links are **fixed if-this-then-that rules**, not a reasoning manager. (1) No goals model — `User` has no goals/targets; onboarding captures business *type*, not objectives. (2) No orchestration — agents don't know about each other. (3) No manager loop owning tasks. (4) Only **passive alerts**, no approval queue where an agent proposes→waits→acts. Closest: `run_digest` (passive summarizer, not a supervisor). NB: SKILL.md §1 pitches a "proactive AI agent platform" — individual agents exist, the orchestrating brain doesn't. **Build outline (not built):** goals/context model; supervisor planner loop calling existing agents as tools (function-calling); HITL approval/decision queue (overlaps unbuilt `chat` agent as the manager UI); decision/preference memory. |
| 2026-06-10 | What does the `email_skill/` folder define, what's already implemented in the main codebase, and what still needs to be built? | ⬜→✅ | **At discussion time:** email_skill/ was a complete reference design — NONE wired into the live codebase. **Built subsequently (2026-06-10):** all 8 phases implemented — see §2.14. |
| 2026-06-17 | Data migration to Supabase done + `TOKEN_ENCRYPTION_KEY` added — are all app functionalities working or do they need changes? | 🟡→✅ | **4 issues found and fixed:** (1) `GOOGLE_OAUTH_REDIRECT_URI` pointed to frontend port 3000 instead of backend port 8000 — OAuth callback would never complete; fixed in `.env`. (2) `User` Pydantic model + `Me` TS type missing `google_connected`/`google_email` columns added by migration — fixed. (3) `AgentType` enum missing `supervisor` and `butler_calendar` values present in DB CHECK constraint — runtime errors if those agents logged; fixed. (4) `_get_fernet()` generated a new temp key on every call when `TOKEN_ENCRYPTION_KEY` unset — encrypt/decrypt mismatch; fixed by caching at module load. **Also built:** Settings page Google Connect section was missing — added `GoogleConnectCard` component + wired into `/settings`. |
| 2026-06-18 | Make the nav responsive and add scroll if content overflows | ✅ | **Responsive sidebar with mobile drawer.** Extracted `SidebarContent` shared component; desktop aside hidden on mobile (`hidden lg:flex`); floating hamburger button (`lg:hidden fixed top-4 left-4 z-40`) opens a slide-in `<aside>` drawer with `translate-x-0`/`-translate-x-full` transition; semi-transparent backdrop closes it; `useEffect` closes drawer on route change; `<nav>` now has `overflow-y-auto` for scroll. Dashboard layout content wrapper gets `pt-16 lg:pt-8` so mobile page headers don't sit behind the hamburger. |
| 2026-06-18 | Update the How it works page with accurate, detailed information | ✅ | **`/about` fully rewritten from source.** Expanded from 7 to 12 feature entries, each derived by reading `supervisor.py`, `butler.py`, `playbook.py`, `gmail_intel.py` — exact thresholds, penalties, observer names, TTLs, and tool names. New sections added: amber HITL guarantee box (all 6 gated action types), agent architecture card (Manager/Butler/Playbook relationships), 3-stage Playbook maturity timeline (Week 1 → Month 3+), 6-entry activity timeline showing when each agent fires, 4-step getting started guide. |
| 2026-07-15 | Email intel empty · calendar error · manager "send email" does nothing · manager miscounts clients | ✅ fixed | **Four root causes, three of them one bug.** (1) **`Credentials.expiry` tz bug** (`google_auth.py`) — expiry was set from an ISO string *with* tzinfo, but google-auth compares it against a **naive** UTC now → `TypeError: can't compare offset-naive and offset-aware datetimes` on the `creds.expired` check. This crashed **every** Google call → broke email-intel sync, calendar, AND Gmail send simultaneously. Fixed by converting expiry to naive UTC. (2) **Token encryption key bug** — `token_encryption.py` read `TOKEN_ENCRYPTION_KEY` from `os.environ`, but pydantic-settings loads `.env` into `settings`, not the process env → key always empty → random Fernet key per process → tokens undecryptable after any restart. Fixed to read `settings.TOKEN_ENCRYPTION_KEY`; `get_user_credentials` now flags the connection for reconnect instead of raising. Needed a one-time Google **reconnect**. (3) **Manager chat miscounted clients** ("2" vs real 5) — `_compact_context` had **no client data** and the agentic chat had **no client tool**, so the LLM hallucinated. Fixed: added `list_clients` tool (+ handler, schema, system-prompt rule) and put `total_clients`/at-risk/silent into the chat context. Now grounds to 5 total / 4 active. (4) **Demo clients use `.example` emails** → 0 real threads even when sync works; real intel/sends need a client with a real corresponded-with address. **Agent-comms note:** Butler + Manager/Supervisor share the same DB (no message-passing); the supervisor briefing already reads Butler client context, but the chat wasn't grounded until fix (3). |
| 2026-06-27 | Implement the privacy artifacts (`privacy_artifacts/`) — security headers, Sentry scrubbing, account deletion, data export, Google disconnect cache cleanup | ⬜→✅ | **All designed items built — see §2.15.** Gap audit: `middleware/security_headers.py` missing → created; Sentry `before_send` scrubber missing → added to `main.py`; `DELETE /api/account/delete` missing → `routers/account.py` created; `GET /api/account/export` missing → same file; Google disconnect did not clear `email_intel_cache`/`drive_doc_cache` → patched `auth_google.py`. Also fixed: `Invoice.amount_paid: float = 0` rejected DB `NULL` → changed to `float \| None = 0`. Already in place before this session: prompt injection defense (`utils/security.py`), CORS middleware, token Fernet encryption, `/privacy` + `/terms` frontend pages. |

