from . import _bootstrap  # noqa: F401  — inject OS trust store before any TLS
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Backend settings via pydantic-settings (SKILL.md §3).

    Everything has a safe default so the app boots with zero secrets in
    mock mode. Real values arrive via a .env file or the environment.
    """

    # Load .env.example (carries the dev gateway key the user added) then let a
    # real .env override it. Last file wins in pydantic-settings.
    model_config = SettingsConfigDict(
        env_file=(".env.example", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Backends. Data: 'mock' (in-memory) or 'supabase'.
    #
    # AI backend — which transport the agents' model calls use:
    #   'vertex' — Google Vertex AI (Gemini) via Application Default Credentials
    #   'openai' — the OpenAI-compatible gateway below
    #   'mock'   — deterministic, network-free provider
    #   'auto'   — Vertex when ADC + a project resolve, else the gateway when
    #              MODEL_API_KEY is set, else mock
    #
    # Note that 'auto' prefers Vertex, and Vertex authenticates with ADC rather
    # than an env var — so blanking MODEL_API_KEY is NOT enough to keep a process
    # offline. The test suite pins 'mock' in conftest.py for exactly this reason.
    KORA_DATA_BACKEND: str = "mock"
    KORA_AI_BACKEND: str = "auto"

    # OpenAI-compatible LLM gateway. Still used for embeddings (see below) and
    # available as an alternative chat transport via KORA_AI_BACKEND=openai.
    MODEL_API_KEY: str = ""
    BASE_URL: str = ""
    # Chat/generation model. On Vertex this must be a Gemini id (e.g.
    # 'gemini-2.5-flash'); a leftover gateway id is corrected to the Vertex
    # default rather than 404-ing every agent call. See services/vertex_llm.py.
    MODEL_NAME: str = "azure.gpt-4.1"

    # Embeddings for semantic/hybrid memory recall. The *shape* of this name
    # picks the backend (services/embeddings.py):
    #   'gemini-embedding-001'         → Vertex AI directly, via ADC
    #   'azure.text-embedding-3-small' → the OpenAI-compatible gateway, which
    #                                    namespaces models with a provider prefix
    # Empty or an unavailable model disables semantic ranking gracefully — recall
    # falls back to lexical-only, so the feature never hard-breaks.
    #
    # CHANGING THIS INVALIDATES EVERY STORED VECTOR. Embeddings are only
    # comparable to others from the same model, so recall silently returns
    # nothing useful until `POST /api/memory/reindex` has re-embedded every row.
    EMBEDDING_MODEL: str = "gemini-embedding-001"

    # Dimensionality of the embedding model above. Must match the `vector(N)`
    # column on agent_memory.embedding_vec (M10 migration).
    #
    # Passed to Vertex as `output_dimensionality`, so gemini-embedding-001
    # (natively 3072) is asked for 1536 and fits the existing column with no
    # migration. Operators changing this MUST also re-issue the column type and
    # rebuild the HNSW index — recorded as FU-M10-dim-change-migration.
    EMBEDDING_DIM: int = 1536

    # M10 — which recall backend the service layer uses.
    #   "jsonb"   — load all rows for the tenant, cosine in Python (legacy,
    #               works in mock mode, O(N) per query)
    #   "pgvector" — call match_agent_memory RPC, O(log N) per query; requires
    #               the 2026-07-29_pgvector_agent_memory.sql migration AND a
    #               backfill (python -m scripts.backfill_agent_memory_vectors).
    # Default stays on "jsonb" until an operator has run the migration + backfill.
    AGENT_MEMORY_VECTOR_BACKEND: str = "jsonb"

    # Allowed browser origin(s) for CORS — comma-separated. A Cloud Run service
    # answers on two hostnames (the legacy *-HASH-REGION.a.run.app and the newer
    # *-PROJECTNUMBER.REGION.run.app), and a visitor may arrive on either, so
    # both usually belong here. Used for CORS only; redirect URLs come from
    # NEXT_PUBLIC_APP_URL / BASE_URL.
    FRONTEND_ORIGIN: str = "http://localhost:3000"

    # Supabase (service role — backend only)
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""

    # Demo bridge: until the frontend login is wired, requests without a valid
    # Supabase JWT resolve to this seeded demo user. Set ALLOW_DEMO_USER=false
    # to require real auth.
    DEMO_EMAIL: str = "demo@kora.app"
    ALLOW_DEMO_USER: bool = True

    # The tenant that scheduled (cron) agent runs act for. Cron carries a shared
    # secret rather than a session, so there is no user on the request to act as.
    # Set this to the tenant's id and it takes precedence over the DEMO_EMAIL
    # lookup — an id is stable, whereas the demo account's email has already been
    # repointed once, which silently broke every scheduled run.
    SCHEDULER_USER_ID: str = ""

    # Tenants whose data is SHARED between many people (the published demo
    # account every evaluator signs into with the same credentials). Erasure is
    # refused for these, because it is not one user deleting their own data —
    # it destroys the account for everyone who signs in after them, revokes the
    # owner's Google grant, and deletes the auth identity behind the published
    # login. Comma-separated user ids; empty disables the guard entirely, so
    # ordinary self-service deletion is untouched for every real tenant.
    #
    # Matched on ID, never on email: D-014 repointed the demo tenant's
    # `users.email` at the operator's real inbox, so an email match would
    # silently stop protecting the very account it was written for.
    PROTECTED_TENANT_IDS: str = ""

    # Populate a brand-new tenant with the sample business when onboarding
    # completes (see services/sample_data.py). OFF by default on purpose:
    # writing invented clients and invoices into a real person's books must be
    # an operator's explicit choice. Enabled for the public evaluation
    # deployment, where an empty tenant would show an evaluator nothing.
    SEED_SAMPLE_DATA_ON_SIGNUP: bool = False

    # Google Cloud / Vertex AI
    GOOGLE_CLOUD_PROJECT_ID: str = ""
    GOOGLE_CLOUD_LOCATION: str = "us-central1"

    # Cloud Storage (artifacts/gcp-cloud.md). Empty = storage disabled; the app
    # falls back to on-the-fly streaming and storage routes report unconfigured.
    CLOUD_STORAGE_BUCKET: str = ""

    # Service-account key for GCS/Vertex. On Cloud Run leave empty (the attached
    # SA is used automatically). Locally, point at the key JSON — the storage
    # client loads it explicitly, since pydantic reads .env into settings (not
    # os.environ, where the google client would otherwise look).
    GOOGLE_APPLICATION_CREDENTIALS: str = ""

    # Scheduler shared secret (SKILL.md §16 Rule 8)
    CRON_SECRET: str = "dev-cron-secret-change-me"

    # Google OAuth (email_skill/oauth.md)
    GOOGLE_OAUTH_CLIENT_ID: str = ""
    GOOGLE_OAUTH_CLIENT_SECRET: str = ""
    GOOGLE_OAUTH_REDIRECT_URI: str = "http://localhost:8000/api/auth/google/callback"
    NEXT_PUBLIC_APP_URL: str = "http://localhost:3000"
    TOKEN_ENCRYPTION_KEY: str = ""  # Fernet key — run: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Gmail real-time push (watch → Pub/Sub). e.g. projects/<proj>/topics/gmail-intel.
    # Empty = push disabled (sync stays scheduled/manual).
    GMAIL_PUBSUB_TOPIC: str = ""
    # OIDC audience for Pub/Sub push auth — set to your public push URL in prod.
    # Empty = skip JWT verification (local dev).
    GMAIL_PUBSUB_AUDIENCE: str = ""

    # Notion connector — mirrors the canonical KORA task ledger into Notion.
    # Two auth modes:
    #   NOTION_API_KEY        — internal integration (one workspace; simplest, dev/self-host)
    #   NOTION_OAUTH_CLIENT_* — public integration (per-user connect; multi-tenant SaaS)
    # KORA PROVISIONS its own Tasks database under NOTION_PARENT_PAGE_ID so it
    # controls the schema (a user renaming a property can't silently break sync).
    NOTION_API_KEY: str = ""
    NOTION_OAUTH_CLIENT_ID: str = ""
    NOTION_OAUTH_CLIENT_SECRET: str = ""
    NOTION_OAUTH_REDIRECT_URI: str = "http://localhost:8000/api/notion/callback"
    NOTION_PARENT_PAGE_ID: str = ""
    NOTION_VERSION: str = "2022-06-28"

    # Stripe billing
    STRIPE_SECRET_KEY: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_STARTER_PRICE_ID: str = ""
    STRIPE_PRO_PRICE_ID: str = ""
    STRIPE_CONTRACT_PRICE_ID: str = ""

    # Stripe Connect (users connect their own Stripe account for bookkeeping)
    STRIPE_CONNECT_CLIENT_ID: str = ""
    STRIPE_CONNECT_REDIRECT_URI: str = "http://localhost:3000/api/auth/stripe/callback"

    # Sentry (error monitoring — set to empty string to disable)
    SENTRY_DSN: str = ""
    ENVIRONMENT: str = "development"

    # Shared rate-limit store (M6). Set in production so limits apply across
    # all workers (e.g. redis://:password@host:6379/0 or Upstash URL).
    # Empty = in-process limiter (single-instance dev only).
    REDIS_URL: str = ""


settings = Settings()
