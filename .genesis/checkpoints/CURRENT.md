# CURRENT
- active_loop: idle (awaiting next milestone pick)
- target: M4 (LLM Input Sanitization) — **CLOSED 2026-07-28**
- iteration: n/a (L4 APPROVE + Q+A logged)
- last_gate: G5 (passed) — L4 APPROVE; all 5 computed gates green at close; 7 spot-checks PASS; Q+A logged without UNCERTAIN downgrade
- last_action: M4 closed. PLAN.md [x], DONE.html done, M4.verify.md + M4.md close-out written. Same-session L4 caveat documented (same as M3 precedent).
- next_action: pick the next milestone — candidates: M1 (Tenant Isolation, CRITICAL, todo), M5 (Docs & Schema, MEDIUM, parallel-friendly), or `structured-sanitizer-library` (M4.2 follow-up candidate, HIGH justification from Q3)
- model: nvidia/minimax-m3 (driver)
- tokens_used: ~4000 (L4 only — separate from M4 L1's ~11500)
- tokens_budget: 50000 (reset per milestone)
- skills_loaded: [agentic-swe-master, llmops-ai-agents, security-engineering]

## M4 closure summary
- 5 services fixed: butler_comms (HIGH), supervisor (MEDIUM), contract_agent (MEDIUM), invoice_agent (MEDIUM), routers/manager (chat message → reject path)
- 2 new test files: tests/security/test_prompt_injection.py (17 tests), tests/security/test_llm_input_lint.py (2 AST-lint tests)
- 2 context-graph invariants added: inv_llm_input_sanitization, inv_llm_sanitizer_consistency
- 6 lint markers added: m4-lint: store-only × 4, m4-lint: no-sanitize × 2
- 3 quiz-me Q+A logged in M4.verify.md §Q+A — all substantive

## Final gate snapshot at M4 close (re-L4 input, fresh execution)
| Gate | Command | Result |
|---|---|---|
| security pytest | pytest tests/security/ | 53 passed, 1 skipped |
| full pytest | pytest tests/ --cov=app --cov-fail-under=39 | 325 passed, 1 skipped · coverage 42.38% |
| lint | flake8 app | exit 0 · 0 errors |
| format (touched) | black --check --line-length=155 on 11 M4-touched files | 11 files would be left unchanged |
| format (full) | black app tests --check --line-length=155 | 27 files would be reformatted (PRE-EXISTING drift on untouched files, NOT M4) |
| context-graph | invariants field has 7 real entries (was 5) | OK |
| M4 demo command | pytest tests/security/test_prompt_injection.py -v | 17 passed |

## Pending human decisions (post-M4)
1. **Pick next milestone** — recommend one of:
   - **M1 (Tenant Isolation, CRITICAL)** — still todo. Highest priority per the original principal-architect review; gaps_and_improvement_of_current_implementation.txt opens with this. Has its own parallel track (`backend-core`), no dependencies.
   - **`structured-sanitizer-library`** (M4.2 follow-up candidate) — Q3 surfaced the strongest argument for this: today's defense is regex + AST lint (catches violations at PR time, not at attack time). A real classifier closes the deeper gap. ~1-2 weeks of work; new dependency.
   - **M5 (Docs & Schema, MEDIUM)** — fully parallel, low risk, quick win. Good "secondary contributor" task.
2. **Real separate-model L4** — for full LOOPS.md §243–244 compliance on the next milestone (defer until then; same-session L4 caveat documented for M3 + M4).

## Caveats / known gaps carried forward
- Mock-provider test scope: tests assert on what was sent to LLM, not LLM response — by design (boundary testing vs. feature testing)
- `butler.parse_capture` + `supervisor.chat` carry `m4-lint: no-sanitize` markers because the router layer sanitizes; lint catches future bypass
- **M4.2 literal interpretation deferred** — `structured-sanitizer-library` is now the strongest follow-up candidate
- **M3 follow-ups still parked**: type-cleanup (218 mypy errors), key-rotation-zero-downtime, context-graph `inv_token_encryption_startup` wording cleanup

## Closed milestones (canonical reference)
- **M2** — Test Harness + CI · `.genesis/checkpoints/M2.md` · `[x]` 2026-07-28
- **M3** — Token Encryption Fail-Closed · `.genesis/checkpoints/M3.md` + `M3.verify.md` · `[x]` 2026-07-28
- **M4** — LLM Input Sanitization · `.genesis/checkpoints/M4.md` + `M4.verify.md` · `[x]` 2026-07-28
