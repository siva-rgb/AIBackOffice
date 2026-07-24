from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from fastapi import HTTPException

from .. import store
from ..dependencies import get_current_user
from ..models import Alert, User
from ..services.alert_agent import queue_digest_email, run_digest
from ..services.stats import compute_agent_stats

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/alerts", response_model=list[Alert])
async def list_alerts(user: User = Depends(get_current_user)):
    return store.list_alerts(user.id)


@router.post("/alerts/digest")
async def run_alerts_digest(user: User = Depends(get_current_user)):
    """Run the daily digest agent now (demo button / Cloud Scheduler path)."""
    return run_digest(user.id, triggered_by="user")


@router.post("/alerts/digest/email")
async def email_alerts_digest(user: User = Depends(get_current_user)):
    """Queue the daily digest to be emailed to the user — behind the approval
    gate. Never sends here; it creates a send_email_gmail task the user approves
    in the Business Manager (or degrades to draft-only if Gmail isn't connected)."""
    return queue_digest_email(user.id, triggered_by="user")


@router.patch("/alerts/{alert_id}/read", response_model=Alert)
async def mark_read(alert_id: str, user: User = Depends(get_current_user)):
    alert = store.mark_alert_read(user.id, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Not found")
    return alert


@router.get("/overview")
async def overview(user: User = Depends(get_current_user)):
    """Consolidated data for the dashboard home so the frontend server
    component makes a single call."""
    txns = store.list_transactions(user.id)
    invoices = store.list_invoices(user.id)
    logs = store.list_agent_logs(user.id)
    alerts = store.list_alerts(user.id)
    stats = compute_agent_stats(logs)

    now = datetime.now(timezone.utc)
    month_income = sum(
        abs(t.amount)
        for t in txns
        if t.type == "income"
        and t.date[:7] == now.date().isoformat()[:7]
    )
    outstanding = sum(i.total for i in invoices if i.status in ("sent", "overdue", "viewed"))
    overdue_count = sum(1 for i in invoices if i.status == "overdue")
    unread = [a for a in alerts if not a.read]

    return {
        "user": {"fullName": user.full_name, "businessName": user.business_name, "currency": user.currency},
        "monthIncome": round(month_income, 2),
        "outstanding": round(outstanding, 2),
        "overdueCount": overdue_count,
        "agentStats": stats,
        "unreadAlerts": [a.model_dump(by_alias=True) for a in unread],
        "recentActivity": [l.model_dump(by_alias=True) for l in logs[:6]],
    }
