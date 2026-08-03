from __future__ import annotations

import io
import json
import re
from datetime import datetime, timezone

from ..config import settings
from ..utils.security import sanitize_prompt_input
from . import agent_logger
from .vertex_ai import generate_with_retry, get_ai


def _db():
    from supabase import create_client

    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Main entry point ────────────────────────────────────────────────────────


def process_transcript(
    user_id: str,
    meeting_id: str,
    transcript_text: str,
    source: str = "transcript_upload",
) -> None:
    """Parse transcript → extract MOM → update DB → queue follow-up.

    Runs as a background task after transcript upload or Drive sync.
    Never raises into the caller — failures update parse_status='failed'.
    """
    if not settings.SUPABASE_URL:
        return

    start = datetime.now(timezone.utc)
    db = _db()

    meeting = db.table("meetings").select("*, clients(name, what_we_do), engagements(title, status)").eq("id", meeting_id).single().execute().data
    if not meeting:
        return

    client_context = ""
    if meeting.get("clients"):
        c = meeting["clients"]
        client_context = f"Client: {c['name']}. Context: {c.get('what_we_do', '')}."

    try:
        safe_transcript = sanitize_prompt_input(transcript_text[:8000])
        prompt = _build_mom_prompt(safe_transcript, client_context)

        ai = get_ai()
        call = generate_with_retry(lambda: ai.extract_meeting_mom({"prompt": prompt}))
        latency_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
        raw = call.data if isinstance(call.data, str) else json.dumps(call.data)
        extracted = _parse_mom_response(raw)

        db.table("meetings").update(
            {
                "parse_status": "parsed",
                "summary": extracted.get("summary"),
                "decisions": extracted.get("decisions", []),
                "commitments": extracted.get("commitments", []),
                "risks_flagged": extracted.get("risks", []),
                "next_steps": extracted.get("next_steps", []),
                "sentiment": extracted.get("sentiment", "neutral"),
                "ai_confidence": extracted.get("confidence", 0.8),
                "updated_at": _now(),
            }
        ).eq("id", meeting_id).eq("user_id", user_id).execute()
        try:
            from .playbook import observe_meeting

            observe_meeting(user_id, meeting.get("client_id"), extracted)
        except Exception:
            pass

        _create_action_items(user_id, meeting_id, meeting.get("client_id"), extracted.get("next_steps", []), db)
        _create_meeting_note(user_id, meeting, extracted, db)

        if meeting.get("client_id"):
            db.table("clients").update(
                {
                    "last_activity_at": _now(),
                }
            ).eq(
                "id", meeting["client_id"]
            ).eq("user_id", user_id).execute()

        if extracted.get("commitments") or extracted.get("next_steps"):
            _queue_meeting_followup(user_id, meeting, extracted, db)

        agent_logger.log_action(
            user_id=user_id,
            agent_type="meeting_agent",
            action=f"Processed transcript: {meeting.get('title', 'Untitled')}",
            input={"meetingId": meeting_id, "source": source, "chars": len(transcript_text)},
            output={
                "decisions": len(extracted.get("decisions", [])),
                "actionItems": len(extracted.get("next_steps", [])),
                "sentiment": extracted.get("sentiment"),
            },
            model_used=call.model_used or "deterministic",
            tokens_used=call.tokens_used,
            latency_ms=latency_ms,
            cost_usd=call.cost_usd,
            triggered_by="user",
            source_record_type="meeting",
            source_record_id=meeting_id,
        )

    except Exception as exc:
        print(f"[meeting-agent] transcript processing failed: {exc}")
        db.table("meetings").update(
            {
                "parse_status": "failed",
                "updated_at": _now(),
            }
        ).eq(
            "id", meeting_id
        ).eq("user_id", user_id).execute()


def _build_mom_prompt(transcript: str, client_context: str) -> str:
    return f"""You are analyzing a business meeting transcript for a freelancer or small business owner.
Extract structured intelligence: key decisions, commitments, risks, and follow-up actions.
Only extract what is actually stated — if unclear, mark confidence low.

{f"CONTEXT: {client_context}" if client_context else ""}

TRANSCRIPT:
<transcript>
{transcript}
</transcript>

Return ONLY valid JSON, no markdown:
{{
  "summary": "2-3 sentence plain English summary of what was discussed and agreed",
  "sentiment": "positive|neutral|cautious|concerning",
  "confidence": 0.0-1.0,
  "decisions": [{{"decision": "what was decided", "owner": "name or null"}}],
  "commitments": [{{"who": "me|client|both", "what": "commitment", "by_when": "date or null", "amount": "amount or null"}}],
  "risks": [{{"risk": "specific concern", "severity": "high|medium|low"}}],
  "next_steps": [{{"action": "specific action", "owner": "me|client|both|third_party", "by_when": "date or null", "priority": "high|medium|low"}}],
  "financial_mentions": [{{"type": "invoice|payment|quote|estimate|expense", "amount": null, "context": "brief"}}]
}}

Rules: only include CLEAR, AGREED decisions; only EXPLICITLY stated commitments; empty arrays are fine."""


def _parse_mom_response(raw: str) -> dict:
    clean = raw.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        return {
            "summary": raw[:300],
            "sentiment": "neutral",
            "confidence": 0.3,
            "decisions": [],
            "commitments": [],
            "risks": [],
            "next_steps": [],
            "financial_mentions": [],
        }


def _create_action_items(user_id: str, meeting_id: str, client_id: str | None, next_steps: list, db) -> None:
    # Task ledger — every action item also becomes tracked work, so a commitment
    # made in a meeting can't be lost. Idempotent per (meeting, action).
    try:
        from .task_ledger import auto_capture_from_meeting

        auto_capture_from_meeting(user_id, client_id, next_steps, meeting_id)
    except Exception as exc:
        print(f"[meetings] task capture skipped: {exc}")

    for step in next_steps:
        try:
            db.table("meeting_action_items").insert(
                {
                    "user_id": user_id,
                    "meeting_id": meeting_id,
                    "client_id": client_id,
                    "description": step.get("action", ""),
                    "owner": step.get("owner", "me"),
                    "due_date": step.get("by_when"),
                    "priority": step.get("priority", "medium"),
                    "status": "open",
                }
            ).execute()
        except Exception as exc:
            print(f"[meeting-agent] action item insert failed: {exc}")


def _create_meeting_note(user_id: str, meeting: dict, extracted: dict, db) -> None:
    if not meeting.get("client_id") or not extracted.get("summary"):
        return
    parts = [f"**Meeting:** {meeting.get('title', 'Call')}\n", f"**Summary:** {extracted['summary']}\n"]
    if extracted.get("decisions"):
        parts.append("\n**Decisions:**")
        for d in extracted["decisions"]:
            parts.append(f"- {d['decision']}")
    if extracted.get("commitments"):
        parts.append("\n**Commitments:**")
        for c in extracted["commitments"]:
            by_when = f" (by {c['by_when']})" if c.get("by_when") else ""
            parts.append(f"- {c['who'].title()}: {c['what']}{by_when}")
    if extracted.get("next_steps"):
        parts.append("\n**Next steps:**")
        for n in extracted["next_steps"]:
            lbl = {"me": "Me", "client": "Client", "both": "Both"}.get(n["owner"], n["owner"])
            by_when = f" → {n['by_when']}" if n.get("by_when") else ""
            parts.append(f"- [{lbl}] {n['action']}{by_when}")
    try:
        db.table("client_notes").insert(
            {
                "user_id": user_id,
                "client_id": meeting["client_id"],
                "engagement_id": meeting.get("engagement_id"),
                "meeting_id": meeting["id"],
                "note_type": "meeting",
                "content_md": "\n".join(parts),
                "is_ai_generated": True,
            }
        ).execute()
    except Exception as exc:
        print(f"[meeting-agent] note insert failed: {exc}")


def queue_followup_for_meeting(user_id: str, meeting_id: str) -> dict:
    """On-demand: draft + queue a post-meeting follow-up email for an already
    processed meeting, rebuilding the content from its stored action items.
    Queues a send_email_gmail task for the owner's approval (never sends directly)."""
    if not settings.SUPABASE_URL:
        return {"queued": False, "reason": "storage unavailable"}
    db = _db()
    meeting = db.table("meetings").select("*").eq("id", meeting_id).eq("user_id", user_id).single().execute().data
    if not meeting:
        return {"queued": False, "reason": "meeting not found"}
    if not meeting.get("client_id"):
        return {"queued": False, "reason": "Link this meeting to a client first."}

    client = db.table("clients").select("name, email").eq("id", meeting["client_id"]).single().execute().data
    if not client or not client.get("email"):
        return {"queued": False, "reason": "This client has no email on file."}

    items = db.table("meeting_action_items").select("description, owner, due_date").eq("meeting_id", meeting_id).execute().data or []
    extracted = {
        "decisions": [],
        "commitments": [{"who": it.get("owner", "me"), "what": it.get("description", ""), "by_when": it.get("due_date")} for it in items],
        "next_steps": items,
    }
    _queue_meeting_followup(user_id, meeting, extracted, db)
    return {"queued": True, "client": client["name"], "actionItems": len(items)}


def _queue_meeting_followup(user_id: str, meeting: dict, extracted: dict, db) -> None:
    if not meeting.get("client_id"):
        return
    client_rows = db.table("clients").select("name, email").eq("id", meeting["client_id"]).single().execute().data
    if not client_rows or not client_rows.get("email"):
        return
    client = client_rows

    email = _build_followup_email(
        client_name=client["name"],
        meeting_title=meeting.get("title", "our call"),
        extracted=extracted,
    )
    _queue_gmail_send_sync(
        user_id=user_id,
        to_email=client["email"],
        to_name=client["name"],
        subject=f"Follow-up: {meeting.get('title', 'Our call')}",
        body_html=email["html"],
        body_text=email["text"],
        context=(
            f"Post-meeting follow-up for {client['name']} after: {meeting.get('title')}. "
            f"Includes {len(extracted.get('commitments', []))} commitments and "
            f"{len(extracted.get('next_steps', []))} next steps."
        ),
        related_client_id=meeting.get("client_id"),
        related_meeting_id=meeting["id"],
        db=db,
    )
    db.table("meetings").update(
        {
            "followup_queued_at": _now(),
        }
    ).eq(
        "id", meeting["id"]
    ).eq("user_id", user_id).execute()


def _build_followup_email(client_name: str, meeting_title: str, extracted: dict) -> dict:
    text_lines = [f"Hi {client_name},\n", "Thanks for the time today. Here's a quick summary of what we covered:\n"]
    html_lines = [f"<p>Hi {client_name},</p>", "<p>Thanks for the time today. Here's a quick summary of what we covered:</p>"]

    if extracted.get("decisions"):
        text_lines.append("What we decided:")
        html_lines.append("<p><strong>What we decided:</strong></p><ul>")
        for d in extracted["decisions"]:
            text_lines.append(f"  • {d['decision']}")
            html_lines.append(f"<li>{d['decision']}</li>")
        html_lines.append("</ul>")

    my_commits = [c for c in extracted.get("commitments", []) if c.get("who") == "me"]
    their_commits = [c for c in extracted.get("commitments", []) if c.get("who") == "client"]

    if my_commits:
        text_lines.append("\nOn my end:")
        html_lines.append("<p><strong>On my end:</strong></p><ul>")
        for c in my_commits:
            bw = f" by {c['by_when']}" if c.get("by_when") else ""
            text_lines.append(f"  • {c['what']}{bw}")
            html_lines.append(f"<li>{c['what']}{bw}</li>")
        html_lines.append("</ul>")

    if their_commits:
        text_lines.append("\nOn your end:")
        html_lines.append("<p><strong>On your end:</strong></p><ul>")
        for c in their_commits:
            bw = f" by {c['by_when']}" if c.get("by_when") else ""
            text_lines.append(f"  • {c['what']}{bw}")
            html_lines.append(f"<li>{c['what']}{bw}</li>")
        html_lines.append("</ul>")

    text_lines.extend(["\nLet me know if I've missed anything.", "Talk soon."])
    html_lines.extend(["<p>Let me know if I've missed anything.</p>", "<p>Talk soon.</p>"])
    return {"text": "\n".join(text_lines), "html": "\n".join(html_lines)}


def _queue_gmail_send_sync(
    user_id: str,
    to_email: str,
    to_name: str,
    subject: str,
    body_html: str,
    body_text: str,
    context: str,
    related_client_id: str | None,
    related_meeting_id: str | None,
    db,
) -> None:
    """Insert a send_email_gmail manager_task (sync, no await needed)."""
    if not settings.SUPABASE_URL:
        return
    conn_rows = db.table("google_connections").select("google_email").eq("user_id", user_id).execute().data
    from_email = conn_rows[0]["google_email"] if conn_rows else "your Gmail"
    try:
        db.table("manager_tasks").insert(
            {
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
            }
        ).execute()
    except Exception as exc:
        print(f"[meeting-agent] queue gmail send failed: {exc}")


# ─── Transcript text extraction (multi-format) ───────────────────────────────


def extract_transcript_text(content: bytes, filename: str) -> str:
    """Extract plain text from .txt/.vtt/.srt/.pdf/.docx transcript files."""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else "txt"

    if ext in ("txt", "vtt", "srt"):
        text = content.decode("utf-8", errors="ignore")
        lines = []
        for line in text.splitlines():
            line = line.strip()
            if "-->" in line:
                continue
            if re.match(r"^\d{2}:\d{2}|^\d+$|^WEBVTT", line):
                continue
            if line:
                lines.append(line)
        return "\n".join(lines)

    if ext == "pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(content))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception:
            return content.decode("utf-8", errors="ignore")

    if ext == "docx":
        try:
            import docx as _docx

            doc = _docx.Document(io.BytesIO(content))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception:
            return content.decode("utf-8", errors="ignore")

    return content.decode("utf-8", errors="ignore")
