from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .middleware.security_headers import SecurityHeadersMiddleware
from .routers import (
    account,
    agents,
    auth_google,
    bookkeeping,
    butler,
    calendar_intel,
    cashflow,
    clients,
    contracts,
    dashboard,
    drive_intel,
    gmail_intel,
    graph,
    invoices,
    manager,
    meetings,
    memory,
    notion,
    playbook,
    proposals,
    public,
    retainers,
    storage,
    stripe_billing,
    stories,
    stripe_connect,
    tasks,
    users,
)

logger = logging.getLogger("kora")

# Sentry — initialise before the app so all exceptions are captured.
# Disabled when SENTRY_DSN is empty (dev default).
if settings.SENTRY_DSN:
    import sentry_sdk

    def _scrub_sensitive_data(event, hint):
        if event.get("extra"):
            for key in list(event["extra"].keys()):
                if any(
                    s in key.lower()
                    for s in [
                        "amount",
                        "total",
                        "income",
                        "expense",
                        "balance",
                        "transaction",
                        "bank",
                        "token",
                        "secret",
                        "password",
                        "email_body",
                        "transcript",
                        "raw_text",
                    ]
                ):
                    event["extra"][key] = "[REDACTED]"
        request = event.get("request", {})
        if request.get("data"):
            request["data"] = "[REDACTED]"
        return event

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        traces_sample_rate=0.05,
        before_send=_scrub_sensitive_data,
    )

app = FastAPI(
    title="Kora API",
    description="AI back-office for freelancers — FastAPI backend (SKILL.md §2/§3).",
    version="0.1.0",
)

app.add_middleware(SecurityHeadersMiddleware)

# CORS so the Next.js frontend can call the API with the Supabase JWT.
# In production only the deployed origin (FRONTEND_ORIGIN) is allowed; the
# localhost dev origins (incl. :3001, Next's busy-port fallback) are added ONLY
# outside production so prod CORS isn't loosened by hardcoded localhost.
_cors_origins = [settings.FRONTEND_ORIGIN]
if settings.ENVIRONMENT != "production":
    _cors_origins += [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    # Never leak stack traces to the client (SKILL.md §19).
    logger.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"error": "An unexpected error occurred"})


@app.get("/health")
async def health():
    from .services.vertex_ai import active_provider_name

    return {
        "status": "ok",
        "service": "kora-api",
        "dataBackend": settings.KORA_DATA_BACKEND,
        "aiBackend": settings.KORA_AI_BACKEND,
        "activeModel": active_provider_name(),
    }


app.include_router(account.router)
app.include_router(bookkeeping.router)
app.include_router(invoices.router)
app.include_router(contracts.router)
app.include_router(cashflow.router)
app.include_router(agents.router)
app.include_router(dashboard.router)
app.include_router(users.router)
app.include_router(manager.router)
app.include_router(butler.router)
app.include_router(clients.router)
app.include_router(playbook.router)
app.include_router(proposals.router)
app.include_router(retainers.router)
app.include_router(storage.router)
app.include_router(public.router)
# Google Butler (email_skill/)
app.include_router(stripe_billing.router)
app.include_router(stripe_connect.router)
app.include_router(auth_google.router)
app.include_router(gmail_intel.router)
app.include_router(drive_intel.router)
app.include_router(calendar_intel.router)
app.include_router(meetings.router)
app.include_router(graph.router)
app.include_router(memory.router)
app.include_router(tasks.router)
app.include_router(stories.router)
app.include_router(notion.router)
