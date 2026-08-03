from __future__ import annotations

import csv
import io
from typing import List

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from .. import store
from ..dependencies import get_current_user
from ..models import AgentLog, User
from ..services.stats import compute_agent_stats, compute_dashboard_stats

router = APIRouter(prefix="/api/agents", tags=["agents"])


# Note: the decorator's `response_model` is evaluated at import time, so we use
# `typing.List[AgentLog]` rather than the 3.9+ `list[AgentLog]` — this file
# still has to import on Python 3.8 (M3's mock-mode conftest pins it).
@router.get("/log", response_model=List[AgentLog])
async def list_logs(user: User = Depends(get_current_user)):
    return store.list_agent_logs(user.id)


@router.get("/log/stats")
async def log_stats(user: User = Depends(get_current_user)):
    return compute_agent_stats(store.list_agent_logs(user.id))


@router.get("/log/dashboard")
async def log_dashboard(
    window_days: int = Query(default=14, ge=1, le=90),
    user: User = Depends(get_current_user),
):
    """M11.3 — richer KPI surface for the business-metrics dashboard.

    Includes everything `compute_agent_stats` returns, plus per-day series,
    cost-by-model, p50/p95 latency, total tokens and top-3 error actions.
    """
    return compute_dashboard_stats(store.list_agent_logs(user.id), window_days=window_days)


@router.get("/log/export")
async def export_logs(user: User = Depends(get_current_user)):
    logs = store.list_agent_logs(user.id)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "created_at",
            "agent_type",
            "action",
            "triggered_by",
            "status",
            "model_used",
            "tokens_used",
            "latency_ms",
            "cost_usd",
        ]
    )
    for log_entry in logs:
        writer.writerow(
            [
                log_entry.created_at,
                log_entry.agent_type,
                log_entry.action,
                log_entry.triggered_by,
                log_entry.status,
                log_entry.model_used,
                log_entry.tokens_used,
                log_entry.latency_ms,
                log_entry.cost_usd,
            ]
        )
    from datetime import date

    filename = f"kora-agent-logs-{date.today().isoformat()}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
