---
name: kora-playbook
description: >
  Build the Kora Business Playbook — a structured learning system that makes
  Kora smarter over time by observing user actions, storing patterns, and
  injecting personalized context into every LLM call. Use this skill whenever
  building any part of the Playbook: the business_playbook table, observation
  workers, context assembler, tiered memory, confidence/decay system,
  validation layer, or the user-facing "What Kora knows" settings page.
  Triggers on: "learning", "playbook", "patterns", "preferences", "corrections",
  "context assembler", "tiered memory", "hallucination prevention", "kora knows",
  "improve over time", "get smarter", "user patterns", "business intelligence".
---

# Kora Business Playbook — Learning System

> "A diligent employee who pays attention. Every correction remembered.
>  Every pattern observed. Every prompt gets better context."

This is NOT machine learning. No model training, no vector database, no embeddings.
It is structured observation stored in Postgres and injected into LLM prompts as context.
The LLM doesn't change. The context it receives changes. That's the learning.

Read the reference files in this order:
1. `references/schema.md`        — the business_playbook table + column additions
2. `references/observers.md`     — three observer functions wired into existing handlers
3. `references/assembler.md`     — context assembly + tiered memory + prompt injection
4. `references/validation.md`    — anti-hallucination checks on LLM output
5. `references/frontend.md`      — "What Kora knows" settings page + Playbook viewer

---

## 1. How it works (the loop)

```
OBSERVE → STORE → ASSEMBLE → INJECT → BETTER OUTPUT → user corrects less → loop
```

1. User approves/dismisses a manager_task → observer records the pattern
2. User edits an email draft before approving → observer extracts tone preference
3. User corrects a transaction category → observer stores the override permanently
4. Weekly worker detects income seasonality → stores as business_pattern
5. Context assembler reads Playbook → selects relevant entries → compresses to ~500 tokens
6. Every LLM call includes this context → output is personalized
7. User corrects less → higher approve rate → more trust → Kora handles more

---

## 2. Kora codebase patterns (MUST follow these exactly)

This skill MUST follow the actual codebase conventions from the tracker:

- **Models:** Pydantic v2 `CamelModel` with camelCase aliases (`app/models.py`)
- **Store:** use `store.py` dispatcher pattern — add helpers to both
  `backends/memory_store.py` and `backends/supabase_store.py`
- **LLM calls:** go through `services/llm.py` abstraction, NOT direct Vertex/OpenAI
- **Agent logging:** use `services/agent_logger.py` → `agent_logs` table
- **Auth:** `get_current_user` dependency on all routes
- **Security:** `sanitize_prompt_input()` on all user text entering prompts
- **Agent types:** add `'playbook'` to the `AgentType` enum in `models.py`
- **Frontend types:** add to `lib/api/types.ts`
- **No FK columns on existing tables** — use name-match linkage (Kora convention)
- **Both backends:** every store function MUST exist in memory_store AND supabase_store

---

## 3. What the Playbook stores (six categories)

| Category | What | Example | Confidence | Decays? |
|---|---|---|---|---|
| `correction` | User explicitly fixed something | "WEWORK → office_supplies" | 1.0 always | Never |
| `user_preference` | Observed from edits + approvals | "email tone: direct, <100 words" | 0.3–0.95 | After 90 days |
| `client_intelligence` | Per-client learned behavior | "Harbor pays in 7 days after 2nd reminder" | 0.3–0.95 | After 90 days inactive |
| `business_pattern` | Detected from transaction history | "Q4 income is 2.3× Q2" | 0.5–0.95 | After 6 months |
| `business_rule` | Inferred from repeated behavior | "never sends follow-ups on weekends" | 0.5–0.9 | After 90 days |
| `extracted_fact` | From emails, contracts, meetings | "charges $150/hr for consulting" | 0.5–0.9 | After 6 months |

---

## 4. Absolute rules

1. **Corrections are permanent and highest priority.** Confidence 1.0. Never decay.
   If the user corrected a category once, the correction is checked before calling
   the LLM for categorization. The same mistake never happens twice.

2. **Numbers in LLM output come from the database, never from the LLM.**
   The context assembler provides pre-computed numbers. The LLM narrates them.
   The validation layer catches any number in the output not present in the input.

3. **Confidence floor: 0.5.** Entries below 0.5 are never injected into prompts.
   They stay in the database for the pattern detection worker to reinforce later.

4. **Max 500 tokens of Playbook context per prompt.** The assembler compresses
   aggressively. More context does not mean better output past this threshold.

5. **User can see, edit, and delete everything.** A settings page shows all
   Playbook entries. The user audits the source. If the source is correct,
   the output is correct.

6. **All Playbook writes go through `store.py`.** Both backends must implement
   every helper. Mock mode must work for demo without Supabase.

7. **Observer functions are synchronous side-effects**, not background workers.
   Kora has no worker runtime. Observers run inline after the triggering action.

---

## 5. Build order

**Phase 1 — Schema + store helpers (Day 1)**
The `business_playbook` table, models, and store CRUD in both backends.
Read `references/schema.md`.

**Phase 2 — Core observers (Days 2–3)**
Observers 1–4: approve/dismiss, category correction, email edit, payment reconciliation.
Plus Observer 7 (onboarding seed) for day-1 context.
Read `references/observers.md`.

**Phase 3 — Context assembler + prompt injection (Days 3–4)**
Build the assembler. Inject into ALL agent prompts: supervisor briefing, butler briefing,
email drafts, bookkeeper categorization, follow-up decisions, cashflow forecast,
and contract generation. Wire the bookkeeper pre-check.
Read `references/assembler.md`.

**Phase 4 — Validation layer (Day 4)**
Post-LLM output checks for hallucinated numbers and unknown entity names.
Read `references/validation.md`.

**Phase 5 — Frontend (Day 5)**
"What Kora knows" page in settings. Playbook viewer with edit/delete.
Read `references/frontend.md`.

**Phase 6 — Bridge observers + pattern detection (Day 6)**
Observers 5–6: Gmail intel → Playbook bridge, meeting agent → Playbook bridge.
Pattern detection: income seasonality, client payment reliability, billing rhythm,
communication frequency. Runs on-demand via button.
Read `references/observers.md` (Phase 2 section).

---

## 6. New files created

```
backend/app/
  models.py              — add PlaybookEntry, PlaybookCategory, PlaybookCreate
  backends/
    memory_store.py      — add playbook CRUD helpers
    supabase_store.py    — add playbook CRUD helpers
  services/
    playbook.py          — context assembler + observers + pattern detection
    validation.py        — post-LLM output validation
  routers/
    playbook.py          — CRUD API for Playbook entries + trigger pattern detection

frontend/
  app/(dashboard)/settings/playbook/page.tsx  — "What Kora knows" viewer
  components/settings/PlaybookViewer.tsx
  lib/api/types.ts       — add PlaybookEntry type
```

---

## 7. Integration points (where existing code changes)

These are minimal, targeted changes to wire the observers and assembler:

### Observers (one-line additions)

| Existing file | Change |
|---|---|
| `routers/supervisor.py` approve handler | Add: `playbook.observe_decision(user_id, task, 'approved')` |
| `routers/supervisor.py` dismiss handler | Add: `playbook.observe_decision(user_id, task, 'dismissed')` |
| `routers/bookkeeping.py` category update | Add: `playbook.observe_correction(user_id, txn_id, old_cat, new_cat)` |
| `services/cross_module.py` reconcile_payments | Add: `playbook.observe_payment(user_id, invoice, transaction)` |
| Onboarding completion handler | Add: `playbook.seed_from_onboarding(user_id, profile)` |
| `services/gmail_intel.py` after thread analysis | Add: `playbook.observe_email_intel(user_id, client_id, intel)` (Phase 2) |
| `services/meeting_agent.py` after MOM extraction | Add: `playbook.observe_meeting(user_id, client_id, extracted)` (Phase 2) |

### Assembler (context injection into prompts)

| Existing file | Change |
|---|---|
| `services/supervisor.py` compose_manager_briefing | Add: `context = assemble_context(user_id, 'briefing')` + inject |
| `services/butler.py` compose_butler_briefing | Add: `context = assemble_context(user_id, 'briefing')` + inject |
| `services/gmail_draft.py` draft_client_reply | Add: `context = assemble_context(user_id, 'email_draft', client_id)` + inject |
| `services/bookkeeper.py` categorization call | Add: `context = assemble_context(user_id, 'categorization')` + inject |
| `services/bookkeeper.py` BEFORE categorization LLM | Add: `corrected, needs_llm = apply_corrections_before_llm(user_id, txns)` |
| Follow-up agent / supervisor assess | Add: `context = assemble_context(user_id, 'follow_up_decision', client_id)` + check business_rules before proposing |
| `services/cashflow_agent.py` forecast prompt | Add: `context = assemble_context(user_id, 'forecast')` + inject seasonality |
| `services/contract_agent.py` generation prompt | Add: `context = assemble_context(user_id, 'contract')` + inject typical terms |
| `services/proposal_agent.py` generation prompt | Add: `context = assemble_context(user_id, 'proposal', client_id)` + inject |

### Validation (post-LLM checks)

| Existing file | Change |
|---|---|
| `services/supervisor.py` after compose_manager_briefing | Add: `briefing = validate_briefing(briefing, state, user_id)` |
| `services/butler.py` after compose_butler_briefing | Add: `briefing = validate_briefing(briefing, state, user_id)` |
| `services/gmail_draft.py` after draft generation | Add: `draft = validate_email_draft(draft, client_name, amounts, user_id)` |
