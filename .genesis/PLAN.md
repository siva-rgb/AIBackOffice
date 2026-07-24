# PLAN — AIBackOffice

The machine-parseable implementation plan. Mirrors the milestone table in `DONE.html` (DONE.html is the human/visual view; this is the one loops read). Sliced so each milestone ships in one L1 BUILD pass.

> Slicing rule: a milestone must have (a) a single clear outcome, (b) an exact **demo command** that proves it, and (c) a freeze boundary of files it may touch. If you can't write the demo command, the milestone is too vague — split it.

## M1 — Establish Unit Testing Foundation for Core Backend Services
- **Outcome:** Unit test suite for authentication and billing modules with 80% line coverage.
- **Phase (swe-master):** Phase 9: Evaluation Systems
- **Files / freeze boundary:** `backend/app/auth/`, `backend/app/billing/`, `backend/tests/unit/`
- **Demo command:** `cd backend && python -m pytest tests/unit/ -v --cov=app --cov-report=term-missing`
- **Success criteria:** All unit tests pass, coverage >= 80% for auth and billing modules.
- **Loops:** L1, L4
- **Skills:** canon + tdd + data-systems-engineering
- **Token budget:** 50000

## M2 — Implement Integration Tests for Critical Service Boundaries
- **Outcome:** Integration test suite that validates contracts with Supabase, LLM API, and Stripe using mocks and fixtures.
- **Phase (swe-master):** Phase 12: Reliability Engineering
- **Files / freeze boundary:** `backend/app/services/`, `backend/tests/integration/`
- **Demo command:** `cd backend && set KORA_DATA_BACKEND=mock && venv\Scripts\python.exe -m pytest tests/integration/ -v --tb=short`
- **Success criteria:** All integration tests pass, external service calls are mocked, no real API keys used in test runs.
- **Loops:** L1, L3 (research), L4
- **Skills:** canon + tdd + llmops-ai-agents
- **Token budget:** 50000

## M3 — Set Up End-to-End Testing for Key User Workflows
- **Outcome:** End-to-end test suite covering user signup, invoice submission, and report viewing, executed against a staging environment.
- **Phase (swe-master):** Phase 20: Continuous Learning Systems
- **Files / freeze boundary:** `frontend/`, `e2e/`, `cypress.config.js`, `playwright.config.ts` (whichever is used)
- **Demo command:** `cd frontend && npx playwright test e2e/tests/user-journeys.spec.js --project=chromium`
- **Success criteria:** All E2E tests pass in headless mode, screenshots and videos captured on failure.
- **Loops:** L1, L2, L4
- **Skills:** canon + tdd + security-engineering
- **Token budget:** 50000