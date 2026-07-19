from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..config import settings
from . import agent_logger
from .google_auth import get_user_credentials


def _db():
    from supabase import create_client
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)


def queue_calendar_event(
    user_id: str,
    title: str,
    start_datetime: str,
    duration_minutes: int,
    attendee_emails: list[str],
    attendee_names: list[str],
    description: str = "",
    client_id: str | None = None,
) -> None:
    """Insert a create_calendar_event manager_task for HITL approval. Never creates directly."""
    if not settings.SUPABASE_URL:
        return
    db = _db()
    db.table("manager_tasks").insert({
        "user_id": user_id,
        "kind": "create_calendar_event",
        "title": f"Schedule: {title} with {', '.join(attendee_names or attendee_emails)}",
        "rationale": f"{title} on {start_datetime[:10]} for {duration_minutes} min",
        "severity": "info",
        "status": "proposed",
        "payload": {
            "title": title,
            "start_datetime": start_datetime,
            "duration_minutes": duration_minutes,
            "attendee_emails": attendee_emails,
            "attendee_names": attendee_names,
            "description": description,
            "client_id": client_id,
        },
        "source_record_type": "client",
        "source_record_id": client_id,
    }).execute()


def execute_calendar_event(user_id: str, task_payload: dict) -> dict:
    """Execute an approved create_calendar_event task. Called only from approve_task."""
    start = datetime.now(timezone.utc)
    creds = get_user_credentials(user_id)
    if not creds:
        raise ValueError("Google account not connected")

    from googleapiclient.discovery import build
    service = build("calendar", "v3", credentials=creds)

    start_dt = task_payload["start_datetime"]
    end_dt = (
        datetime.fromisoformat(start_dt) +
        timedelta(minutes=int(task_payload["duration_minutes"]))
    ).isoformat()

    event_body = {
        "summary": task_payload["title"],
        "description": task_payload.get("description", ""),
        "start": {"dateTime": start_dt, "timeZone": "UTC"},
        "end": {"dateTime": end_dt, "timeZone": "UTC"},
        "attendees": [{"email": e} for e in task_payload.get("attendee_emails", [])],
        "conferenceData": {
            "createRequest": {
                "requestId": f"kora-{user_id[:8]}-{start_dt[:10]}",
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
    }

    created = service.events().insert(
        calendarId="primary",
        body=event_body,
        conferenceDataVersion=1,
        sendUpdates="all",
    ).execute()

    latency_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
    meet_link = created.get("hangoutLink")
    event_id = created.get("id")

    if settings.SUPABASE_URL:
        db = _db()
        db.table("meetings").insert({
            "user_id": user_id,
            "client_id": task_payload.get("client_id"),
            "title": task_payload["title"],
            "meeting_type": "video",
            "meeting_date": start_dt,
            "duration_minutes": task_payload["duration_minutes"],
            "attendees": [
                {"name": n, "email": e}
                for n, e in zip(
                    task_payload.get("attendee_names", []),
                    task_payload.get("attendee_emails", []),
                )
            ],
            "google_event_id": event_id,
            "meet_link": meet_link,
            "source": "calendar_import",
            "parse_status": "pending",
        }).execute()

    agent_logger.log_action(
        user_id=user_id,
        agent_type="calendar_agent",
        action=f"Created meeting: {task_payload['title']}",
        input={"attendees": task_payload.get("attendee_emails")},
        output={"event_id": event_id, "meet_link": meet_link},
        latency_ms=latency_ms,
        triggered_by="user",
        source_record_type="client",
        source_record_id=task_payload.get("client_id"),
    )
    return {"event_id": event_id, "meet_link": meet_link}
