from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..config import settings
from .google_auth import get_user_credentials


def _db():
    from supabase import create_client
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)


def get_todays_meetings_with_clients(user_id: str) -> list[dict]:
    """Return today's calendar events enriched with matched Kora client names.

    No AI — pure Calendar API + client email lookup.
    """
    creds = get_user_credentials(user_id)
    if not creds or not settings.SUPABASE_URL:
        return []

    from googleapiclient.discovery import build
    db = _db()
    service = build("calendar", "v3", credentials=creds)
    now = datetime.now(timezone.utc)
    end_of_day = now.replace(hour=23, minute=59, second=59)

    result = service.events().list(
        calendarId="primary",
        timeMin=now.isoformat(),
        timeMax=end_of_day.isoformat(),
        maxResults=10,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    events = result.get("items", [])
    if not events:
        return []

    clients = db.table("clients").select("id, name, email").eq(
        "user_id", user_id).execute().data
    email_map = {c["email"].lower(): c for c in clients if c.get("email")}

    enriched = []
    for ev in events:
        attendees = ev.get("attendees", [])
        matched = [email_map[a.get("email", "").lower()]["name"]
                   for a in attendees if a.get("email", "").lower() in email_map]
        start = ev.get("start", {})
        enriched.append({
            "id": ev["id"],
            "title": ev.get("summary", "Meeting"),
            "start": start.get("dateTime") or start.get("date"),
            "meet_link": ev.get("hangoutLink"),
            "client_names": matched,
            "is_client_meeting": bool(matched),
        })
    return enriched


def get_unlogged_past_meetings(user_id: str) -> list[dict]:
    """Return past-7-day calendar events with known clients that have no meeting record."""
    creds = get_user_credentials(user_id)
    if not creds or not settings.SUPABASE_URL:
        return []

    from googleapiclient.discovery import build
    db = _db()
    service = build("calendar", "v3", credentials=creds)
    now = datetime.now(timezone.utc)
    seven_days_ago = (now - timedelta(days=7)).isoformat()

    result = service.events().list(
        calendarId="primary",
        timeMin=seven_days_ago,
        timeMax=now.isoformat(),
        maxResults=20,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    events = result.get("items", [])
    clients = db.table("clients").select("id, name, email").eq(
        "user_id", user_id).execute().data
    email_map = {c["email"].lower(): c for c in clients if c.get("email")}

    existing = db.table("meetings").select("google_event_id").eq(
        "user_id", user_id).not_.is_("google_event_id", "null").execute().data
    logged_ids = {m["google_event_id"] for m in existing}

    unlogged = []
    for ev in events:
        if ev["id"] in logged_ids:
            continue
        matched = [email_map[a.get("email", "").lower()]
                   for a in ev.get("attendees", [])
                   if a.get("email", "").lower() in email_map]
        if matched:
            unlogged.append({
                "event_id": ev["id"],
                "title": ev.get("summary", "Meeting"),
                "date": (ev.get("start", {}).get("dateTime") or "")[:10],
                "client_names": [c["name"] for c in matched],
                "client_ids": [c["id"] for c in matched],
            })
    return unlogged


def find_availability_slots(
    user_id: str,
    duration_minutes: int = 60,
    days_ahead: int = 7,
) -> list[dict]:
    """Find three free time slots for scheduling a meeting."""
    creds = get_user_credentials(user_id)
    if not creds:
        return []

    from googleapiclient.discovery import build
    service = build("calendar", "v3", credentials=creds)
    now = datetime.now(timezone.utc)

    freebusy = service.freebusy().query(body={
        "timeMin": now.isoformat(),
        "timeMax": (now + timedelta(days=days_ahead)).isoformat(),
        "items": [{"id": "primary"}],
    }).execute()
    busy = freebusy.get("calendars", {}).get("primary", {}).get("busy", [])

    suggestions: list[dict] = []
    current = now.replace(hour=9, minute=0, second=0, microsecond=0)
    if current < now:
        current += timedelta(days=1)

    while len(suggestions) < 3 and current < now + timedelta(days=days_ahead):
        if current.weekday() < 5 and current.hour < 17:
            slot_end = current + timedelta(minutes=duration_minutes)
            overlaps = any(
                datetime.fromisoformat(b["start"].replace("Z", "+00:00")) < slot_end
                and datetime.fromisoformat(b["end"].replace("Z", "+00:00")) > current
                for b in busy
            )
            if not overlaps:
                suggestions.append({
                    "start": current.isoformat(),
                    "end": slot_end.isoformat(),
                    "label": current.strftime("%A, %B %d at %I:%M %p UTC"),
                })
        current += timedelta(hours=1)
        if current.hour >= 17:
            current = (current + timedelta(days=1)).replace(
                hour=9, minute=0, second=0, microsecond=0)

    return suggestions
