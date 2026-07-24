# PLAN — KORA

The machine-parseable implementation plan. Mirrors the milestone table in `DONE.html` (DONE.html is the
human/visual view; this is the one loops read). Sliced so each milestone ships in one L1 BUILD pass.

> Slicing rule: a milestone must have (a) a single clear outcome, (b) an exact **demo command** that
> proves it, and (c) a freeze boundary of files it may touch. If you can't write the demo command,
> the milestone is too vague — split it.

---

## Brainstorm (G0.5 — filled 2026-07-23)

> Scope is **extend**, so the brainstorm is scoped to the current increment's cognitive job:
> **how does KORA decide, server-side and auditably, that a given user may invoke a given capability?**
> Billing plumbing already exists (`stripe_billing.py`, `require_plan`, `contract_credits`) but
> **restricts nothing** — no premium route is gated. That is the problem being solved.

### Approach A — Per-route dependency
Apply `Depends(require_plan("pro"))` directly on each premium route across the 27 router modules.
The gate lives where the capability is exposed, using the factory that already works today.
- Strengths: explicit and greppable; zero new abstraction; reuses working code; the gate is visible at the point of use.
- Weaknesses: **fails open** — a new premium route added later is ungated by default and nothing catches it; plan tiers end up scattered across 27 files, so "what does Pro include?" has no single answer.

### Approach B — Central entitlements policy + per-route application
A single `app/entitlements.py` declares `feature → minimum plan`. Routes derive their gate from that
table. A test asserts every premium route resolves to a policy entry.
- Strengths: one **auditable policy artifact** (satisfies the kit's core rule #2, "security policy before mechanism"); pricing changes in one place; coverage is machine-checkable, so it can fail *closed*.
- Weaknesses: one layer of indirection between route and rule; the policy table can drift from reality if the coverage test is ever deleted.

### Approach C — Capability / credit ledger at the service layer
Move the gate inside the services (e.g. contract generation checks `contract_credits` itself), so the
check fires regardless of entry point — HTTP, cron, or agent tool-call.
- Strengths: gates the actual expensive operation, not just the front door; agent tool-calls and cron paths are covered for free; metered credits model naturally.
- Weaknesses: largest change by far; surfacing a clean 403 to HTTP from deep in a service is awkward; slowest to ship, and the MVP's agent/cron paths aren't user-billable yet anyway.

### Chosen: **B, implemented with A's mechanism** — a central `entitlements.py` policy table, applied per-route via the existing `require_plan` dependency.
Rationale: it is the only option that produces a **single auditable artifact** answering "who may do
what" (the Phase 11 gate wants exactly that) while keeping the gate visible at the route and reusing
code that already works. A alone fails open; C is the right eventual destination but is out of
proportion to an MVP whose cron and agent paths are not yet user-billable — revisit C when agent
tool-calls become independently billable.

---

## Re-plan (2026-07-23, at user request)

Two milestones were inserted ahead of the original backlog. Rationale, recorded so a future loop
doesn't undo it:

1. **Five features shipped between §2.20–§2.24 of `docs/specs/tracker.md` have ZERO regression tests.**
   They were each verified with throwaway smoke scripts that proved they worked *that day* and were
   then discarded. Nothing protects them now, and G4's pytest half cannot pass at all (`exit 5`), so
   the anti-slop spine is decorative until a harness exists. **M0 fixes this first.**
2. **Agent-maintained client & project intelligence is the product's differentiator** and is the
   reason the `feature/project-management` branch exists. It answers "why would I use this instead of
   Notion?" — Notion is empty until a human fills it; KORA fills itself from Gmail/Stripe/
   transcripts/graph. Expanded on 2026-07-23 into the **M1–M4 arc** (see ADR-0001); the originally
   planned standalone "Client Canvas" milestone was absorbed into **M4**.

> **Product rule to apply when scoping any future milestone:** *can the agent maintain this surface
> without the user typing?* If no, it is a container the user has to fill — Notion already won that,
> don't build it. This is why we are NOT building a block editor, wiki, or generic databases.
>
> **Amended 2026-07-23 (ADR-0001):** a `Story` level under `Task` **is** being built, which an earlier
> version of this rule discouraged as "Jira ceremony." The amendment is deliberate and conditional:
> stories pass the rule **only because every qualitative field is agent-authored from evidence with
> provenance** (`going_well` / `not_going_well` / `blockers` each cite a source record). A story layer
> that users had to fill by hand would fail the rule and must not be built. Depth concern was raised
> and the user reaffirmed — proceeding.

Notion's role is settled and **not** to be extended: KORA's `tasks` table is canonical, Notion is an
optional mirror via `external_ref`. Keep it working; stop investing in it.

---

## Milestones

### M0 — Test harness + regression cover for the shipped features
- **Outcome:** `pytest` actually runs (not `exit 5`), and the five recently-shipped features have regression tests. G4's pytest half becomes a real gate instead of a waived one.
- **Phase (swe-master):** 9 — Evaluation Systems
- **Files / freeze boundary:** `backend/conftest.py` (new) · `backend/pytest.ini` (new) · `backend/tests/**` (new). **No production code changes** — if a test fails, that is a finding to surface, not a licence to edit `app/`.
- **Demo command:** `cd backend && KORA_DATA_BACKEND=mock venv/Scripts/python.exe -m pytest -q`
- **Success criteria:**
  1. Exit **0** with a non-zero test count (proves real tests ran, not `exit 5`).
  2. Covers, in mock mode: `memory_recall` hybrid ranking + **lexical fallback when embeddings are unavailable**; `task_ledger` auto-capture **idempotency** for meeting/email/contract + `build_task_brief` single-listing of an overdue+blocked task; `notion_connector` read-only surface + **the multi-tenant `_token()` isolation guard returning None** (the old `task_to_properties`→`page_to_patch` round-trip was removed with the write side in M9); `_profile_completeness` accepting a raw dict profile.
  3. **Zero network and zero secrets** — `embeddings.embed` monkeypatched, no Notion/Supabase/LLM calls. Suite passes from a cold checkout.
  4. `pytest.ini` pins `asyncio_default_fixture_loop_scope` (kills the upgrade-behaviour warning flagged in `LOOPS.md`).
  5. `cd frontend && npx tsc --noEmit` still exits 0.
- **Loops:** L1, L4
- **Skills:** canon + `test-driven-development` + production-readiness
- **Token budget:** 50000
- **⚠ Note:** this supersedes the harness-creation that the old M1 carried inside its own boundary; M2 (plan gating) now inherits a working harness.

## The M1–M4 arc — Agent-maintained client & project intelligence

Governed by **ADR-0001** (accepted 2026-07-23). Read it before starting any of M1–M4.

**G0 finding that shapes the whole arc:** three of the four hierarchy levels **already exist** —
`Client` ✅, `Engagement` ✅ (*is* the Project level: status, dates, budget, `value_delivered`),
`Task` ✅ (client + engagement linked, auto-capture, Notion mirror). Only **Story is unbuilt**.
`ClientNote.note_type` already covers `meeting|call|email|decision|blocker|update|general`; meeting
scheduling exists via HITL `create_calendar_event`; payment discussion exists via invoices + email
`financial_mentions`. **Extend these. Do not create a parallel hierarchy.**

The standalone "Client Canvas" milestone was **absorbed into M4** — the agent-maintained client view
*is* the top of this pyramid, so building both would duplicate work.

### M1 — Story level + evidence-backed qualitative status
- **Outcome:** A `Story` entity under `Task`, carrying `progress_pct` and qualitative status where **every entry cites its evidence**. This is the layer that makes the hierarchy self-filling rather than another empty container.
- **Phase (swe-master):** route at L1 start via `agentic-swe-master`. Do not invent a number.
- **Files / freeze boundary:** `backend/app/models.py` · `backend/migrations/2026-07-23_add_stories.sql` (new) · `backend/app/backends/{memory_store,supabase_store}.py` · `backend/app/store.py` · `backend/app/services/story_ledger.py` (new) · `backend/app/routers/stories.py` (new) · `backend/app/main.py` · `backend/tests/test_stories.py` (new)
- **Demo command:** `cd backend && KORA_DATA_BACKEND=mock venv/Scripts/python.exe -m pytest tests/test_stories.py -q`
- **Success criteria:**
  1. `Story` CRUD under a parent `task_id`; deleting a task defines an explicit cascade rule (documented, tested).
  2. `progress_pct` constrained 0–100; `blockers` / `going_well` / `not_going_well` are lists of `{text, source, source_ref, observed_at, user_edited}`.
  3. **A qualitative entry with no `source_ref` is refused** — enforces the `qualitative_fields_carry_provenance` invariant (ADR-0001).
  4. **`user_edited = true` survives an agent refresh** — a simulated refresh must not mutate or delete it (invariant `user_override_survives_agent_refresh`).
  5. `cd frontend && npx tsc --noEmit` still exits 0.
- **Loops:** L1, L4 · **Skills:** canon + modular-architecture + tdd · **Budget:** 50000

### M2 — Deterministic roll-up health (story → task → project → client)
- **Outcome:** Project and client health finally reflect **delivery**, not just money and silence. Today `compute_client_health` reads invoices/engagements/staleness only.
- **Files / freeze boundary:** `backend/app/services/rollup.py` (new) · `backend/app/services/butler.py` (extend `compute_client_health`) · `backend/tests/test_rollup.py` (new)
- **Demo command:** `cd backend && KORA_DATA_BACKEND=mock venv/Scripts/python.exe -m pytest tests/test_rollup.py -q`
- **Success criteria:**
  1. Changing one story's `progress_pct` or adding a blocker moves task → project → client health **arithmetically and predictably**.
  2. **Zero LLM calls** — the test asserts the provider is never invoked (invariant `rollup_health_is_deterministic`).
  3. Delivery signal is **added to**, not substituted for, the existing money/silence signals; the pre-existing health behaviour is pinned by a test so this is a strict extension.
  4. Degenerate inputs are safe: project with no stories, story with no progress, 100% complete with an open blocker — all defined, none crash.
- **Loops:** L1, L4 · **Skills:** canon + production-readiness · **Budget:** 50000

### M3 — PM agent fan-out (role-scoped analysts + deterministic merge)
- **Outcome:** The "team of specialists" that keeps the view current — four narrow analysts run in parallel and a **code** synthesizer merges them.
- **Files / freeze boundary:** `backend/app/services/pm_agent.py` (new) · `backend/migrations/2026-07-23_add_client_view_cache.sql` (new) · `backend/app/routers/clients.py` · `.github/workflows/cron.yml` · `backend/tests/test_pm_agent.py` (new)
- **Demo command:** `cd backend && KORA_DATA_BACKEND=mock venv/Scripts/python.exe -m pytest tests/test_pm_agent.py -q`
- **Architecture:** analysts = **Delivery** (stories/tasks/blockers/progress) · **Money** (invoices/payments/forecast) · **Relationship** (email sentiment, silence, commitments) · **Risk** (what's not going well). Each gets a narrow tool subset and its own prompt. **The merge is deterministic code, never an LLM.**
- **Success criteria:**
  1. Four analysts run **in parallel**; the merge is code (asserted — no LLM call in the merge path).
  2. **One analyst failing degrades only its section** — the other three still populate the view (this is the load-bearing reliability property).
  3. **No figure originates from an LLM** — a test injects a wrong amount into an analyst response and asserts the validator strips/corrects it.
  4. `GET` serves cache with **zero LLM calls**; `POST .../refresh` recomposes; nightly cron job added (invariant `client_view_refresh_is_cached`).
  5. Token cost per client refresh is **measured and asserted under a cap** — fan-out multiplies calls, so this is a real budget gate, not a nicety.
- **Loops:** L1, L4 · **Skills:** canon + `llmops-ai-agents` + production-readiness · **Budget:** 50000

### M4 — Client workspace UI (hierarchy + client-level surfaces) — *absorbs the Client Canvas*
- **Outcome:** The full picture in one place: `Client → Project → Task → Story` with roll-up health, plus the client-level surfaces (payment discussion, general discussion, key notes, meeting scheduling) wired to what already exists.
- **Files / freeze boundary:** `frontend/components/butler/{client-canvas,project-tree,story-card}.tsx` (new) · `frontend/components/butler/client-workspace.tsx` · `frontend/lib/api/types.ts`
- **Demo command:** `cd frontend && npx tsc --noEmit && npm run build`
- **Success criteria:**
  1. Tree renders Client → Project → Task → Story with per-level roll-up health.
  2. Qualitative entries show **provenance** ("from meeting 12 Jul") and **staleness**, so an old judgement never reads as current.
  3. A user edit marks the entry `user_edited` and visibly distinguishes it from agent-authored content.
  4. Client-level surfaces **reuse existing endpoints** — `ClientNote` note types for discussion/key notes, HITL `create_calendar_event` for scheduling, invoices/`financial_mentions` for payment. No new note system.
  5. `npx tsc --noEmit` exit 0 and `npm run build` succeeds.
- **Loops:** L1, L4 · **Skills:** canon + design-system skill (**mandatory** for frontend) + qa · **Budget:** 50000
- **Decision carried from the Canvas plan:** the composed client view **replaces** the Overview tab (two overlapping summaries is worse than one good one).

### M9 — Notion as a read-only intelligence source (repurpose the connector)
- **Outcome:** A user who already lives in Notion connects it (read-only), picks which pages/databases to share, and Kora **ingests that content into `agent_memory`** (the hybrid semantic memory). The agent then surfaces Notion facts via recall — in the PM analysts, client view and chat. Kora **never writes to Notion**. Decided 2026-07-24: (1) ingest-into-memory (not compose-time re-read, not auto-capture); (2) user-picks pages; (3) the old two-way write path is **removed**, not left dormant.
- **Files / freeze boundary:** `backend/app/services/notion_connector.py` (strip write side; keep OAuth+read; add `read_page_text` + page selection) · **new** `backend/app/services/notion_ingest.py` · `backend/app/routers/notion.py` (drop `/provision` + `/sync`; add select + ingest) · `backend/migrations/2026-07-24_notion_ingest.sql` (add `ingest_page_ids` to `notion_connections`) · `backend/app/backends/{memory,supabase}_store.py` + `app/store.py` (targeted `delete_agent_memory` by kind) · `backend/app/services/pm_agent.py` (analysts consume a recall brief incl. Notion) · `.github/workflows/cron.yml` (repurpose the notion job to ingest) · `frontend/components/settings/notion-connect-card.tsx` · `backend/tests/test_notion_ingest.py` (new)
- **Demo command:** `cd backend && KORA_DATA_BACKEND=mock venv/Scripts/python.exe -m pytest tests/test_notion_ingest.py -q`
- **Success criteria:**
  1. **Read-only, provably:** no write path to Notion exists — `provision_tasks_db`/`push_task`/`sync` are gone, the removed endpoints 404, and a grep for Notion writes (`POST /pages`, `PATCH /pages`, `/databases`) is empty.
  2. **Ingest + idempotent:** selected pages land in `agent_memory` as `kind="notion"` with page-id/URL provenance; re-ingest updates rather than duplicates (unique `(user_id, kind, ref_id)`).
  3. **The agent uses it (the demo):** a fact that exists ONLY in a Notion page is recalled into the composed client view / a recall brief — proving intelligence, not dead data.
  4. **Privacy:** disconnect purges that user's `kind="notion"` memories (and only those).
  5. **Graceful:** no embeddings → lexical fallback; not connected → no-op, never raises.
  6. `pytest` green (no regression), `npx tsc --noEmit` 0, `npm run build` succeeds.
- **Loops:** L1, L4 · **Skills:** canon + llmops-ai-agents + production-readiness · **Budget:** 50000

### M5 — Enforce plan gating
- **Outcome:** Premium capabilities reject free-plan users server-side, driven by one auditable entitlements policy. Billing stops being decorative.
- **Phase (swe-master):** 11 — Security Architecture
- **Files / freeze boundary:** `backend/app/entitlements.py` (new) · `backend/app/dependencies.py` · `backend/app/routers/{contracts,cashflow,butler,memory,graph}.py` · `backend/tests/` + `backend/conftest.py` (new)
- **Demo command:** `cd backend && KORA_DATA_BACKEND=mock venv/Scripts/python.exe -m pytest tests/test_plan_gating.py -q`
- **Success criteria:**
  1. A `free` user receives **403** from every route the policy marks premium.
  2. A `pro` user receives a non-403 from those same routes.
  3. A coverage test asserts **every** premium route resolves to a policy entry — adding an ungated premium route fails the suite.
  4. `cd frontend && npx tsc --noEmit` still exits 0.
- **Loops:** L1, L4
- **Skills:** canon + security-engineering + production-readiness
- **Token budget:** 50000
- **⚠ Prerequisite — now satisfied by M0:** the pytest harness (`conftest.py`, `pytest.ini`, `tests/`) is created in **M0**, so this milestone inherits a working one and only adds `tests/test_plan_gating.py`. The seeded demo user is `plan="pro"` (`app/seed.py:50`), so the free-user case **must** be produced by overriding `get_current_user` via `app.dependency_overrides` — it cannot be reached with plain curl in mock mode.

### M6 — Regression suite over the critical paths
- **Outcome:** Broadens M0's harness to the *older* critical paths (M0 covered the recently-shipped features) and wires a CI test job.
- **Phase:** 9 — Evaluation Systems
- **Files:** `backend/tests/**` · `.github/workflows/` (add a test job) — `pytest.ini` already exists from M0
- **Demo command:** `cd backend && KORA_DATA_BACKEND=mock venv/Scripts/python.exe -m pytest -q`
- **Success criteria:** covers Stripe webhook signature verification, `agent_logger` attribution, the CSV parser, the cashflow forecast string-coercion regression (fixed 2026-05-30 — pin it), and cross-module contract-signed → invoice creation. Suite green from a cold checkout with zero secrets.
- **Loops:** L1, L3 (research: what a 3-level eval plan means for an agentic app), L4
- **Skills:** canon + llmops-ai-agents + production-readiness
- **Token budget:** 50000

### M7 — Containerize the frontend + Cloud Run deploy config
- **Outcome:** Both services are containerized and deployable to Cloud Run; the backend already is, the frontend is not.
- **Phase:** 13 — Infrastructure & Deployment
- **Files:** `frontend/Dockerfile` (new) · `frontend/.dockerignore` (new) · `backend/.dockerignore` (new) · `frontend/next.config.mjs` (`output: 'standalone'`) · `cloudbuild.yaml` (new) · `DEPLOY.md` (new)
- **Demo command:** `docker build -t kora-frontend ./frontend && docker run --rm -d -p 3000:3000 --name kora-fe kora-frontend && curl -fsS localhost:3000 >/dev/null && echo DEMO-PASS`
- **Success criteria:** frontend image builds and serves; `.dockerignore` excludes `venv/`, `node_modules/`, `.next/`; `DEPLOY.md` documents that **`NEXT_PUBLIC_API_URL` is build-time baked** → backend deploys first, its URL becomes a frontend build-arg; CORS accepts the prod origin via `FRONTEND_ORIGIN` instead of hardcoded `localhost:3000`.
- **Loops:** L1, L2 (debug — container builds fail in novel ways), L4
- **Skills:** canon + production-readiness + distributed-systems
- **Token budget:** 50000
- **⚠ Blocked on environment:** Docker 29.1.5 is installed but the **daemon was not running** at genesis. Start Docker Desktop before this milestone, or the demo command cannot be computed.

### M8 — Wire digest / alert email delivery behind an approval gate
- **Outcome:** Daily digests and alerts can actually reach the user, without weakening the "no send without approval" contract.
- **Phase:** 19 — Human-in-the-Loop
- **Files:** `backend/app/services/{alert_agent,gmail_agent,supervisor}.py` · `backend/app/routers/alerts.py` · `backend/tests/test_digest_delivery.py` (new)
- **Demo command:** `cd backend && KORA_DATA_BACKEND=mock venv/Scripts/python.exe -m pytest tests/test_digest_delivery.py -q`
- **Success criteria:** with Gmail connected **and** approval given → a send occurs and the returned note says *Sent* with a `gmailMessageId`; without approval, or without Gmail → **draft-only, no send**, with a clear note; a repeated run does **not** double-send (idempotency); the `no_outbound_send_without_human_approval` invariant still holds.
- **Loops:** L1, L4
- **Skills:** canon + llmops-ai-agents + security-engineering
- **Token budget:** 50000

---

## Progress (loops append here on milestone completion — newest last)

- _(none yet — first loop fills this)_
