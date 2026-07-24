# KICKOFF — paste this to start or resume an AIBackOffice session cold

> Works in any agent. Replace the skill-invocation syntax per `AGENT-ADAPTERS.md`
> (Hermes `skill_view(name=…)` · Claude Code `Skill`/`/x` · Codex `$x`). The rest is identical.

```
PROJECT: AIBackOffice — AI-native back-office SaaS (Next.js 14 frontend + FastAPI backend, Supabase, Stripe, Google/Notion connectors, OpenAI-compatible LLM gateway).
Scope = EXTEND an existing, working MVP. Not a greenfield build.

Load skills (skill canon — always):
- agentic-swe-master          (orchestrator — routes everything)
- modular-architecture, production-readiness
- milestone-specific: tdd (M1, M2, M3), data-systems-engineering (M1), llmops-ai-agents (M2), security-engineering (M3)

  ⚠ MACHINE REALITY (verified 2026-07-25 — do not waste turns on this):
  - The swe-kit skills are installed at ~/.hermes/skills/, NOT ~/.claude/skills/.
    Claude Code only auto-loads ~/.claude/skills/, which contains ONLY `genesis`.
    To use a swe-kit skill in Claude Code, READ THE FILE directly, e.g.
    ~/.hermes/skills/swe-foundations/security-engineering/SKILL.md
  - The skills `coding-orchestrator`, `tdd`, `qa`, and `design-system` DO NOT EXIST
    on this machine, despite being named in the kit templates. Do not try to load them.
    `coding-orchestrator` is the scaffolder's default --router-skill and is a dead reference.
  - The concept wiki IS installed: ~/.agentic-swe-kit/wiki/ (7 domains).
    $AGENTIC_SWE_WIKI_ROOT is set in ~/.bashrc.

Read in order:
- CLAUDE.md / AGENTS.md                       (repo governance, if present)
- .genesis/DONE.html                          (locked spec + definition of done + plan)
- .genesis/PLAN.md                            (milestones being executed)
- .genesis/wiki/index.md                      (then drill into pages matching the milestone's nouns)
- .genesis/implementation-notes.html          (search for the milestone's nouns — what's LIVE now)
- .genesis/LOOPS.md                           (how the work gets done — READ THE G4 BASELINE NOTE)
- .genesis/checkpoints/CURRENT.md             (where we are, if it exists)
- docs/specs/tracker.md §5                    (the pre-genesis backlog these milestones came from)

Environment facts you will otherwise get wrong:
- Backend python is backend/venv/Scripts/python.exe. The SYSTEM python has NO dependencies.
- A real backend/.env exists → the app defaults to AIBackOffice_DATA_BACKEND=supabase.
  Tests and demos MUST pass AIBackOffice_DATA_BACKEND=mock explicitly.
- The seeded demo user is plan="pro" (app/seed.py:50). A free-plan case cannot be
  reached by curl in mock mode — override get_current_user via app.dependency_overrides.
- Zero test files exist. `pytest -q` currently exits 5 ("no tests ran"), NOT 0.
- Docker 29.1.5 is installed but the daemon may not be running (M3 needs it).

Then:
1. Pick the next unstarted milestone (or resume from CURRENT.md). Next up: M1 — Establish Unit Testing Foundation for Core Backend Services.
2. Run G0 EXISTENCE PRE-FLIGHT first. Verdict UNBUILT → continue. PARTIAL → revise scope.
   BUILT → halt and surface the existing artifact.
3. Run L1 BUILD per LOOPS.md exactly. Enforce G0 + all 5 gates (G1 Skill, G2 Progress, G3 Cost, G4 Quality, G5 Verify). Gates are COMPUTED (run the command, paste exit code), not narrated.
4. Checkpoint every iteration to .genesis/checkpoints/<milestone-id>.md.
5. Spawn L2 DEBUG / L3 RESEARCH as needed. Exit through L4 VERIFY (separate model, fresh context).
6. On milestone done: update CURRENT.md, append a row to implementation-notes.html "what's live", append progress to PLAN.md.

Non-negotiable invariants (from .genesis/context-graph.json — check before claiming done):
- Services never import routers.
- Every outbound call has an explicit timeout.
- All untrusted text passes sanitize_prompt_input() before reaching a prompt.
- No outbound send without a human approval step (deliver=True only from approve_*).

Stop rules: if any gate fails 3 times, stop, write what you tried to CURRENT.md, surface to the user.
Never mark a milestone done without L4 VERIFY APPROVE. Never edit DONE.html / PLAN.md without being asked.
```