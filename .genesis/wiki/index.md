# Wiki Index — AIBackOffice

The project knowledge base. Same schema as the agentic-swe-kit wiki: concept pages in `concepts/`,
each with frontmatter and ≥2 `[[wikilinks]]`. The L3 RESEARCH loop writes here; G0 reads here first.

> **Read this file before any milestone (G0 step 1).** Pick candidate pages by name-matching the
> milestone's nouns, then drill in. The wiki is what prevents rebuilding work that already exists.

## Entities (the things this system has)
<!-- - [[concepts/<Entity>]] — one-line summary -->

## Concepts (how it works)
<!-- - [[concepts/<Concept>]] — one-line summary -->

## Sources (research distilled by L3)
<!-- - [[concepts/<source-slug>]] — one-line summary | filed <date> -->

## Seeded from agentic-swe-kit
Relevant global concept pages for this project's phases (pointers only — read on demand):

### Phase 0 — Cognitive Design
- `$AGENTIC_SWE_WIKI_ROOT/swe-foundations/engineering-mindset/concepts/autonomy-levels.md` — defining what the agent decides vs what requires human approval

### Phase 3 — Backend Engineering & API Layer
- `$AGENTIC_SWE_WIKI_ROOT/swe-foundations/modular-architecture/concepts/dependency-direction.md` — domain never imports framework
- `$AGENTIC_SWE_WIKI_ROOT/swe-foundations/production-readiness/concepts/timeout-circuit-breaker.md` — every outbound call needs one

### Phase 5 — LLM & Reasoning Layer
- `$AGENTIC_SWE_WIKI_ROOT/mlops/llmops-ai-agents/concepts/prompt-injection-defenses.md` — LlamaGuard / instruction hierarchy
- `$AGENTIC_SWE_WIKI_ROOT/mlops/llmops-ai-agents/concepts/structured-output-schemas.md` — all outputs validated against schema
- `$AGENTIC_SWE_WIKI_ROOT/mlops/llmops-ai-agents/concepts/multi-model-routing.md` — cheap model vs flagship routing

### Phase 11 — Security Architecture
- `$AGENTIC_SWE_WIKI_ROOT/swe-foundations/security-engineering/concepts/threat-modeling.md` — adversary categories, prompt injection vectors
- `$AGENTIC_SWE_WIKI_ROOT/swe-foundations/security-engineering/concepts/tenant-isolation.md` — middleware-enforced user_id filtering + RLS fallback
- `$AGENTIC_SWE_WIKI_ROOT/swe-foundations/security-engineering/concepts/audit-trails.md` — append-only, tamper-evident logs

### Phase 12 — Reliability Engineering
- `$AGENTIC_SWE_WIKI_ROOT/swe-foundations/production-readiness/concepts/retry-idempotency.md` — deterministic retries
- `$AGENTIC_SWE_WIKI_ROOT/swe-foundations/distributed-systems/concepts/rate-limiting-distributed.md` — Redis-backed vs in-process

### Phase 15 — Governance & Compliance
- `$AGENTIC_SWE_WIKI_ROOT/swe-foundations/security-engineering/concepts/gdpr-compliance.md` — data export + right to erasure
- `$AGENTIC_SWE_WIKI_ROOT/mlops/llmops-ai-agents/concepts/cost-attribution.md` — per-span cost tracking
