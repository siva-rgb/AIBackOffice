from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..dependencies import get_current_user
from ..entitlements import enforce_plan
from ..models import User
from ..services.cashflow_agent import compute_forecast

router = APIRouter(prefix="/api/cashflow", tags=["cashflow"])


@router.get("/forecast", dependencies=[Depends(enforce_plan)])
async def forecast(
    horizon: int = Query(default=90, ge=30, le=90),
    user: User = Depends(get_current_user),
):
    return compute_forecast(user.id, horizon_days=horizon)
