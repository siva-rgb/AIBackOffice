from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

from .. import store

router = APIRouter(prefix="/api/public", tags=["public"])


@router.get("/stats")
async def public_stats():
    """Aggregate agent activity across all users for the landing page's live
    counters (SKILL.md §23). No auth, no user filter — counts only."""
    logs = store.list_all_agent_logs()
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    def _dt(log_entry):
        try:
            return datetime.fromisoformat(log_entry.created_at)
        except ValueError:
            return now

    return {
        "actionsToday": sum(1 for log_entry in logs if log_entry.created_at[:10] >= today),
        "followUpsSentThisWeek": sum(1 for log_entry in logs if log_entry.agent_type == "invoice_follow_up" and _dt(log_entry) >= week_ago),
        "contractsThisMonth": sum(1 for log_entry in logs if log_entry.agent_type == "contract_generator" and _dt(log_entry) >= month_ago),
        "totalActions": len(logs),
    }
