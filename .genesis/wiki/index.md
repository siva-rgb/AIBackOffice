# Wiki Index — KORA

The project knowledge base. Same schema as the agentic-swe-kit wiki: concept pages in `concepts/`,
each with frontmatter and ≥2 `[[wikilinks]]`. The L3 RESEARCH loop writes here; G0 reads here first.

> **Read this file before any milestone (G0 step 1).** Pick candidate pages by name-matching the
> milestone's nouns, then drill in. The wiki is what prevents rebuilding work that already exists.

## Entities (the things this system has)
<!-- Stubs — fill as milestones touch them. Source of truth is the code, not this list. -->
- `User` — owns a `plan` (`free` / `starter` / `pro`, ranked in `dependencies.py:_PLAN_RANK`) and `contract_credits`. The subject of every entitlement decision (M2).
- `Invoice` — the money object. Carries follow-up state and the day-3/7/14 escalation ladder.
- `Contract` — LLM-drafted, risk-reviewed; signing auto-creates milestone invoices (cross-module).
- `Engagement` / `Client` — Butler's workspace objects; the hub that tasks and notes hang off.
- `Task` — the ledger added 2026-07-17, two-way synced to Notion via `external_ref`.
- `AgentLog` — every AI action with model, tokens, latency, cost. The audit trail (Phase 15).
- `Alert` — deduped output of the daily digest agent. **In-app only today — delivery is M5.**

## Concepts (how it works)
- `entitlements` — **does not exist yet; M2 creates it.** The policy table mapping feature → minimum plan.
- `require_plan` — the dependency factory in `app/dependencies.py:50`. Works, returns 403, **currently applied to zero routes.**
- `sanitize_prompt_input` — the prompt-injection boundary; 21 call sites. See invariant `all_llm_input_is_sanitized`.
- `deliver=True` — the autonomy switch. Reachable only from `supervisor.approve_task`. See invariant `no_outbound_send_without_human_approval`.
- `KORA_DATA_BACKEND` — `mock` (in-memory, zero secrets) vs `supabase`. Tests must force `mock`.

## Sources (research distilled by L3)
<!-- - [[concepts/<source-slug>]] — one-line summary | filed <date> -->
_(none yet — the first L3 RESEARCH loop fills this)_

## Seeded from agentic-swe-kit
Pointers only — read on demand. Root: `$AGENTIC_SWE_WIKI_ROOT` (= `~/.agentic-swe-kit/wiki`).
All paths below were verified to exist at genesis (2026-07-23).

**M1 · Plan gating — Phase 11 Security**
- `security-engineering/concepts/Access-Control.md` — when deciding who may invoke what; the core M1 question.
- `security-engineering/concepts/Threat-Modeling.md` — before writing the adversary list the Phase 11 gate demands.
- `security-engineering/concepts/Metering-and-Token-Security.md` — when implementing `contract_credits` as a metered entitlement.
- `security-engineering/concepts/Financial-Security-Controls.md` — controls appropriate to a system holding client financial records.
- `clean-architecture/concepts/Boundary-Lines.md` — when deciding whether the gate belongs at the route, middleware, or service layer.

**M2 · Regression suite — Phase 9 Evaluation**
- `llmops-ai-agents/concepts/Evaluation-Frameworks.md` — building the 3-level (component/integration/production) eval plan.
- `release-it/concepts/Code-Thats-Easy-to-Test.md` — when the code resists testing, fix the seam not the test.
- `clean-architecture/concepts/Component-Coupling-Principles.md` — when a test needs half the app booted, coupling is the bug.

**M3 · Containerize + Cloud Run — Phase 13 Infra**
- `release-it/concepts/Design-for-Production.md` — the general "will this survive contact with prod" checklist.
- `release-it/concepts/Configuration-Management.md` — directly relevant: `NEXT_PUBLIC_API_URL` is **build-time baked**, so backend must deploy first.
- `release-it/concepts/Integration-Points.md` — every Cloud Run service boundary is a new failure mode.
- `release-it/concepts/Circuit-Breaker.md` — when adding resilience around the LLM gateway and Supabase.

**M4 · Digest delivery HITL — Phase 19**
- `llmops-ai-agents/concepts/Autonomous-Action-Agents.md` — agents that take real-world action; the approval-gate design.
- `llmops-ai-agents/concepts/Production-Hardening.md` — idempotency so a retry never double-sends.
- `llmops-ai-agents/concepts/Observability-and-Cost-Control.md` — keeping `agent_logs` attribution intact for new send paths.
