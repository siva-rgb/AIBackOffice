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
2. **The Client Canvas is the product's differentiator** and is the reason the
   `feature/project-management` branch exists. It answers "why would I use this instead of Notion?" —
   Notion is empty until a human fills it; KORA fills itself from Gmail/Stripe/transcripts/graph.

> **Product rule to apply when scoping any future milestone:** *can the agent maintain this surface
> without the user typing?* If no, it is a container the user has to fill — Notion already won that,
> don't build it. This is why we are NOT building a block editor, wiki, generic databases, or
> sprint/story/epic ceremony (that is Jira vocabulary for engineering teams; the target user is a
> freelancer with four clients).

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
  2. Covers, in mock mode: `memory_recall` hybrid ranking + **lexical fallback when embeddings are unavailable**; `task_ledger` auto-capture **idempotency** for meeting/email/contract + `build_task_brief` single-listing of an overdue+blocked task; `notion_connector` pure mapping round-trip (`task_to_properties` → `page_to_patch`) + **the multi-tenant `_token()` isolation guard returning None**; `_profile_completeness` accepting a raw dict profile.
  3. **Zero network and zero secrets** — `embeddings.embed` monkeypatched, no Notion/Supabase/LLM calls. Suite passes from a cold checkout.
  4. `pytest.ini` pins `asyncio_default_fixture_loop_scope` (kills the upgrade-behaviour warning flagged in `LOOPS.md`).
  5. `cd frontend && npx tsc --noEmit` still exits 0.
- **Loops:** L1, L4
- **Skills:** canon + `test-driven-development` + production-readiness
- **Token budget:** 50000
- **⚠ Note:** this supersedes the harness-creation that the old M1 carried inside its own boundary; M2 (plan gating) now inherits a working harness.

### M1 — Client Canvas (the agent-composed client one-pager)
- **Outcome:** Opening a client shows a living, agent-maintained picture of the relationship — money, open work, commitments, risks, and next actions — composed from data KORA already holds, with **zero user typing**.
- **Phase (swe-master):** set at L1 start by routing through `agentic-swe-master` (product/AI feature; likely 9 + 19 overlap). Do not invent a number before routing.
- **Files / freeze boundary:** `backend/app/services/client_canvas.py` (new) · `backend/migrations/2026-07-23_add_client_canvas.sql` (new) · `backend/app/routers/clients.py` · `backend/app/backends/{memory_store,supabase_store}.py` · `backend/app/store.py` · `frontend/components/butler/client-canvas.tsx` (new) · `frontend/components/butler/client-workspace.tsx` · `frontend/lib/api/types.ts` · `backend/tests/test_client_canvas.py`
- **Demo command:** `cd backend && KORA_DATA_BACKEND=mock venv/Scripts/python.exe -m pytest tests/test_client_canvas.py -q`
- **Architecture (agreed before planning — deterministic gather → ONE LLM call):**
  - `gather_canvas_state()` — **no LLM.** Reuses `butler.get_client_detail` (health, financials, invoices, engagements, tasks), `email_intel_cache`, meetings + action items, `graph_memory.query_subgraph`, client-scoped `memory_recall.recall`, `get_playbook_for_client`.
  - `suggest_actions()` — **deterministic rules**, each returning a *typed* action bound to a real record id (`chase_invoice`/`draft_email`/`create_task`/`unblock_task`) so the UI wires a real button. Never model-invented.
  - `compose_canvas()` — exactly **one** LLM call producing only a 2–3 sentence narrative + risk read, passed through the existing `validate_briefing`-style guard.
- **Success criteria:**
  1. `gather_canvas_state` returns the money/work/commitments/risks blocks from the real stores with **no LLM call** (assert the provider is never invoked).
  2. Every action from `suggest_actions` carries a payload id that resolves to a real record; a client with no data yields an empty action list, not invented ones.
  3. **Figures are never model-authored** — a test feeds a narrative containing a wrong amount and asserts the validator strips/corrects it.
  4. `GET /api/clients/{id}/canvas` serves the cache with **zero LLM calls**; `POST .../canvas/refresh` recomposes.
  5. Degrades safely: a client with no email intel / no graph / no tasks still renders a canvas.
  6. `cd frontend && npx tsc --noEmit` exits 0.
- **Loops:** L1, L4
- **Skills:** canon + `llmops-ai-agents` + modular-architecture + design-system skill (frontend)
- **Token budget:** 50000
- **Open decisions to resolve at L1 start (default = the recommendation, override at kickoff):**
  - (a) Canvas **replaces** the Overview tab (default) vs. added as a separate first tab. Recommendation: replace — two overlapping summaries is worse than one good one.
  - (b) Narrative is **LLM-composed** (default, 2–3 sentences only) vs. fully deterministic/templated.

### M2 — Enforce plan gating
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

### M3 — Regression suite over the critical paths
- **Outcome:** Broadens M0's harness to the *older* critical paths (M0 covered the recently-shipped features) and wires a CI test job.
- **Phase:** 9 — Evaluation Systems
- **Files:** `backend/tests/**` · `.github/workflows/` (add a test job) — `pytest.ini` already exists from M0
- **Demo command:** `cd backend && KORA_DATA_BACKEND=mock venv/Scripts/python.exe -m pytest -q`
- **Success criteria:** covers Stripe webhook signature verification, `agent_logger` attribution, the CSV parser, the cashflow forecast string-coercion regression (fixed 2026-05-30 — pin it), and cross-module contract-signed → invoice creation. Suite green from a cold checkout with zero secrets.
- **Loops:** L1, L3 (research: what a 3-level eval plan means for an agentic app), L4
- **Skills:** canon + llmops-ai-agents + production-readiness
- **Token budget:** 50000

### M4 — Containerize the frontend + Cloud Run deploy config
- **Outcome:** Both services are containerized and deployable to Cloud Run; the backend already is, the frontend is not.
- **Phase:** 13 — Infrastructure & Deployment
- **Files:** `frontend/Dockerfile` (new) · `frontend/.dockerignore` (new) · `backend/.dockerignore` (new) · `frontend/next.config.mjs` (`output: 'standalone'`) · `cloudbuild.yaml` (new) · `DEPLOY.md` (new)
- **Demo command:** `docker build -t kora-frontend ./frontend && docker run --rm -d -p 3000:3000 --name kora-fe kora-frontend && curl -fsS localhost:3000 >/dev/null && echo DEMO-PASS`
- **Success criteria:** frontend image builds and serves; `.dockerignore` excludes `venv/`, `node_modules/`, `.next/`; `DEPLOY.md` documents that **`NEXT_PUBLIC_API_URL` is build-time baked** → backend deploys first, its URL becomes a frontend build-arg; CORS accepts the prod origin via `FRONTEND_ORIGIN` instead of hardcoded `localhost:3000`.
- **Loops:** L1, L2 (debug — container builds fail in novel ways), L4
- **Skills:** canon + production-readiness + distributed-systems
- **Token budget:** 50000
- **⚠ Blocked on environment:** Docker 29.1.5 is installed but the **daemon was not running** at genesis. Start Docker Desktop before this milestone, or the demo command cannot be computed.

### M5 — Wire digest / alert email delivery behind an approval gate
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
