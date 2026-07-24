# Wiki Index — AIBackOffice

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
All paths below were verified to exist at genesis (2026-07-25).

**M1 · Establish Unit Testing Foundation for Core Backend Services — Phase 9: Evaluation Systems**
- `release-it/concepts/Code-Thats-Easy-to-Test.md` — writing testable code and applying TDD principles
- `clean-architecture/concepts/Boundary-Lines.md` — keeping domain layer free of framework dependencies
- `security-engineering/concepts/Access-Control.md` — authentication and authorization principles for auth module
- `security-engineering/concepts/Financial-Security-Controls.md` — controls for billing and payment handling

**M2 · Implement Integration Tests for Critical Service Boundaries — Phase 12: Reliability Engineering**
- `llmops-ai-agents/concepts/Evaluation-Frameworks.md` — building evaluation plans for LLM API integrations
- `release-it/concepts/Integration-Points.md` — managing contracts and boundaries with external services
- `release-it/concepts/Circuit-Breaker.md` — resilience patterns for external service calls
- `security-engineering/concepts/Threat-Modeling.md` — identifying threats in service integrations

**M3 · Set Up End-to-End Testing for Key User Workflows — Phase 20: Continuous Learning Systems**
- `release-it/concepts/Design-for-Production.md` — production readiness checklist for user workflows
- `llmops-ai-agents/concepts/Autonomous-Action-Agents.md` — agents that perform real-world actions (e.g., invoice submission)
- `llmops-ai-agents/concepts/Observability-and-Cost-Control.md` — monitoring and cost control for E2E test execution
- `security-engineering/concepts/Production-Hardening.md` — hardening measures for user-facing workflows