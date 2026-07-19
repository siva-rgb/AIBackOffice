---
name: kora-butler
description: >
  Build the Kora AI Butler — a proactive AI business partner for freelancers, micro-businesses,
  side hustlers, and online sellers. Use this skill whenever building any part of the Butler
  feature: the client entity layer, quick-capture system, morning briefing, butler agent,
  proposal generator, retainer tracking, or any related backend service, database migration,
  frontend page, or AI prompt. Also use when asked to extend, fix, test, or integrate the
  Butler with existing Kora modules (Supervisor, invoices, contracts, bookkeeping, cash flow).
  Triggers on phrases like "butler", "business manager", "client entity", "quick capture",
  "morning briefing", "client profile", "engagement", "retainer", "proposal", "client health",
  or any request to make Kora understand a user's business context or client relationships.
---

# Kora AI Butler

> "An AI that knows your business the way a great chief of staff would."

The Butler is NOT a project management tool. It is a context and intelligence layer that sits
above all existing Kora agents. Its job: understand the user's full business — clients, work,
money, goals — and act on their behalf without being asked.

Read the reference files for deep implementation details:
- `references/schema.md`       — All new DB tables + migration SQL
- `references/backend.md`      — FastAPI services, routes, worker patterns
- `references/agent-prompts.md`— All Gemini prompt templates
- `references/frontend.md`     — Page specs, component patterns, UX rules

---

## 1. What this feature is

The Butler extends Kora from a financial back-office into a full AI business partner. It adds:

1. **Client entity** — clients become real DB objects (not just strings on invoices)
2. **Engagement layer** — lightweight "what work is happening" context per client
3. **Quick capture** — freeform notes the AI parses into structured business state
4. **Morning briefing** — one daily AI output combining financial + work + client state
5. **Proposal generator** — closes the top of the deal funnel (proposal → contract → invoice)
6. **Retainer tracking** — recurring revenue that makes cash flow forecasts reliable
7. **Butler agent** — the orchestrating brain that runs the above and feeds the Supervisor

The Butler does NOT build a kanban board, task manager, or PM tool. Context capture must
take < 30 seconds. If it requires more effort than that, users won't sustain it.

---

## 2. Integration with existing Kora

The Butler is additive — it does not replace or break existing modules.

```
Existing modules (unchanged):
  bookkeeper · invoice_agent · contract_generator · cashflow_agent
  alert_agent · supervisor · cross_module triggers

New Butler modules (additive):
  client_entity   → promotes client from string to DB object
  engagement      → lightweight work-in-progress context
  quick_capture   → freeform note → AI-parsed state update
  morning_briefing→ unified daily AI output (extends daily_digest)
  proposal_agent  → new document type, feeds contract_generator
  retainer_agent  → recurring income, feeds cashflow_agent
  butler_agent    → orchestrates all of the above + feeds supervisor
```

Integration points (touch existing code minimally):

| Existing module | What changes |
|---|---|
| `invoices` | Add `client_id FK` column (nullable, backward compatible) |
| `contracts` | Add `client_id FK` column + `proposal_id FK` (both nullable) |
| `transactions` | Add `client_id FK` column (nullable, for retainer income tagging) |
| `daily_digest worker` | Extend to include client health + butler briefing section |
| `supervisor` | Add `client_context` to `gather_state()` — reads client + engagement data |
| `agent_logs` | Add `butler` to the `agent_type` CHECK constraint |

Never rewrite existing working modules. Add columns as nullable. Add FK constraints with
`ON DELETE SET NULL` so existing records without clients are unaffected.

---

## 3. Core data model (summary)

Five new tables. Full SQL in `references/schema.md`.

```
clients          — the client entity (replaces free-text client_name strings)
engagements      — what work is happening per client (lightweight, not task manager)
quick_captures   — raw freeform notes before AI parsing
proposals        — pre-contract documents (feeds contract_generator)
retainers        — recurring income records (feeds cashflow_agent)
```

Supporting column additions to existing tables:
```
invoices.client_id          FK → clients.id  (nullable)
invoices.proposal_id        FK → proposals.id (nullable)
contracts.client_id         FK → clients.id  (nullable)
contracts.proposal_id       FK → proposals.id (nullable)
transactions.client_id      FK → clients.id  (nullable)
transactions.retainer_id    FK → retainers.id (nullable)
users.butler_memory         JSONB (rolling summary for briefing continuity)
```

---

## 4. Build order

Build strictly in this order. Each phase is independently shippable.

**Phase 1 — Client entity (Days 1–3)**
Foundation everything else depends on. Thin profile, not a PM tool.
Read `references/backend.md#phase-1` and `references/schema.md#clients`.

**Phase 2 — Quick capture (Days 4–6)**
The interaction model that makes the Butler feel alive.
Read `references/backend.md#phase-2` and `references/agent-prompts.md#quick-capture`.

**Phase 3 — Morning briefing (Days 7–10)**
The primary user-facing output. Extends daily_digest worker.
Read `references/backend.md#phase-3` and `references/agent-prompts.md#morning-briefing`.

**Phase 4 — Proposal generator (Days 11–15)**
Closes top of the deal funnel. Reuses contract_generator infrastructure.
Read `references/backend.md#phase-4` and `references/agent-prompts.md#proposal`.

**Phase 5 — Retainer tracking (Days 16–18)**
Makes cash flow reliable. Simple new table + agent logic.
Read `references/backend.md#phase-5` and `references/agent-prompts.md#retainer`.

**Phase 6 — Butler agent + Supervisor integration (Days 19–22)**
Wires everything together. Butler feeds Supervisor's `gather_state()`.
Read `references/backend.md#phase-6`.

---

## 5. Absolute rules (never violate)

These apply to every file you touch in this feature:

1. **All Gemini calls go through `services/vertex_ai.py` `generate_with_retry()`** — never call
   Vertex AI directly. Never use OpenAI or Anthropic SDK anywhere in this project.

2. **All Gemini calls log to `agent_logs`** — call `agent_logger.log_action()` after every
   single AI call. No exceptions. `agent_type` = `'butler'` for all Butler agent calls.

3. **All user-supplied text entering prompts goes through `sanitize_prompt_input()`** — this
   includes quick_capture notes, client names, engagement descriptions, proposal details.

4. **All routes use `get_current_user()` dependency** — never skip auth on any endpoint.

5. **All request bodies use Pydantic v2 models** — never accept raw dicts in route handlers.

6. **Client-facing actions require HITL approval** — anything that emails a client or modifies
   money state goes into `manager_tasks` with `status='proposed'`, not auto-executed.

7. **New DB columns are nullable with `ON DELETE SET NULL`** — never break existing records.

8. **New FK columns are backward compatible** — existing invoices/contracts without a client_id
   continue to work exactly as before.

9. **Quick capture parsing degrades gracefully** — if AI parsing fails, save the raw note text
   and flag it as `parse_status='failed'`. Never lose user input.

10. **Morning briefing uses ONE Gemini call** — gather all data deterministically, then one LLM
    call to compose the narrative. Do not chain LLM calls in the briefing path.

---

## 6. Security rules (butler-specific additions)

These extend the security rules in the main SKILL.md.

- Rate limit quick_capture: 50 per day per user (prevent prompt injection via bulk notes)
- Rate limit proposal generation: 10 per hour per user (same as contract generation)
- Sanitize all freeform text (client names, engagement descriptions, note content) before
  any DB insert — strip control characters, enforce max length (2000 chars for notes)
- Client health scores are computed server-side only — never trust client-supplied scores
- The butler_memory JSONB field must be server-written only (never accept from client)
- Quick capture notes that match INJECTION_PATTERNS in `security.py` → reject with 400,
  log the attempt, do NOT save the note

---

## 7. AI cost controls

The Butler adds new Gemini calls. Stay within budget:

| Operation | Calls per run | Max tokens | Schedule |
|---|---|---|---|
| Quick capture parsing | 1 per note | 500 output | On user action |
| Client health score | 1 per client | 400 output | Daily, batched |
| Morning briefing | 1 per user | 1500 output | Daily 07:00 UTC |
| Proposal generation | 1 per proposal | 4096 output | On user action |
| Retainer income categorization | Batch with bookkeeper | — | On CSV upload |

Use `getGeminiForAgent('butler')` from `services/vertex_ai.py`. Add `'butler': 600` to the
TOKEN_BUDGETS dict for client health + quick capture calls. Proposals use `'contract': 4096`.

---

## 8. Testing requirements

Every Butler module needs tests before moving to the next phase.

Priority 1 (must have): quick_capture parsing edge cases — empty note, injection attempt,
note that maps to multiple clients, note with no recognizable entity.

Priority 2: client health score — verify it updates when invoice goes overdue, verify it
degrades gracefully when engagement data is missing.

Priority 3: morning briefing — verify it generates even with zero clients, verify it includes
all sections (financial + client + decisions pending).

Priority 4: proposal → contract cross-module link — verify contract.proposal_id is set when
contract is generated from a proposal.

Use pytest. Test files live in `backend/tests/`. Follow patterns in existing test files.

---

## 9. Frontend conventions

Follow all rules in main SKILL.md §9. Butler-specific additions:

- New sidebar item: "Butler" (icon: `ti-robot`) between Dashboard and Bookkeeping
- Client list uses health score color: green (≥75), amber (50–74), red (<50)
- Quick capture is a floating action or persistent input — always one click away
- Morning briefing card appears at top of Butler page and Dashboard overview
- Empty states must be motivating, not clinical — see `references/frontend.md#empty-states`
- All Butler pages load client data via React Server Components — no client-side fetching
  for initial page load

Status color conventions (extend existing):
```
client status:     active=green, inactive=gray, prospect=blue, churned=red
engagement status: active=blue, on_track=green, at_risk=amber, done=gray, paused=gray
health score:      ≥75=green, 50-74=amber, <50=red
proposal status:   draft=gray, sent=blue, accepted=green, declined=red, expired=gray
retainer status:   active=green, paused=amber, cancelled=gray
```
