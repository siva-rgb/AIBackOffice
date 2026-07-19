# Google Butler — Calendar Intelligence Reference

Lightweight — no AI needed. Pure structured data from Calendar API.

---

## Calendar intelligence service

```python
# app/services/calendar_intel.py
from datetime import datetime, timedelta, timezone
from googleapiclient.discovery import build
from app.services.google_auth import get_user_credentials
from supabase import create_client
from app.config import settings


async def get_todays_meetings_with_clients(user_id: str) -> list[dict]:
    """
    Get today's calendar events, match attendees to known clients.
    Returns enriched events for the morning briefing. No AI needed.
    """
    creds = await get_user_credentials(user_id)
    if not creds:
        return []

    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    service = build("calendar", "v3", credentials=creds)

    now = datetime.now(timezone.utc)
    end_of_day = now.replace(hour=23, minute=59, second=59)

    events_result = service.events().list(
        calendarId="primary",
        timeMin=now.isoformat(),
        timeMax=end_of_day.isoformat(),
        maxResults=10,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    events = events_result.get("items", [])
    if not events:
        return []

    clients = db.table("clients").select("id, name, email").eq(
        "user_id", user_id).execute().data
    client_email_map = {c["email"].lower(): c for c in clients if c.get("email")}

    enriched = []
    for event in events:
        attendees = event.get("attendees", [])
        matched_clients = []
        for attendee in attendees:
            email = attendee.get("email", "").lower()
            if email in client_email_map:
                matched_clients.append(client_email_map[email]["name"])

        start = event.get("start", {})
        enriched.append({
            "id": event["id"],
            "title": event.get("summary", "Meeting"),
            "start": start.get("dateTime") or start.get("date"),
            "meet_link": event.get("hangoutLink"),
            "client_names": matched_clients,
            "is_client_meeting": len(matched_clients) > 0,
        })

    return enriched


async def get_unlogged_past_meetings(user_id: str) -> list[dict]:
    """
    Find calendar events from the past 7 days with known clients
    that have no meeting record in Kora yet. Used to prompt user
    to upload transcript or log notes.
    """
    creds = await get_user_credentials(user_id)
    if not creds:
        return []

    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    service = build("calendar", "v3", credentials=creds)

    now = datetime.now(timezone.utc)
    seven_days_ago = (now - timedelta(days=7)).isoformat()

    events_result = service.events().list(
        calendarId="primary",
        timeMin=seven_days_ago,
        timeMax=now.isoformat(),
        maxResults=20,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    events = events_result.get("items", [])
    clients = db.table("clients").select("id, name, email").eq(
        "user_id", user_id).execute().data
    client_email_map = {c["email"].lower(): c for c in clients if c.get("email")}

    existing = db.table("meetings").select("google_event_id").eq(
        "user_id", user_id).not_.is_("google_event_id", "null").execute().data
    logged_event_ids = {m["google_event_id"] for m in existing}

    unlogged = []
    for event in events:
        if event["id"] in logged_event_ids:
            continue
        attendees = event.get("attendees", [])
        matched = [
            client_email_map[a.get("email", "").lower()]
            for a in attendees
            if a.get("email", "").lower() in client_email_map
        ]
        if matched:
            unlogged.append({
                "event_id": event["id"],
                "title": event.get("summary", "Meeting"),
                "date": event.get("start", {}).get("dateTime", "")[:10],
                "client_names": [c["name"] for c in matched],
                "client_ids": [c["id"] for c in matched],
            })

    return unlogged


async def find_availability_slots(
    user_id: str,
    duration_minutes: int = 60,
    days_ahead: int = 7,
) -> list[dict]:
    """Find three available time slots for scheduling a meeting."""
    creds = await get_user_credentials(user_id)
    if not creds:
        return []

    service = build("calendar", "v3", credentials=creds)
    now = datetime.now(timezone.utc)

    freebusy_result = service.freebusy().query(body={
        "timeMin": now.isoformat(),
        "timeMax": (now + timedelta(days=days_ahead)).isoformat(),
        "items": [{"id": "primary"}],
    }).execute()

    busy_slots = freebusy_result.get("calendars", {}).get("primary", {}).get("busy", [])

    suggestions = []
    current = now.replace(hour=9, minute=0, second=0, microsecond=0)
    if current < now:
        current += timedelta(days=1)

    while len(suggestions) < 3 and current < now + timedelta(days=days_ahead):
        if current.weekday() < 5:
            slot_end = current + timedelta(minutes=duration_minutes)
            overlaps = any(
                datetime.fromisoformat(b["start"].replace("Z", "+00:00")) < slot_end and
                datetime.fromisoformat(b["end"].replace("Z", "+00:00")) > current
                for b in busy_slots
            )
            if not overlaps and current.hour < 17:
                suggestions.append({
                    "start": current.isoformat(),
                    "end": slot_end.isoformat(),
                    "label": current.strftime("%A, %B %-d at %-I:%M %p UTC"),
                })
        current += timedelta(hours=1)
        if current.hour >= 17:
            current = (current + timedelta(days=1)).replace(
                hour=9, minute=0, second=0, microsecond=0)

    return suggestions
```
