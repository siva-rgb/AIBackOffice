# Checkpoint — Robust Business Profile + Agent Graph Memory
_Saved 2026-07-16. Resume here tomorrow._

Plan file: `C:\Users\Asus\.claude\plans\robust-sprouting-tiger.md`
Two features, built in order: **Phase 1 = Business Profile v2 (DONE)**, **Phase 2 = Agent Graph Memory (NOT STARTED)**.

---

## ✅ PHASE 1 — Business Profile v2 — COMPLETE & VERIFIED

Goal: turn the shallow ~25-field profile into a standardized, 6-domain,
business-type-aware profile, and actually feed it to the AI agents.

### Backend (all compile-checked; app imports; new routes register)
- **`backend/app/models.py`**
  - New `BusinessType` enum: `freelancer | online_seller | small_business | agency | startup`.
  - `normalize_business_type()` + `_LEGACY_BUSINESS_TYPE` map (etsy_seller→online_seller, micro_business→small_business, side_hustler/side_project/solopreneur→freelancer, …). Applied via a `business_type` `field_validator` on `BusinessProfile` (normalizes on read/validate).
  - New nested sub-models: `BrandIdentity, Offering, BuyerPersona, Customers, TeamMember, Operations, SocialAccount, Marketing, LegalFinancial`.
  - `BusinessProfile` gained: `brand, offerings[], customers, operations, marketing, legal_financial` (all additive/optional, defaults). All existing flat fields kept (canonical source for invoice/contract agents). `_coerce_domain` validator normalizes JSONB null → {}.
- **`backend/app/routers/users.py`**
  - New `GET /api/profile/completeness` → `{percent, sections{...}}` via `_profile_completeness()` + `_has()` helpers.
  - `PATCH /api/profile` unchanged (shallow top-level merge already handles nested keys).
- **`backend/app/services/profile_context.py`** (NEW)
  - `build_profile_brief(profile, task_type, *, business_name, max_chars)` → compact prompt block. Task-aware (email/contract foreground brand voice + guarantees; briefing/chat foreground offerings/customers/goals). `_TYPE_SECTIONS` mirrors the frontend `templates.ts` visibility.
- **`backend/app/services/playbook.py`**
  - `assemble_context` Tier 1 now calls `build_profile_brief(...)` (replaced the old ad-hoc identity lines) — so supervisor, butler, contract, proposal, cashflow (all already route through `assemble_context`) get the rich profile automatically.
  - `seed_from_onboarding` now also seeds brand voice, USP, primary offering, primary persona as Playbook entries.
- **`backend/app/services/invoice_agent.py`**
  - New `_writing_brief(user)` helper; `business_context` added to follow-up + demand params.
- **`backend/app/services/vertex_ai.py`**
  - `draft_follow_up_email` and `generate_payment_demand` now append `params["business_context"]` to the prompt when present (brand-voice-aware emails).

### Frontend (tsc --noEmit → exit 0)
- **`frontend/lib/api/types.ts`**: added `BusinessType` union, nested interfaces (`BrandIdentity, Offering, BuyerPersona, Customers, TeamMember, Operations, SocialAccount, Marketing, LegalFinancial`), extended `BusinessProfile`, new `ProfileCompleteness`.
- **`frontend/components/settings/profile/templates.ts`** (NEW): `visibleTabs(businessType)`, `TYPE_TABS`, `TAB_LABELS`, `BUSINESS_TYPES`, `CURRENCIES`, `TONES`, `inputCls`, `toList/fromList`. Type→tabs: freelancer sees 5 tabs (no Operations/Marketing); online_seller +Marketing; small_business/agency/startup = all 7.
- **`frontend/components/settings/profile/fields.tsx`** (NEW): `Field, TextField, TextAreaField, RowsEditor<T>` (add/remove editor for arrays-of-objects).
- **`frontend/components/settings/profile-form.tsx`** (REWRITTEN): tabbed shell (Identity · Brand · Offerings · Customers · Operations · Marketing · Legal & finance), live completeness meter, type-driven tab visibility, single merge-safe Save (`PATCH /api/me` + `PATCH /api/profile` with full objects). Array editors for offerings, personas, team, socials.
- **`frontend/components/onboarding/onboarding-wizard.tsx`**: step-1 type list aligned to the 5 canonical values (Users2 icon added).

### Verification already run
- `python -m py_compile` on all changed backend files → OK.
- Runtime smoke (via `backend/venv/Scripts/python.exe`): legacy normalization + `build_profile_brief` briefing/email output + empty-profile "" → OK.
- `app.main` imports; `/api/profile`, `/api/profile/completeness`, `/api/me` register (108 routes).
- `npx tsc --noEmit` → exit 0.

### ⚠️ Phase 1 has NO migration (JSONB is schemaless) — nothing to apply. Just **restart backend** to load the new .py.

---

## ✅ PHASE 2 — Agent Graph Memory — COMPLETE & VERIFIED

Postgres `kg_nodes` + `kg_edges` via the existing dual memory/Supabase store pattern. No graph DB / no new infra. Full write-up in `tracker.md §2.21`.

- **Migration** `backend/migrations/2026-07-16_add_graph_memory.sql` (kg_nodes, kg_edges; RLS like business_playbook).
- **Store**: `upsert_kg_node/edge, get_kg_nodes/edges, delete_kg_for_user` in both backends; re-exported in `store.py`.
- **Service** `backend/app/services/graph_memory.py`: `sync_graph` (idempotent), `ingest_fact`/`ingest_client_fact`, `build_graph_brief`, `query_subgraph`.
- **Retrieval**: graph tier in `playbook.assemble_context`; `query_graph` tool in `supervisor.chat_agentic`; `butler.get_client_detail` → `graphFacts`; observer bridges in `observe_email_intel`/`observe_meeting`; `sync_graph` at top of `run_supervisor`.
- **API** `backend/app/routers/graph.py` (registered in `main.py`): `GET /api/graph`, `POST /api/graph/sync`, `POST /api/graph/run` (cron), `GET /api/graph/client/{id}`. New `graph` job in `.github/workflows/cron.yml` (6:50 UTC).
- **Frontend**: `KgNode/KgEdge/KgGraph` types + "Relationship memory" section on the **What Kora knows** page (`settings/playbook`) via `components/settings/graph-view.tsx` (Rebuild button + per-client relation list).
- **Verified**: py_compile + `app.main` import (112 routes, all `/api/graph/*`); mock smoke (sync 18n/17e, idempotent, briefs, fact ingest, label preserved, context tier); frontend `tsc --noEmit` exit 0.

### ⚠️ Phase 2 needs a migration
- Apply `backend/migrations/2026-07-16_add_graph_memory.sql` in Supabase before graph features work in supabase mode. (Mock mode works with no migration.)

### Documented future upgrades (NOT built)
- NetworkX in-process ranking/pathfinding (pure-Python dep, no infra).
- pgvector semantic recall (uses existing Supabase; "who did we discuss X with").

---

## ✅ FEATURE 3 — Butler communication hub — COMPLETE & VERIFIED (both phases)

Full write-up: `tracker.md §2.22`. Plan: `~/.claude/plans/robust-sprouting-tiger.md`.
- **Phase A**: four comms pages re-homed to `/butler/{calendar,meetings,email,drive}` + `butler/layout.tsx` tab bar; sidebar entries removed; per-client Email/Calendar/Drive tabs in `client-workspace.tsx`; Drive client linkage (migration `2026-07-16_drive_client_link.sql` + `drive_intel._resolve_client_id` + `/cache?client_id=` + `/gmail/intel?client_id=`).
- **Phase B**: `services/butler_comms.py` (draft_client_email / queue_client_email, HITL via existing `send_email_gmail` flow); `POST /api/clients/{id}/compose` + `/queue-email`; EmailTab "Ask Butler to draft…" panel + butler-home "Draft" action (`?tab=email` deep-link).
- Verified: py_compile + app import + mock smoke; frontend tsc exit 0.
- **Needs migration**: `2026-07-16_drive_client_link.sql` in Supabase.

## Live run (2026-07-16)
- **Backend driven live** (isolated mock mode, no prod writes): profile v2 + completeness, graph sync/query, per-client email/drive filters (200), and **Butler compose produced a real LLM draft** citing the actual overdue invoice + client + brand offering; queue-email degraded safely (no Gmail). **Found & fixed a real bug**: `/api/profile/completeness` crashed on a dict profile → now coerces to `BusinessProfile`; re-verified 25% + normalized businessType live.
- **Frontend `next build` exit 0**: route table confirms `/butler/{calendar,meetings,email,drive}` + `/butler/clients/[clientId]` compile and the old `/calendar,/email,/meetings,/drive` are gone.
- **Browser click-through NOT done**: dashboard is behind Supabase-Auth middleware (redirects to `/login`); no test credentials + no Playwright installed. Full UI click-through needs a login session (and the migrations applied for the Supabase-only surfaces).

## Live BROWSER test (2026-07-16, demo@kora.app, real Supabase)
Drove the real UI with Playwright/Chromium against the running app (backend :8000 already up with graph migration applied). All screenshots in scratchpad/e2e/shots.
- ✅ Login → dashboard; sidebar has NO Calendar/Email/Meetings/Drive.
- ✅ Butler hub tab bar (Clients·Calendar·Meetings·Email·Drive); hidden on client-detail page.
- ✅ Client workspace: all per-client tabs render (…·Meetings·Email·Calendar·Drive·…).
- ✅ Profile v2: completeness meter (13%) + all 7 tabs + Brand fields.
- ✅ **Butler compose end-to-end in-browser**: real draft to real contact ("Hi Bikash… website redesign & brand refresh…"), editable subject/body, "Approve & queue" present.
- 2 fixes made during testing: (a) `/api/profile/completeness` coerces dict→BusinessProfile; (b) `/api/drive/cache` falls back when `client_id` column absent (pre-migration). **These need a backend restart on your machine to take effect.**
- Gotchas noted: CORS allows only `:3000/:3001` (run the frontend there); Drive per-client needs the drive migration.

## ✅ FEATURE 4 — Hybrid semantic memory (recall) — COMPLETE & VERIFIED

Full write-up: `tracker.md §2.23`. The meaning-based recall layer the agents lacked — a durable `agent_memory` index queried for planning/decisions, hybrid-ranked (semantic + lexical + salience + recency). No new infra (JSONB embeddings, Python scoring; pgvector ANN is a later drop-in).
- **New**: `services/embeddings.py` (gateway wrapper, graceful), `services/memory_recall.py` (remember/recall/build_recall_brief/reindex/stats), `routers/memory.py`, migration `2026-07-16_add_semantic_memory.sql`.
- **Store**: `upsert/get/delete agent_memory` in both backends + `store.py` re-exports.
- **Writers**: `graph_memory.ingest_fact` + `gmail_intel` (live); Playbook via daily reindex.
- **Readers**: recall tier in `assemble_context`; `recall_memory` supervisor tool; `butler_comms` draft grounding.
- **Config**: `EMBEDDING_MODEL` default `azure.text-embedding-3-small` (confirmed on the gateway, 1536-dim). Falls back to lexical-only if embeddings unavailable.
- **Verified**: py_compile + app import (131 routes); mock smoke (lexical/scoping/semantic/reindex); **live gateway** paraphrase recall with zero lexical overlap ranked the right memory top (sim 0.46/lex 0.0).
- **⚠️ Needs migration**: `2026-07-16_add_semantic_memory.sql` in Supabase (mock needs none).

## Standing reminders
- **Restart backend** to load all new .py (Profile v2, Graph memory, Butler comms hub) — incl. the completeness fix.
- **Apply migrations in Supabase**: `2026-07-16_add_graph_memory.sql`, `2026-07-16_drive_client_link.sql`, and the still-pending `2026-07-15_gmail_intel_upgrades.sql`.
- Remaining manual check: a logged-in browser pass of the Butler tabs + per-client comms once migrations are applied.
- Backlog (implement only when asked): plan gating §5.10, GCP Cloud Run §5.9, automated tests §5.6.

## Handy commands
- Backend venv python: `backend/venv/Scripts/python.exe`
- Backend compile-check: `python -m py_compile app/<file>.py`
- Frontend typecheck: `cd frontend && npx tsc --noEmit`
