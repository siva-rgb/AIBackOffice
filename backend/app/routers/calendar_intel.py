from __future__ import annotations

from fastapi import APIRouter, Depends

from ..dependencies import get_current_user
from ..models import CamelModel, User
from ..utils.casing import camelize
from ..services.calendar_intel import (
    find_availability_slots,
    get_todays_meetings_with_clients,
    get_unlogged_past_meetings,
)
from ..services.calendar_agent import queue_calendar_event

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


class ScheduleRequest(CamelModel):
    title: str
    start_datetime: str
    duration_minutes: int = 60
    attendee_emails: list[str] = []
    attendee_names: list[str] = []
    description: str = ""
    client_id: str | None = None


@router.get("/today")
async def todays_meetings(user: User = Depends(get_current_user)):
    """Return today's calendar events enriched with matched Kora clients."""
    return camelize(get_todays_meetings_with_clients(user.id))


@router.get("/unlogged")
async def unlogged_meetings(user: User = Depends(get_current_user)):
    """Return past-7-day meetings with known clients that have no Kora meeting record."""
    return camelize(get_unlogged_past_meetings(user.id))


@router.get("/availability")
async def availability(
    duration_minutes: int = 60,
    days_ahead: int = 7,
    user: User = Depends(get_current_user),
):
    """Find three free time slots for scheduling a meeting."""
    return camelize(find_availability_slots(user.id, duration_minutes, days_ahead))


@router.post("/schedule")
async def schedule_meeting(
    body: ScheduleRequest,
    user: User = Depends(get_current_user),
):
    """Queue a calendar event for HITL approval (never creates directly)."""
    queue_calendar_event(
        user_id=user.id,
        title=body.title,
        start_datetime=body.start_datetime,
        duration_minutes=body.duration_minutes,
        attendee_emails=body.attendee_emails,
        attendee_names=body.attendee_names,
        description=body.description,
        client_id=body.client_id,
    )
    return {"status": "queued_for_approval"}
