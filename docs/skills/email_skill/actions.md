# Google Butler — Actions Reference

Every action here goes through `manager_tasks` with `status='proposed'`.
Nothing executes without the user clicking Approve. No exceptions.

---

## Gmail send on behalf of user

```python
# app/services/gmail_agent.py
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from googleapiclient.discovery import build
from app.services.google_auth import get_user_credentials
from app.services.agent_logger import log_action
from datetime import datetime
from supabase import create_client
from app.config import settings


async def queue_gmail_send(
    user_id: str,
    to_email: str,
    to_name: str,
    subject: str,
    body_html: str,
    body_text: str,
    context: str,
    related_client_id: str = None,
    related_meeting_id: str = None,
):
    """Queue a Gmail send for HITL approval. Never sends directly."""
    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

    conn = db.table("google_connections").select("google_email").eq(
        "user_id", user_id).single().execute().data
    from_email = conn["google_email"] if conn else "your Gmail"

    db.table("manager_tasks").insert({
        "user_id": user_id,
        "kind": "send_email_gmail",
        "title": f"Send email to {to_name}: {subject}",
        "rationale": context,
        "severity": "info",
        "status": "proposed",
        "payload": {
            "to_email": to_email,
            "to_name": to_name,
            "subject": subject,
            "body_html": body_html,
            "body_text": body_text,
            "from_email": from_email,
            "related_client_id": related_client_id,
            "related_meeting_id": related_meeting_id,
        },
        "source_record_type": "meeting" if related_meeting_id else "client",
        "source_record_id": related_meeting_id or related_client_id,
    }).execute()


async def execute_gmail_send(user_id: str, task_payload: dict) -> bool:
    """Called ONLY when user approves the manager_task."""
    start = datetime.utcnow()
    creds = await get_user_credentials(user_id)
    if not creds:
        raise ValueError("Google account not connected")

    service = build("gmail", "v1", credentials=creds)

    msg = MIMEMultipart("alternative")
    msg["To"] = f"{task_payload['to_name']} <{task_payload['to_email']}>"
    msg["Subject"] = task_payload["subject"]
    msg.attach(MIMEText(task_payload["body_text"], "plain"))
    msg.attach(MIMEText(task_payload["body_html"], "html"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    result = service.users().messages().send(
        userId="me", body={"raw": raw}
    ).execute()

    latency_ms = int((datetime.utcnow() - start).total_seconds() * 1000)
    await log_action(
        user_id=user_id,
        agent_type="gmail_agent",
        action=f"Sent email to {task_payload['to_email']}: {task_payload['subject']}",
        input_data={"to": task_payload["to_email"], "subject": task_payload["subject"]},
        output_data={"gmail_message_id": result.get("id")},
        latency_ms=latency_ms,
        triggered_by="user"
    )
    return True
```

---

## Calendar event creation

```python
# app/services/calendar_agent.py
from datetime import datetime, timedelta, timezone
from googleapiclient.discovery import build
from app.services.google_auth import get_user_credentials
from app.services.agent_logger import log_action
from supabase import create_client
from app.config import settings


async def queue_calendar_event(
    user_id: str,
    title: str,
    start_datetime: str,
    duration_minutes: int,
    attendee_emails: list[str],
    attendee_names: list[str],
    description: str = "",
    client_id: str = None,
):
    """Queue a calendar event for HITL approval. Never creates directly."""
    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
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


async def execute_calendar_event(user_id: str, task_payload: dict) -> dict:
    """Called ONLY when user approves the manager_task."""
    start = datetime.utcnow()
    creds = await get_user_credentials(user_id)
    if not creds:
        raise ValueError("Google account not connected")

    service = build("calendar", "v3", credentials=creds)

    start_dt = task_payload["start_datetime"]
    end_dt = (
        datetime.fromisoformat(start_dt) +
        timedelta(minutes=task_payload["duration_minutes"])
    ).isoformat()

    event_body = {
        "summary": task_payload["title"],
        "description": task_payload.get("description", ""),
        "start": {"dateTime": start_dt, "timeZone": "UTC"},
        "end": {"dateTime": end_dt, "timeZone": "UTC"},
        "attendees": [{"email": e} for e in task_payload["attendee_emails"]],
        "conferenceData": {
            "createRequest": {
                "requestId": f"kora-{user_id[:8]}-{start_dt[:10]}",
                "conferenceSolutionKey": {"type": "hangoutsMeet"}
            }
        },
    }

    created = service.events().insert(
        calendarId="primary",
        body=event_body,
        conferenceDataVersion=1,
        sendUpdates="all",
    ).execute()

    latency_ms = int((datetime.utcnow() - start).total_seconds() * 1000)
    meet_link = created.get("hangoutLink")
    event_id = created.get("id")

    # Create meeting record in Kora DB
    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    db.table("meetings").insert({
        "user_id": user_id,
        "client_id": task_payload.get("client_id"),
        "title": task_payload["title"],
        "meeting_type": "video",
        "meeting_date": start_dt,
        "duration_minutes": task_payload["duration_minutes"],
        "attendees": [
            {"name": n, "email": e}
            for n, e in zip(task_payload.get("attendee_names", []),
                           task_payload["attendee_emails"])
        ],
        "google_event_id": event_id,
        "meet_link": meet_link,
        "source": "calendar_import",
        "parse_status": "pending",
    }).execute()

    await log_action(
        user_id=user_id,
        agent_type="calendar_agent",
        action=f"Created meeting: {task_payload['title']}",
        input_data={"attendees": task_payload["attendee_emails"]},
        output_data={"event_id": event_id, "meet_link": meet_link},
        latency_ms=latency_ms,
        triggered_by="user"
    )

    return {"event_id": event_id, "meet_link": meet_link}
```

---

## Dispatch approved tasks

Add this to the existing task approval handler:

```python
# In the manager_tasks approve endpoint, extend the dispatch logic:

async def dispatch_approved_task(user_id: str, task: dict):
    kind = task["kind"]
    payload = task.get("payload", {})

    if kind == "send_email_gmail":
        from app.services.gmail_agent import execute_gmail_send
        await execute_gmail_send(user_id, payload)

    elif kind == "create_calendar_event":
        from app.services.calendar_agent import execute_calendar_event
        await execute_calendar_event(user_id, payload)

    elif kind == "send_meeting_followup":
        from app.services.gmail_agent import execute_gmail_send
        await execute_gmail_send(user_id, payload)

    # ... existing dispatchers for send_followup, send_demand, etc.
```
