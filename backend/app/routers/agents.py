from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from .. import store
from ..dependencies import get_current_user
from ..models import AgentLog, User
from ..services.stats import compute_agent_stats

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("/log", response_model=list[AgentLog])
async def list_logs(user: User = Depends(get_current_user)):
    return store.list_agent_logs(user.id)


@router.get("/log/stats")
async def log_stats(user: User = Depends(get_current_user)):
    return compute_agent_stats(store.list_agent_logs(user.id))


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
