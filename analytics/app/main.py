"""kora-analytics — a standalone usage dashboard for the Kora deployment.

Runs as its own Cloud Run service, in its own container, with its own
dependencies. It reads the product's database and writes nothing, so it can be
deployed, restarted or deleted without any effect on the product itself.

No authentication, by request. Two consequences follow, and both are handled
here rather than assumed away:

  * anything rendered is readable by anyone holding the URL, so email addresses
    are masked unless ANALYTICS_SHOW_EMAILS is explicitly set (see config.py);
  * the service accepts no input that reaches a query — every route is a
    parameterless read — because the service-role key it holds is exactly the
    credential that bypasses row-level security.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from . import config
from .metrics import get_snapshot

STATIC = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="Kora analytics", docs_url=None, redoc_url=None)


@app.get("/health")
async def health() -> dict:
    """Liveness only — deliberately does not touch the database, so a database
    blip cannot make Cloud Run recycle a container that is otherwise fine.

    NOT `/healthz`: that path is intercepted by Google's frontend and never
    reaches the container. It answers a Google 404 page while every other route
    on the same host works, and nothing appears in the Cloud Run request log —
    which is how this was found, since the endpoint worked perfectly in local
    testing and only failed once deployed.
    """
    return {"ok": True}


@app.get("/api/stats")
async def stats(refresh: bool = False) -> JSONResponse:
    try:
        return JSONResponse(get_snapshot(force=refresh))
    except Exception as exc:
        # Say what broke. A dashboard that renders "—" everywhere with a green
        # HTTP 200 is worse than one that admits it could not read the database.
        return JSONResponse(
            {"error": f"{type(exc).__name__}: {str(exc)[:200]}"},
            status_code=503,
        )


@app.get("/")
async def dashboard() -> FileResponse:
    return FileResponse(STATIC / "index.html", media_type="text/html")


@app.get("/config")
async def visible_config() -> dict:
    """What this instance is configured to do — no secrets, just the switches."""
    return {
        "emailsMasked": not config.SHOW_EMAILS,
        "testAccounts": len(config.TEST_ACCOUNTS),
        "cacheTtlSeconds": config.CACHE_TTL_SECONDS,
    }
