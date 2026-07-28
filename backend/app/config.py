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

    # Backends. AI: 'auto' (default) uses the OpenAI-compatible gateway when
    # MODEL_API_KEY is set, otherwise the deterministic mock. Force with
    # 'openai' / 'mock' / 'vertex'. Data: 'mock' (in-memory) or 'supabase'.
    KORA_DATA_BACKEND: str = "mock"
    KORA_AI_BACKEND: str = "auto"

    # OpenAI-compatible LLM gateway (e.g. the PwC GenAI shared service used for
    # development; swap to Google Vertex AI for production per SKILL.md §7).
    MODEL_API_KEY: str = ""
    BASE_URL: str = ""
    MODEL_NAME: str = "azure.gpt-4.1"

    # Embeddings for semantic/hybrid memory recall — uses the same OpenAI-
    # compatible gateway above. Must be a model your key exposes (this gateway
    # prefixes them like the chat models: azure.text-embedding-3-small /
    # -3-large / -ada-002, or vertex_ai.text-embedding-005). Empty or an
    # unavailable model disables semantic ranking gracefully — recall then falls
    # back to lexical-only, so the feature never hard-breaks.
    EMBEDDING_MODEL: str = "azure.text-embedding-3-small"

    FRONTEND_ORIGIN: str = "http://localhost:3000"

    # Supabase (service role — backend only)
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""

    # Demo bridge: until the frontend login is wired, requests without a valid
    # Supabase JWT resolve to this seeded demo user. Set ALLOW_DEMO_USER=false
    # to require real auth.
    DEMO_EMAIL: str = "demo@kora.app"
    ALLOW_DEMO_USER: bool = True

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
