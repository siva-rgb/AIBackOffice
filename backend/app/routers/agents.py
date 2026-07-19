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
    writer.writerow([
        "created_at", "agent_type", "action", "triggered_by", "status",
        "model_used", "tokens_used", "latency_ms", "cost_usd",
    ])
    for l in logs:
        writer.writerow([
            l.created_at, l.agent_type, l.action, l.triggered_by, l.status,
            l.model_used, l.tokens_used, l.latency_ms, l.cost_usd,
        ])
    from datetime import date

    filename = f"kora-agent-logs-{date.today().isoformat()}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
