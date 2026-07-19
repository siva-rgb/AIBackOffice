# Comms — Meeting Intelligence Agent Reference

The core of the feature. Processes transcripts or notes → extracts structured
intelligence → updates Butler client records → queues follow-up actions.

---

## Three input paths to meeting intelligence

### Path A: Transcript upload (most complete)
User downloads transcript from any meeting tool → uploads file to Kora.
Supports: .txt, .vtt (WebVTT from Google Meet/Zoom), .srt, .docx, .pdf.
Kora strips speaker tags and timestamps → sends clean text to Gemini.

### Path B: Drive transcript (Workspace users)
Google Workspace Business Plus+ auto-saves Meet transcripts to Drive.
If user has Drive access granted, Kora can fetch these automatically
after a calendar event ends.

### Path C: Quick capture (lightest weight, works for any meeting)
User types a few sentences about what happened → meeting_agent enriches it.
Works for phone calls, in-person meetings, Zoom, Teams — anything.
Example: "Call with Harbor Design — they approved homepage, want logo revision,
will pay invoice by Friday. Need to send revised timeline by Tuesday."

---

## Meeting agent service

```python
# app/services/meeting_agent.py
import json
from datetime import datetime
from app.services.vertex_ai import generate_with_retry, getGeminiForAgent
from app.services.agent_logger import log_action
from app.utils.security import sanitize_prompt_input
from supabase import create_client
from app.config import settings


async def process_transcript(
    user_id: str,
    meeting_id: str,
    transcript_text: str,
    source: str = "transcript_upload",
):
    """
    Main entry point. Parses transcript → extracts MOM → updates DB → queues actions.
    Called as a background task after upload.
    """
    start = datetime.utcnow()
    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

    # Get meeting context (client name, engagement)
    meeting = db.table("meetings").select(
        "*, clients(name, what_we_do), engagements(title, status)"
    ).eq("id", meeting_id).single().execute().data

    client_context = ""
    if meeting.get("clients"):
        c = meeting["clients"]
        client_context = f"Client: {c['name']}. Context: {c.get('what_we_do', '')}."

    try:
        # Clean and truncate transcript
        safe_transcript = sanitize_prompt_input(transcript_text[:8000])  # ~6k tokens

        model = getGeminiForAgent("meeting")
        prompt = _build_mom_prompt(safe_transcript, client_context)

        result = await generate_with_retry(lambda: model.generate_content(prompt))
        raw = result.response.candidates[0].content.parts[0].text
        extracted = _parse_mom_response(raw)

        latency_ms = int((datetime.utcnow() - start).total_seconds() * 1000)

        # Update meeting record with extracted intelligence
        db.table("meetings").update({
            "parse_status": "parsed",
            "summary": extracted.get("summary"),
            "decisions": extracted.get("decisions", []),
            "commitments": extracted.get("commitments", []),
            "risks_flagged": extracted.get("risks", []),
            "next_steps": extracted.get("next_steps", []),
            "sentiment": extracted.get("sentiment", "neutral"),
            "ai_confidence": extracted.get("confidence", 0.8),
            "updated_at": datetime.utcnow().isoformat(),
        }).eq("id", meeting_id).execute()

        # Create action items from next_steps
        await _create_action_items(user_id, meeting_id, meeting.get("client_id"),
                                    extracted.get("next_steps", []), db)

        # Create a client note from the meeting
        await _create_meeting_note(user_id, meeting, extracted, db)

        # Update client last_activity_at
        if meeting.get("client_id"):
            db.table("clients").update({"last_activity_at": "now()"}).eq(
                "id", meeting["client_id"]).execute()

        # Queue follow-up email for approval (if commitments were made)
        if extracted.get("commitments") or extracted.get("next_steps"):
            await _queue_meeting_followup(user_id, meeting, extracted, db)

        await log_action(
            user_id=user_id,
            agent_type="meeting_agent",
            action=f"Processed meeting transcript: {meeting.get('title', 'Untitled')}",
            input_data={"meeting_id": meeting_id, "source": source,
                        "transcript_length": len(transcript_text)},
            output_data={
                "decisions": len(extracted.get("decisions", [])),
                "action_items": len(extracted.get("next_steps", [])),
                "sentiment": extracted.get("sentiment"),
            },
            latency_ms=latency_ms,
            triggered_by="user"
        )

    except Exception as e:
        db.table("meetings").update({
            "parse_status": "failed",
        }).eq("id", meeting_id).execute()
        raise


def _build_mom_prompt(transcript: str, client_context: str) -> str:
    return f"""
You are analyzing a business meeting transcript for a freelancer or small business owner.
Extract structured intelligence: key decisions, commitments, risks, and follow-up actions.
Be specific and factual — only extract what is actually stated in the transcript.
If information is unclear, mark confidence low rather than guess.

{f"CONTEXT: {client_context}" if client_context else ""}

TRANSCRIPT:
<transcript>
{transcript}
</transcript>

Return ONLY valid JSON, no markdown, no explanation:
{{
  "summary": "2-3 sentence plain English summary of what was discussed and agreed",
  "sentiment": "positive|neutral|cautious|concerning",
  "confidence": 0.0-1.0,
  "decisions": [
    {{
      "decision": "what was decided — specific and concrete",
      "owner": "name of who decided or who it affects, or null"
    }}
  ],
  "commitments": [
    {{
      "who": "me|client|both — who made the commitment",
      "what": "specific commitment made",
      "by_when": "date mentioned or null",
      "amount": "dollar amount if financial commitment, or null"
    }}
  ],
  "risks": [
    {{
      "risk": "specific concern or risk mentioned",
      "severity": "high|medium|low"
    }}
  ],
  "next_steps": [
    {{
      "action": "specific action item",
      "owner": "me|client|both|third_party",
      "by_when": "date mentioned or null",
      "priority": "high|medium|low"
    }}
  ],
  "financial_mentions": [
    {{
      "type": "invoice|payment|quote|estimate|expense",
      "amount": number or null,
      "context": "what was said about it"
    }}
  ]
}}

Guidelines:
- Only include decisions that are CLEAR and AGREED, not possibilities discussed
- Only include commitments that were EXPLICITLY stated ("I'll send it by Tuesday")
- Risks are concerns mentioned, not hypotheticals
- If the transcript is a quick capture note (not a formal transcript), extract what you can
- Empty arrays are fine if there's nothing to extract for that category
"""


def _parse_mom_response(raw: str) -> dict:
    clean = raw.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        return {
            "summary": raw[:300],
            "sentiment": "neutral",
            "confidence": 0.3,
            "decisions": [], "commitments": [], "risks": [],
            "next_steps": [], "financial_mentions": []
        }


async def _create_action_items(
    user_id: str, meeting_id: str, client_id: str,
    next_steps: list, db
):
    """Create meeting_action_items rows from extracted next_steps."""
    for step in next_steps:
        db.table("meeting_action_items").insert({
            "user_id": user_id,
            "meeting_id": meeting_id,
            "client_id": client_id,
            "description": step.get("action"),
            "owner": step.get("owner", "me"),
            "due_date": step.get("by_when"),
            "priority": step.get("priority", "medium"),
            "status": "open",
        }).execute()


async def _create_meeting_note(
    user_id: str, meeting: dict, extracted: dict, db
):
    """Create a client_note from the meeting summary."""
    if not meeting.get("client_id") or not extracted.get("summary"):
        return

    # Build a rich markdown note
    note_parts = [f"**Meeting:** {meeting.get('title', 'Call')}\n"]
    note_parts.append(f"**Summary:** {extracted['summary']}\n")

    if extracted.get("decisions"):
        note_parts.append("\n**Decisions made:**")
        for d in extracted["decisions"]:
            note_parts.append(f"- {d['decision']}")

    if extracted.get("commitments"):
        note_parts.append("\n**Commitments:**")
        for c in extracted["commitments"]:
            by_when = f" (by {c['by_when']})" if c.get("by_when") else ""
            note_parts.append(f"- {c['who'].title()}: {c['what']}{by_when}")

    if extracted.get("next_steps"):
        note_parts.append("\n**Next steps:**")
        for n in extracted["next_steps"]:
            owner_label = "Me" if n["owner"] == "me" else "Client" if n["owner"] == "client" else "Both"
            by_when = f" → {n['by_when']}" if n.get("by_when") else ""
            note_parts.append(f"- [{owner_label}] {n['action']}{by_when}")

    db.table("client_notes").insert({
        "user_id": user_id,
        "client_id": meeting["client_id"],
        "engagement_id": meeting.get("engagement_id"),
        "meeting_id": meeting["id"],
        "note_type": "meeting",
        "content_md": "\n".join(note_parts),
        "is_ai_generated": True,
    }).execute()


async def _queue_meeting_followup(
    user_id: str, meeting: dict, extracted: dict, db
):
    """Queue a follow-up email to the client summarizing the meeting."""
    if not meeting.get("client_id"):
        return

    client = db.table("clients").select("name, email").eq(
        "id", meeting["client_id"]).single().execute().data
    if not client or not client.get("email"):
        return

    # Build follow-up email content using AI
    from app.services.gmail_agent import queue_gmail_send

    email_body = _build_followup_email(
        client_name=client["name"],
        meeting_title=meeting.get("title", "our call"),
        extracted=extracted,
    )

    await queue_gmail_send(
        user_id=user_id,
        to_email=client["email"],
        to_name=client["name"],
        subject=f"Follow-up: {meeting.get('title', 'Our call')}",
        body_html=email_body["html"],
        body_text=email_body["text"],
        context=f"Post-meeting follow-up for {client['name']} after: {meeting.get('title')}. "
                f"Includes {len(extracted.get('commitments',[]))} commitments and "
                f"{len(extracted.get('next_steps',[]))} next steps.",
        related_client_id=meeting.get("client_id"),
        related_meeting_id=meeting["id"],
    )

    db.table("meetings").update({
        "followup_queued_at": datetime.utcnow().isoformat()
    }).eq("id", meeting["id"]).execute()


def _build_followup_email(
    client_name: str,
    meeting_title: str,
    extracted: dict
) -> dict:
    """Build a clean post-meeting follow-up email."""
    lines_text = [f"Hi {client_name},\n",
                  f"Thanks for the time today. Here's a quick summary of what we covered:\n"]
    lines_html = [f"<p>Hi {client_name},</p>",
                  f"<p>Thanks for the time today. Here's a quick summary of what we covered:</p>"]

    if extracted.get("decisions"):
        lines_text.append("What we decided:")
        lines_html.append("<p><strong>What we decided:</strong></p><ul>")
        for d in extracted["decisions"]:
            lines_text.append(f"  • {d['decision']}")
            lines_html.append(f"<li>{d['decision']}</li>")
        lines_html.append("</ul>")

    my_commitments = [c for c in extracted.get("commitments", []) if c["who"] == "me"]
    their_commitments = [c for c in extracted.get("commitments", []) if c["who"] == "client"]

    if my_commitments:
        lines_text.append("\nOn my end:")
        lines_html.append("<p><strong>On my end:</strong></p><ul>")
        for c in my_commitments:
            by_when = f" by {c['by_when']}" if c.get("by_when") else ""
            lines_text.append(f"  • {c['what']}{by_when}")
            lines_html.append(f"<li>{c['what']}{by_when}</li>")
        lines_html.append("</ul>")

    if their_commitments:
        lines_text.append("\nOn your end:")
        lines_html.append("<p><strong>On your end:</strong></p><ul>")
        for c in their_commitments:
            by_when = f" by {c['by_when']}" if c.get("by_when") else ""
            lines_text.append(f"  • {c['what']}{by_when}")
            lines_html.append(f"<li>{c['what']}{by_when}</li>")
        lines_html.append("</ul>")

    lines_text.extend(["\nLet me know if I've missed anything.", "Talk soon."])
    lines_html.extend(["<p>Let me know if I've missed anything.</p>", "<p>Talk soon.</p>"])

    return {
        "text": "\n".join(lines_text),
        "html": "\n".join(lines_html),
    }
```

---

## Meeting router

```python
# app/routers/meetings.py
from fastapi import APIRouter, Depends, BackgroundTasks, UploadFile, File
from app.dependencies import get_current_user
from app.services.meeting_agent import process_transcript
from app.utils.security import sanitize_prompt_input
from pydantic import BaseModel
from typing import Optional
from uuid import UUID
import io

router = APIRouter(prefix="/meetings", tags=["meetings"])

class MeetingCreate(BaseModel):
    title: str
    meeting_date: str       # ISO datetime
    client_id: Optional[UUID] = None
    engagement_id: Optional[UUID] = None
    meeting_type: str = "call"
    duration_minutes: Optional[int] = None
    attendees: Optional[list] = None

class QuickMeetingNote(BaseModel):
    notes: str              # freeform, processed like quick_capture
    client_id: Optional[UUID] = None
    meeting_date: Optional[str] = None
    title: Optional[str] = None

@router.get("")
async def list_meetings(
    client_id: str = None,
    limit: int = 20,
    user=Depends(get_current_user)
):
    from supabase import create_client
    from app.config import settings
    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    q = db.table("meetings").select(
        "*, clients(name), meeting_action_items(id, description, status, owner)"
    ).eq("user_id", user["id"]).order("meeting_date", desc=True).limit(limit)
    if client_id:
        q = q.eq("client_id", client_id)
    return q.execute().data

@router.post("")
async def create_meeting(body: MeetingCreate, user=Depends(get_current_user)):
    from supabase import create_client
    from app.config import settings
    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    res = db.table("meetings").insert({
        "user_id": user["id"],
        **body.model_dump(exclude_none=True),
        "parse_status": "pending",
        "source": "manual",
    }).execute()
    return res.data[0]

@router.post("/{meeting_id}/transcript")
async def upload_transcript(
    meeting_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user=Depends(get_current_user)
):
    """Upload a transcript file (.txt, .vtt, .srt, .docx, .pdf)."""
    MAX_SIZE = 2 * 1024 * 1024  # 2MB
    ALLOWED_TYPES = ["text/plain", "text/vtt", "application/octet-stream",
                     "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                     "application/pdf"]

    if file.size and file.size > MAX_SIZE:
        from fastapi import HTTPException
        raise HTTPException(413, "Transcript file too large (max 2MB)")

    content = await file.read()

    # Parse based on file type
    transcript_text = _extract_text(content, file.filename or "")

    # Save raw transcript
    from supabase import create_client
    from app.config import settings
    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    db.table("meetings").update({
        "raw_transcript": transcript_text[:10000],  # store first 10k chars
        "source": "transcript_upload",
        "parse_status": "pending",
    }).eq("id", meeting_id).eq("user_id", user["id"]).execute()

    # Parse in background
    background_tasks.add_task(process_transcript, user["id"], meeting_id,
                               transcript_text, "transcript_upload")

    return {"meeting_id": meeting_id, "status": "processing",
            "chars": len(transcript_text)}

@router.post("/quick-note")
async def create_quick_meeting_note(
    body: QuickMeetingNote,
    background_tasks: BackgroundTasks,
    user=Depends(get_current_user)
):
    """Create a meeting from a quick freeform note (no transcript)."""
    safe_notes = sanitize_prompt_input(body.notes)

    from supabase import create_client
    from app.config import settings
    from datetime import datetime
    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

    res = db.table("meetings").insert({
        "user_id": user["id"],
        "client_id": str(body.client_id) if body.client_id else None,
        "title": body.title or "Meeting note",
        "meeting_date": body.meeting_date or datetime.utcnow().isoformat(),
        "meeting_type": "call",
        "raw_notes": safe_notes,
        "source": "quick_capture",
        "parse_status": "pending",
    }).execute()
    meeting_id = res.data[0]["id"]

    background_tasks.add_task(process_transcript, user["id"], meeting_id,
                               safe_notes, "quick_capture")

    return {"meeting_id": meeting_id, "status": "processing"}


def _extract_text(content: bytes, filename: str) -> str:
    """Extract plain text from various transcript file formats."""
    ext = filename.lower().split(".")[-1] if "." in filename else "txt"

    if ext in ("txt", "vtt", "srt"):
        # VTT/SRT: strip timestamps and speaker tags
        text = content.decode("utf-8", errors="ignore")
        lines = []
        for line in text.split("\n"):
            line = line.strip()
            # Skip VTT/SRT timing lines (contain "-->")
            if "-->" in line:
                continue
            # Skip pure timestamp lines and sequence numbers
            import re
            if re.match(r"^\d{2}:\d{2}|^\d+$|^WEBVTT", line):
                continue
            if line:
                lines.append(line)
        return "\n".join(lines)

    elif ext == "pdf":
        import io
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                return "\n".join(page.extract_text() or "" for page in pdf.pages)
        except Exception:
            return content.decode("utf-8", errors="ignore")

    elif ext == "docx":
        try:
            import docx
            doc = docx.Document(io.BytesIO(content))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception:
            return content.decode("utf-8", errors="ignore")

    return content.decode("utf-8", errors="ignore")
```

---

## Supervisor integration for meeting action items

Add to `supervisor.py`'s `gather_state()`:

```python
async def _gather_meeting_context(user_id: str, db) -> dict:
    from datetime import datetime, timedelta
    seven_days_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()

    # Open action items from meetings
    open_actions = db.table("meeting_action_items").select(
        "*, meetings(title, meeting_date), clients(name)"
    ).eq("user_id", user_id).eq("status", "open").execute().data

    overdue_actions = [
        a for a in open_actions
        if a.get("due_date") and a["due_date"] < datetime.utcnow().date().isoformat()
    ]

    recent_meetings = db.table("meetings").select(
        "id, title, meeting_date, parse_status, client_id, clients(name)"
    ).eq("user_id", user_id).gte("meeting_date", seven_days_ago).execute().data

    unparsed = [m for m in recent_meetings if m["parse_status"] == "pending"]

    return {
        "open_action_items": len(open_actions),
        "overdue_action_items": len(overdue_actions),
        "overdue_action_details": [
            f"{a['description']} (from {a['meetings']['title']})"
            for a in overdue_actions[:3]
        ],
        "recent_meetings": len(recent_meetings),
        "unparsed_meetings": len(unparsed),
    }

# In gather_state():
# state["meeting_context"] = await _gather_meeting_context(user_id, db)

# Add to briefing prompt:
"""
MEETING FOLLOW-UPS:
- Open action items: {meeting_context['open_action_items']}
- Overdue: {meeting_context['overdue_action_items']}
{chr(10).join(f"  - {a}" for a in meeting_context['overdue_action_details'])}
- Meetings needing transcript upload: {meeting_context['unparsed_meetings']}
"""
```

---

## Frontend: meetings tab under client workspace

Add a "Meetings" tab to `/butler/clients/[clientId]`:

```
Meetings tab content:
  - "Log a meeting note" button → opens QuickMeetingNote form (title + freeform notes)
  - "Upload transcript" button → file input
  - Meeting list (reverse chronological):
    Each meeting card shows:
      [Date] [Title] [Sentiment chip] [Action items count]
      Expandable: Summary | Decisions | Commitments | Next steps
      "View full note" → opens client note detail
      "Follow-up pending" badge if followup_queued_at is set
  - Empty state: "No meetings logged yet. Use the quick note or upload
    a transcript after your next call with this client."

Action items section (below meetings):
  - Filterable list: open / done
  - Each item: [priority dot] [description] [owner chip] [due date] [mark done]
  - Overdue items highlighted in amber
```

---

## New pip dependencies to add

```
google-auth-oauthlib   # OAuth 2.0 flow
google-api-python-client  # Gmail + Calendar + Drive APIs
google-auth-httplib2   # HTTP transport for google-api
cryptography           # Fernet token encryption
pdfplumber             # PDF transcript reading (already may be installed)
python-docx            # DOCX transcript reading
```

```bash
pip install google-auth-oauthlib google-api-python-client google-auth-httplib2 \
            cryptography pdfplumber python-docx --break-system-packages
```
