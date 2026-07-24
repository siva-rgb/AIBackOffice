# Kora

> The back-office that runs itself — AI bookkeeping, invoicing, contracts, and an autonomous business manager for freelancers and small businesses.

Kora is a split-architecture web app: a **Next.js 14** thin client talking over HTTP/JSON to a
**Python / FastAPI** backend that owns all data and AI. Every AI action is logged with its real
model, token count, latency, and cost, giving the whole system an auditable trail.

```
┌───────────────────────────┐   HTTPS / JSON   ┌──────────────────────────────┐
│  frontend/  (Next.js 14)  │ ───────────────► │  backend/  (FastAPI, Python) │
│  RSC fetch, typed client  │ ◄─────────────── │  agents · pandas · ReportLab │
└───────────────────────────┘                  └──────────────────────────────┘
                                                              │
                                              Supabase (Postgres) · Google APIs
                                              Stripe · OpenAI-compatible LLM
```

## Quick start

The stack boots with **zero secrets** — the backend defaults to an in-memory store and a
deterministic mock LLM, so you can run it immediately and wire real services in later.

**1. Backend** → http://localhost:8000

```bash
cd backend
python -m venv venv
venv\Scripts\activate          # Windows   (macOS/Linux: source venv/bin/activate)
pip install -r requirements.txt
cp .env.example .env           # optional — only to connect real services
uvicorn app.main:app --port 8000 --reload
```

**2. Frontend** → http://localhost:3000

```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

Requires **Python 3.11+** and **Node 20**. Interactive API docs are at http://localhost:8000/docs.

In mock mode the backend seeds a demo business (Rivera Studio) with categorized transactions,
invoices — one overdue with logged AI follow-ups — a contract, and agent logs. State is
in-memory and resets on restart; set `KORA_DATA_BACKEND=supabase` to persist.

## Features

| Module | What it does |
|---|---|
| **AI Bookkeeper** | pandas CSV ingest, LLM categorization in batches, review queue, ReportLab P&L PDF |
| **Invoice Agent** | CRUD + send, autonomous follow-ups on day 3/7/14 with LLM-written escalation |
| **Contracts** | 3-step wizard → LLM draft, plain-English clause explanations, PDF, risk/loophole reviewer |
| **Cash-flow Forecast** | Probability-weighted 90-day projection across 3 scenarios, LLM risks and actions |
| **Proactive Alerts** | Daily digest agent builds a financial snapshot and raises deduped alerts |
| **Supervisor** | Goal-aware AI business manager — conversational chat, agentic tool-calling, advisories |
| **Butler (Google)** | Gmail, Drive, Calendar, and meeting intelligence feeding a morning briefing |
| **Graph + Semantic Memory** | `kg_nodes`/`kg_edges` relationship graph plus embedding-based recall over learned facts |
| **Task / Project Ledger** | Task tracking with a two-way Notion connector |
| **Agent Dashboard** | Stats, filterable execution log, CSV export — every action attributed and costed |
| **Billing & Auth** | Supabase auth, Stripe billing and Connect, onboarding, legal pages |

Cross-module intelligence ties these together — e.g. marking a contract signed auto-creates its
milestone invoices.

## Repository layout

```
backend/                  FastAPI (Python 3.11+)
  app/
    main.py               app, CORS, /health, error handling
    config.py  models.py  pydantic-settings · Pydantic v2 (camelCase JSON)
    store.py   backends/  data layer — in-memory and Supabase adapters
    dependencies.py       get_current_user, require_plan, cron secret
    routers/              27 route modules (invoices, butler, tasks, graph, memory, …)
    services/             agents, LLM client, PDF, logging, storage, cost accounting
    utils/                security (prompt sanitization) · rate limiting · CSV parsing
    middleware/           request-level concerns
  migrations/             dated SQL migrations, applied in filename order
  workers/                background sync jobs
  Dockerfile  requirements.txt  .env.example

frontend/                 Next.js 14 (App Router, thin client)
  app/(dashboard)/        RSC pages: dashboard · bookkeeping · invoices · contracts · cashflow · agents
  components/             UI and per-module components
  lib/api/                base URL config · RSC fetch helpers · shared types
  .env.local.example

docs/
  specs/                  product spec, agent design, schema.sql, build tracker, checkpoints
  skills/                 per-domain design docs (email, manager, invoice, privacy, Stripe, …)
  gcp_setup.md            Google Cloud setup notes

.github/workflows/        cron.yml — scheduled agent runs against the deployed backend
```

## Configuration

Copy each template and fill in your own values. Both templates ship with **placeholders only** —
never commit real credentials.

| File | Key settings |
|---|---|
| `backend/.env.example` | `KORA_DATA_BACKEND` (`mock`\|`supabase`), `KORA_AI_BACKEND` (`auto`\|`openai`\|`mock`\|`vertex`), Supabase service-role key, Google Cloud, Stripe, `CRON_SECRET` |
| `frontend/.env.local.example` | `NEXT_PUBLIC_API_URL`, Supabase URL + anon key, Stripe publishable key |

**LLM provider.** Agents call a provider-agnostic layer (`services/vertex_ai.py` → `llm.py`).
`KORA_AI_BACKEND=auto` uses any OpenAI-compatible gateway when `MODEL_API_KEY` and `BASE_URL` are
set, and otherwise falls back to the deterministic mock so the app still runs offline. Production
targets Google Vertex AI via `KORA_AI_BACKEND=vertex` — no agent code changes required.

**Database.** Apply `backend/migrations/*.sql` in filename order against your Supabase project;
`docs/specs/schema.sql` holds the full schema.

**Scheduled runs.** `.github/workflows/cron.yml` fires the cron endpoints on a deployed backend.
It needs two repository secrets: `KORA_API_URL` and `KORA_CRON_SECRET` (matching `CRON_SECRET`).

## Security

- Secrets live only in `.env` / `.env.local`, which are gitignored. Only `*.example` templates
  with placeholder values are committed.
- Service-account JSON keys, `*.pem`, and `*.key` are gitignored by pattern.
- All LLM input passes through `sanitize_prompt_input()`; calls are retried with tenacity and
  rate-limited per user.
- Plan gating is enforced server-side via `require_plan`.
- The Supabase **service-role** key bypasses row-level security — backend only, never exposed to
  the frontend.

## License & ownership

**Copyright © 2026 [YOUR FULL LEGAL NAME]. All Rights Reserved.**

Kora — including its source code, design, architecture, and documentation — was created by and
is the exclusive property of the copyright holder. It is **proprietary software**, not open
source. No permission is granted to use, copy, modify, deploy, or distribute it without prior
written consent. See [LICENSE](LICENSE) for the full terms.

## Status

The MVP vertical slice is complete and running end to end. Open items are tracked in
[docs/specs/tracker.md](docs/specs/tracker.md) §5 — the main ones being GCP Cloud Run deployment,
full plan-gating enforcement, transactional email wiring, and automated test coverage.
