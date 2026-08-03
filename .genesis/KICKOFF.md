# KICKOFF — paste this to start or resume a AIBackOffice session cold

> Works in any agent. Replace the skill-invocation syntax per `AGENT-ADAPTERS.md`
> (Hermes `skill_view(name=…)` · Claude Code `Skill`/`/x` · Codex `$x`). The rest is identical.

```
Load skills (skill canon — always):
- agentic-swe-master              (orchestrator — routes everything)
- coding-orchestrator                (route before any code)
- modular-architecture, production-readiness
- security-engineering               (tenant isolation, auth, threat model)
- llmops-ai-agents                (prompt security, LLM performance)
- if frontend milestone: the design-system skill (MANDATORY)

Read in order:
- .genesis/DONE.html                          (locked spec + definition of done + plan)
- .genesis/PLAN.md                            (8 milestones, security-critical first)
- .genesis/wiki/index.md                      (pointers to swe-kit concepts)
- .genesis/implementation-notes.html          (search for milestone nouns)
- .genesis/LOOPS.md                           (how the work gets done)
- .genesis/checkpoints/CURRENT.md           (where we are now)

Then:
1. Pick the next unstarted milestone from the table in DONE.html.
2. Run G0 EXISTENCE PRE-FLIGHT first. Verdict UNBUILT -> continue. PARTIAL -> revise scope.
   BUILT -> halt and surface the existing artifact.
3. Run L1 BUILD per LOOPS.md exactly. Enforce all 5 gates -- gates are COMPUTED (real exit codes).
4. Checkpoint every iteration and milestone completion.
5. Exit through L4 VERIFY (separate model, fresh context).

Active project: AIBackOffice (Kora) — AI-powered business backoffice.
```
