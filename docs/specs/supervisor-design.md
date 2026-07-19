# Kora Supervisor — "AI Business Manager" — Requirements & Design Draft

_Status: DRAFT for review (no code written yet) · 2026-05-31_

> One-liner: a goal-aware orchestration layer that sits **above** Kora's point agents, reviews the
> whole business across modules, **does the routine work automatically**, and **asks the owner to
> approve anything client-facing or irreversible** — turning a toolbox of agents into a virtual
> business manager.

---

## 1. The problem & why this is necessary

Today Kora has capable but **independent** agents (bookkeeper, invoice follow-up, contract
generator/reviewer, cash-flow forecaster, alerts, payment reconciliation). Each is triggered on its
own — the owner still has to visit each tab, press buttons, and mentally connect the dots. The cross-
module links that exist (contract→invoice, payment→reconcile) are **fixed if-this-then-that rules**,
not a reasoning manager.

SKILL.md §1 pitches Kora as *"a proactive AI agent platform … that monitors the business 24/7 and
takes action without being asked."* The individual agents exist; **the orchestrating brain does not.**
The Supervisor is that brain.

**Why it matters / value added:**
- **From toolbox → employee.** The owner stops operating tools and instead reviews a manager's
  briefing. One pane of glass instead of six tabs.
- **Nothing falls through the cracks.** Overdue invoices, cash-danger days, unsigned/expiring
  contracts, uncategorized income, missed deductions — all watched and prioritized continuously.
- **Goal alignment.** Ties daily operations to the owner's stated targets (from the Business Profile):
  "You're at $4.2k of your $8k monthly goal; the fastest lever is the $3k Harbor invoice, 12 days overdue."
- **Trust by design.** Routine, reversible work happens automatically; anything that emails a client
  or changes money state waits for a one-click human approval. Every action is in the audit log.
- **Makes the other agents worth more together than apart** — this is the literal payoff of the
  "cross-module intelligence" promise.

---

## 2. What it is (definition)

A **Supervisor agent** that, on a schedule and on demand:
1. **Understands the specific business** — reads `users.profile` (type, industry, goals, payment
   prefs, tone) + live cross-module data.
2. **Reviews the whole state** across bookkeeping, invoices, contracts, cash flow.
3. **Decides what matters now**, prioritized by the owner's goals.
4. **Executes safe actions automatically** by invoking the existing agents as tools.
5. **Escalates critical/irreversible actions** to a **human-in-the-loop approval queue**.
6. **Produces a manager's briefing** — what it did, what needs a decision, where the owner stands vs goals.

Analogy: a diligent operations manager who clears your inbox of routine items overnight and leaves you
a short note: *"Handled these 4 things. Need your OK on these 2. Here's your number for the month."*

---

## 3. Scope

**In scope (Phase 1 — this build):**
- Supervisor service: gather cross-module state → assess (rule-derived findings + candidate actions)
  → execute safe actions → queue risky ones → LLM-composed briefing.
- Human-in-the-loop **approval/decision queue** (persisted) with Approve / Dismiss.
- A **Manager view** (page/dashboard section): briefing, goal progress, pending decisions, recent autonomous actions.
- Triggers: **on-demand button** + **daily scheduler** (same path as the digest).
- Full audit logging + alerts integration.

**Out of scope (Phase 2+, later):**
- Conversational **chat** interface to the manager (ask it questions, give instructions in natural language).
- True **LLM tool-calling planner** (model decides which tools to call autonomously).
- Preference **learning** (it remembers how you like things handled).
- Multi-step autonomous workflows beyond the defined action set.

---

## 4. Architecture & logical implementation

Three candidate approaches were considered:

| Approach | Description | Trade-off |
|---|---|---|
| A. Pure LLM tool-calling planner | LLM loop with agents exposed as callable tools; it reasons + calls them | Most "agentic" & flexible; least predictable, higher cost/latency, hardest to make safe/demo-stable |
| B. Pure deterministic rules engine | Hard-coded rules gather signals → actions | Predictable & cheap; not intelligent, no narrative, doesn't feel like a manager |
| **C. Hybrid (recommended)** | Deterministic state-gathering + rule-derived candidate actions; **LLM does prioritization + the manager's briefing/reasoning** | Reliable & auditable where it matters (money/comms), intelligent & natural where it helps (narrative, ranking). Best risk/value for an MVP. Tool-calling can be layered on later. |

**Recommended: C (hybrid).** Flow of a single supervisor run:

```
run_supervisor(user_id, mode):
  1. gather_state()      → cross-module snapshot (deterministic, no LLM):
                            • profile + goals
                            • P&L / month income / run-rate
                            • invoices: open, overdue (by age), unpaid totals
                            • contracts: unsigned, signed-without-invoices, expiring
                            • cash flow: danger days (14d/30d), projected balance
                            • bookkeeping: uncategorized / low-confidence txns, untagged deductibles
                            • recent agent activity
  2. assess(state)       → list of Findings, each mapped to a candidate Action,
                            tagged AUTO_SAFE or NEEDS_APPROVAL (deterministic rules)
  3. execute safe        → run AUTO_SAFE actions now via existing agents
                            (categorize, reconcile, refresh forecast, draft-only follow-ups)
  4. queue risky         → upsert NEEDS_APPROVAL actions into the decision queue
                            (idempotent: don't re-queue an identical open task)
  5. brief()             → ONE LLM call: compose the manager's narrative —
                            status vs goals, what was handled, what needs a decision, priorities
  6. log + return        → audit to agent_logs; return {briefing, goalProgress, autoActions, pendingTasks}
```

Determinism where it counts (which invoice, how much, did a payment match), LLM where it adds value
(ranking, plain-English briefing, tone). Only **one** LLM call per run → cheap, fast, demo-stable.

---

## 4a. Cross-agent memory model

Kora's agents are **in-process functions** that coordinate through the shared DB (`store.py`), not
separate services with private state and no message bus. The supervisor **organizes existing memory**
and adds continuity — 5 layers:

| Layer | What | Where | Role |
|---|---|---|---|
| 1. World state (system of record) | transactions, invoices, contracts, alerts | DB via `store.py` | the shared memory; all agents read/write here |
| 2. Run context (working memory) | `SupervisorContext` = profile + snapshot, built once per run | in-memory, per run | passed into every tool so all agents act on one consistent view |
| 3. Episodic / audit memory | every action taken (who/what/when/result/cost) | `agent_logs` | supervisor reads recent logs to avoid repeating (idempotency over time) |
| 4. Decision memory | proposed→approved/dismissed | `manager_tasks` (new) | don't re-propose dismissed items; record owner choices |
| 5. Manager memory (continuity) | rolling "state of business" summary + learned prefs | `users.profile._manager_memory` (no new table) | continuity across runs; seeds Phase-2 preference learning |

Principle: **the database is the cross-agent memory.** The supervisor assembles the right slice into a
per-run shared context, persists outcomes back, and keeps a light rolling summary. No vector/semantic
store in Phase 1 (structured data + summary is enough and token-cheap); semantic memory is Phase 2+ only.

## 4b. How the supervisor communicates with & manages agents

Each capability is wrapped behind a **uniform tool interface** and registered with the supervisor:
```
Tool = { name, description, side_effect: AUTO | APPROVAL, run(ctx, params) -> Result }
```
(thin wrappers over existing service functions: send_follow_up, reconcile, refresh_forecast,
draft_demand, review_contract, …)

- **Supervisor → agent (command):** direct **in-process call**, passing shared `ctx` (layer 2) + params.
  No bus/queue. "Management" = choosing which tools, in what order, with what inputs.
- **Agent → supervisor (report):** each tool returns a structured `Result` (did/proposed, records, cost);
  the supervisor aggregates into the briefing + audit.
- **Sequencing/conflict:** supervisor is the **single orchestrator** → safe order (reconcile → then
  follow-ups, so a paid invoice is never dunned). Per-user serialization prevents racing passes.
- **The gate:** AUTO tools execute now; APPROVAL tools are written to `manager_tasks` as proposals and
  only run when the owner clicks Approve (then the supervisor dispatches the same tool to execute).
- **LLM role:** hybrid → rules pick candidate tools, LLM ranks + writes briefing. (Phase-2 tool-calling:
  the same registry is exposed to the LLM as a tool schema and it chooses — identical underlying functions.)

Agents still communicate with each other **only through the database**, never via hidden private channels;
the supervisor is the single top-level coordinator. No message bus / microservices / vector DB — in-process
orchestration + the existing DB is right-sized for a single FastAPI backend.

## 5. Action taxonomy (the manager's "powers")

| Action | Class | Rationale |
|---|---|---|
| Categorize new/low-confidence transactions | **AUTO** | reversible, internal |
| Reconcile incoming payments → mark invoice paid | **AUTO** (already conservative) | internal, conservative match |
| Refresh cash-flow forecast | **AUTO** | read-only computation |
| Draft (not send) follow-up emails | **AUTO** | nothing leaves the building |
| Raise alerts / surface findings | **AUTO** | informational |
| **Send** a follow-up / payment-demand to a client | **APPROVAL** | outward-facing, reputational |
| **Send / mark-signed** a contract | **APPROVAL** | legal/irreversible |
| **Write off / cancel** an invoice | **APPROVAL** | money state, irreversible |
| Anything emailing a client or moving money | **APPROVAL** | trust boundary |

Principle: **a false "auto-sent email to a paying client" is far worse than a missed auto-action.**
When unsure → queue for approval, don't act.

---

## 6. Data model & persistence (⚠ migrations required)

- **Business Profile** — `users.profile` JSONB. _Already built; migration still pending (prerequisite)._
- **Decision/approval queue** — NEW table `manager_tasks`:
  ```
  id, user_id, kind (send_followup|send_demand|send_contract|writeoff_invoice|review_contract|…),
  title, rationale, severity (info|warning|critical), status (proposed|approved|dismissed|done|failed),
  payload JSONB (e.g. {invoiceId}), source_record_type, source_record_id,
  created_at, resolved_at
  ```
  RLS "users see own tasks". This is the HITL backbone.
- **Audit** — reuse `agent_logs`. The `agent_type` CHECK currently lacks `supervisor`; either (a) add it
  via migration, or (b) reuse `cross_module` for MVP (no migration). _Recommend (b) for MVP._
- **Surfacing** — reuse existing `alerts` for informational items.

**Migrations needed:** (1) the pending `profile` column, (2) the `manager_tasks` table. Both are one-time
SQL in the Supabase editor (provided as files). Optional: extend `agent_logs` CHECK for a `supervisor` type.

---

## 7. Triggers
- **On-demand:** "Run manager" button on the Manager view (primary demo path).
- **Scheduled:** daily, via the existing cron path (alongside/replacing the digest). Guarded by `CRON_SECRET`.
- (Not in MVP: event-driven on every upload/sign — avoids noise; daily + on-demand is enough.)

---

## 8. Goal awareness
Reads `profile.monthly_revenue_goal` / `annual_revenue_goal` / `financial_goals` / `business_priorities`
and computes progress (e.g. month income vs goal, overdue total as % of goal). The briefing leads with
this so the owner always sees "where I stand" and the manager's priorities are tied to **their** targets.
Degrades gracefully when goals aren't set (suggests setting them).

---

## 9. UX — the Manager view
- **Header:** goal progress (e.g. "$4,200 / $8,000 this month") + a one-paragraph manager's briefing.
- **Needs your decision:** the approval queue — each item shows title, plain-English rationale, severity,
  and **Approve / Dismiss**. Approve → executes the underlying agent action; Dismiss → closes it.
- **Handled automatically:** recent AUTO actions (categorized N txns, reconciled a payment, refreshed forecast).
- **At a glance:** key cross-module numbers (overdue total, cash-danger day, unsigned contracts).
- Entry point: a top "Manager" item in the sidebar and/or a card on the Overview dashboard.

---

## 10. Safety, trust, audit
- **HITL** for everything outward-facing/irreversible (see §5).
- **Conservative** matching/decisions; when unsure, ask.
- **Idempotent** queueing (no duplicate open tasks; no double-sends).
- **Every** action (auto or approved) → `agent_logs`, with model/tokens/latency/cost when LLM-backed.
- **Disclaimers** preserved (AI-generated drafts, not legal/financial advice).

---

## 11. Risks & mitigations
| Risk | Mitigation |
|---|---|
| Auto-acting on client comms | Hard rule: client comms & money moves are APPROVAL-only |
| LLM cost/latency | One LLM call per run; everything else deterministic |
| Alert/task spam | Idempotent upserts; only surface actionable items; severity ranking |
| Wrong reconciliation/match cascading | Reuse the existing conservative reconciler; ambiguous → review |
| Migration friction | Minimize: reuse `alerts`/`agent_logs`; only `manager_tasks` is genuinely new |

---

## 12. Open decisions (need your call — recommendations in **bold**)
1. **Architecture:** A (LLM tool-calling) / B (rules) / **C hybrid (recommended)**.
2. **Autonomy level:** **Conservative (recommended)** — auto only reversible/internal; all client-comms &
   money moves require approval. (Alt: "auto-send low-risk reminders" — riskier.)
3. **Migrations:** OK to add the `manager_tasks` table (+ apply the pending `profile` column)? Reuse
   `cross_module` agent_type to avoid a third migration? **(recommended)**
4. **Triggers:** **on-demand + daily scheduler (recommended)**, or on-demand only for now?
5. **Phasing:** build **Phase 1 (supervisor + approval queue + Manager view)** now; defer chat &
   tool-calling to Phase 2? **(recommended)**

---

## 12b. Implementation checkpoint (2026-05-31)

Verified against the code. ✅ done · 🟡 partial · ❌ not yet · ⚠️ blocked on migration.

| Design area | Status | Notes |
|---|---|---|
| §4 run flow (gather→assess→execute safe→queue→brief) | ✅ | `services/supervisor.py` |
| §4a memory L1 world state / L2 run-context / L3 audit / L4 decisions | ✅ | DB + `agent_logs` + `manager_tasks` |
| §4a memory **L5 manager memory (continuity, rolling summary)** | ✅ | `users.manager_memory` column; persists last briefing + rolling summary; fed back into next briefing _(done 2026-05-31)_ |
| §4b tool registry + in-process calls + safe sequencing | ✅ | Phase 2b registry; reconcile→follow-up order |
| §4b per-user run serialization / lock | ❌ | minor; fine for single-user demo |
| §5 AUTO: reconcile payments, refresh forecast | ✅ | run on every pass |
| §5 AUTO: categorize new (untouched) txns | ✅ | `recategorize_uncategorized()` runs in each pass _(done 2026-05-31)_ |
| §5 APPROVAL: send follow-up, send demand | ✅ | queued, dispatched on approve |
| §5 APPROVAL: write-off stale invoice | ✅ | proposed at >60d + 3 reminders; approve → invoice cancelled; agentic `propose_write_off` tool _(done 2026-05-31)_ |
| §5 APPROVAL: send/sign contract reminder | 🟡 | deferred — needs email integration (Resend); unsigned contracts surfaced as advisory instead |
| §6 `manager_tasks` table + store CRUD | ✅ | migration applied to live DB; verified end-to-end |
| §6 audit reuse (`cross_module`/`chat`) | ✅ | no migration needed |
| §7 trigger: on-demand "Run manager" | ✅ | button + `POST /run` |
| §7 trigger: daily scheduler | 🟡 | endpoint is cron-ready (`CRON_SECRET`); **no schedule wired** (Cloud Scheduler = deploy phase) |
| §8 goal awareness (read goals + progress) | ✅ | live (`profile` migration applied) |
| §9 UX: briefing, priorities, auto-actions, goal bar, stats, approval queue | ✅ | `/manager` |
| §9 UX: briefing shown on load (persisted) | ✅ | `GET /manager` returns `lastBriefing` from manager memory _(done 2026-05-31)_ |
| §9/§4: advisory findings (cash danger, unsigned contracts, uncategorized txns) | ✅ | "Heads up" section + briefing; deduped cash-danger alert _(done 2026-05-31)_ |
| §10 safety: HITL approval, conservative, idempotent, audit | ✅ | client-comms/money always gated |
| §10 not-legal/financial-advice disclaimer | 🟡 | in chat prompt; not shown in Manager UI |
| Phase 2 conversational chat (#7) | ✅ | §2.6 |
| Phase 2b agentic tool-calling | ✅ | §2.7, verified on gateway |
| Phase 2 preference learning | ❌ | deferred |

### Recommended order to "perfect" the supervisor
1. ~~Apply the migrations (`profile`, `manager_tasks`, `manager_memory`)~~ ✅ done 2026-05-31 — verified live.
2. ~~Manager memory + persisted briefing (§4a L5)~~ ✅ done 2026-05-31 (`users.manager_memory`; `GET /manager` returns `lastBriefing`; prev summary fed into next briefing).
3. ~~Advisory findings (§4/§9)~~ ✅ done 2026-05-31 ("Heads up" + briefing + deduped cash-danger alert).
4. ~~Broaden actions (§5)~~ ✅ done 2026-05-31 — auto-categorize untouched txns; write-off proposal (queue→cancel) + agentic `propose_write_off`. (Contract send/sign reminders deferred → need email/Resend.)
5. **Preference learning:** bias proposals from approve/dismiss history (e.g., stop re-proposing what's repeatedly dismissed). ← _next_
6. **Polish:** per-user run lock; not-advice disclaimer in the Manager UI; show which tools the chat used (transparency).
7. (Deploy phase) Cloud Scheduler daily trigger.

## 13. Phase 1 deliverables (once approved)
- [ ] `manager_tasks` table migration (+ ensure `profile` migration applied)
- [ ] `services/supervisor.py`: `gather_state`, `assess`, `execute_safe`, `compose_briefing`, `run_supervisor`
- [ ] Supervisor LLM method (`compose_briefing`) in both providers (real + mock)
- [ ] Store helpers + endpoints: `POST /api/manager/run`, `GET /api/manager`, `POST /api/manager/tasks/{id}/approve`, `/dismiss`
- [ ] Approve → dispatch to the right existing agent (send follow-up / demand / etc.)
- [ ] Frontend: Manager view (briefing, goal progress, approval queue, auto-actions) + sidebar entry
- [ ] Scheduler wiring + audit logging
- [ ] Verify live (tester): run manager → briefing + queued approvals → approve → action executes
- [ ] Update tracker (§2.x + flip the §8 supervisor gap ⬜→✅)
