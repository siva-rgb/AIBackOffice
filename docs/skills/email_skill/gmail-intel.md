# Butler Google — Gmail Intelligence Reference

## What Gmail gives the Butler

For each known client, the Butler reads their email thread history and extracts:
- Last contact date and who contacted whom
- Tone and sentiment of the conversation
- Commitments made in writing by either party
- Financial mentions (amounts, invoices, payments referenced)
- Unanswered questions or unresolved items
- Whether the relationship feels healthy or strained

This is the difference between "Harbor Design has an overdue invoice"
and "Harbor Design has been unresponsive for 12 days — their last email
asked about the revision timeline and you haven't replied."

---

## Gmail service

```python
# app/services/gmail_intel.py
"""
Reads Gmail threads with known clients, extracts business intelligence,
caches results. Called by the daily Butler worker and on-demand.
"""
import json
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from app.services.google_auth import get_user_credentials
from app.services.vertex_ai import generate_with_retry, getGeminiForAgent
from app.services.agent_logger import log_action
from app.utils.security import sanitize_prompt_input
from supabase import create_client
from app.config import settings


# ── Fetch and process threads ─────────────────────────────────────────────────

async def sync_client_email_intel(user_id: str, force_refresh: bool = False):
    """
    Main entry point. For each connected client with an email address,
    fetch their Gmail threads and extract intelligence.
    Called daily by the morning briefing worker.
    """
    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    creds = await get_user_credentials(user_id)
    if not creds:
        return  # not connected — skip silently

    # Get all clients with email addresses
    clients = db.table("clients").select(
        "id, name, email, status"
    ).eq("user_id", user_id).eq("status", "active").not_.is_("email", "null").execute().data

    service = build("gmail", "v1", credentials=creds)

    for client in clients:
        try:
            await _process_client_threads(user_id, client, service, db, force_refresh)
        except Exception as e:
            print(f"Gmail intel failed for client {client['name']}: {e}")
            continue


async def _process_client_threads(
    user_id: str, client: dict, service, db, force_refresh: bool
):
    """Fetch and process Gmail threads for one client."""
    client_email = client["email"]
    client_id = client["id"]
    client_name = client["name"]

    # Check cache — skip if already processed today and not forced
    if not force_refresh:
        cache = db.table("email_intel_cache").select(
            "id, processed_at, last_message_id"
        ).eq("user_id", user_id).eq("client_id", client_id).execute().data

        if cache:
            cached = cache[0]
            if cached.get("processed_at"):
                processed = datetime.fromisoformat(
                    cached["processed_at"].replace("Z", "+00:00")
                )
                if (datetime.utcnow().replace(tzinfo=processed.tzinfo) - processed
                        ).total_seconds() < 86400:  # less than 24h ago
                    # Check if there are newer messages
                    if not await _has_new_messages(service, client_email,
                                                    cached.get("last_message_id")):
                        return  # cache is current — skip

    # Fetch threads involving this client's email
    threads = await _fetch_client_threads(service, client_email)
    if not threads:
        return

    # Process threads → extract intelligence
    intel = await _analyze_threads(user_id, client_name, client_email, threads, service)

    # Cache the result
    last_msg_id = threads[0].get("messages", [{}])[-1].get("id") if threads else None
    db.table("email_intel_cache").upsert({
        "user_id": user_id,
        "client_id": client_id,
        "client_name": client_name,
        "thread_count": len(threads),
        "last_message_id": last_msg_id,
        "last_contact_days": intel.get("last_contact_days"),
        "last_contact_direction": intel.get("last_contact_direction"),
        "sentiment": intel.get("sentiment"),
        "relationship_health": intel.get("relationship_health"),
        "summary": intel.get("summary"),
        "action_needed": intel.get("action_needed"),
        "action_description": intel.get("action_description"),
        "commitments_pending": intel.get("commitments_pending", []),
        "financial_mentions": intel.get("financial_mentions", []),
        "open_questions": intel.get("open_questions", []),
        "processed_at": datetime.utcnow().isoformat(),
        "expires_at": (datetime.utcnow() + timedelta(hours=24)).isoformat(),
    }, on_conflict="user_id,client_id").execute()

    # Update client last_activity_at if we found recent contact
    if intel.get("last_contact_days", 999) < 7:
        db.table("clients").update({
            "last_activity_at": "now()"
        }).eq("id", client_id).execute()


async def _fetch_client_threads(service, client_email: str) -> list:
    """
    Fetch the most recent Gmail threads involving client_email.
    Returns up to 10 threads, most recent first.
    Only reads threads — does not read full message bodies unnecessarily.
    """
    query = f"from:{client_email} OR to:{client_email}"
    result = service.users().threads().list(
        userId="me",
        q=query,
        maxResults=10,
    ).execute()

    threads = result.get("threads", [])
    if not threads:
        return []

    # Fetch thread details (metadata only for efficiency)
    full_threads = []
    for thread_ref in threads[:10]:
        thread = service.users().threads().get(
            userId="me",
            id=thread_ref["id"],
            format="metadata",
            metadataHeaders=["From", "To", "Subject", "Date"]
        ).execute()
        full_threads.append(thread)

    return full_threads


async def _has_new_messages(service, client_email: str, last_known_id: str) -> bool:
    """Quick check: any messages newer than last_known_id?"""
    if not last_known_id:
        return True
    result = service.users().messages().list(
        userId="me",
        q=f"from:{client_email} OR to:{client_email}",
        maxResults=1,
    ).execute()
    messages = result.get("messages", [])
    if not messages:
        return False
    return messages[0]["id"] != last_known_id


async def _analyze_threads(
    user_id: str,
    client_name: str,
    client_email: str,
    threads: list,
    service
) -> dict:
    """
    For the most recent 3 threads, fetch snippet text and analyze with Gemini.
    Uses snippets (200 char previews), not full bodies — balances insight vs cost.
    """
    start = datetime.utcnow()

    # Build a thread summary from metadata + snippets
    thread_summaries = []
    for thread in threads[:3]:
        messages = thread.get("messages", [])
        thread_text_parts = []
        for msg in messages[-5:]:  # last 5 messages per thread
            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            snippet = msg.get("snippet", "")
            sender = headers.get("From", "Unknown")
            date = headers.get("Date", "")
            thread_text_parts.append(
                f"[{date}] From: {sender}\n{snippet}"
            )
        if thread_text_parts:
            thread_summaries.append("\n---\n".join(thread_text_parts))

    if not thread_summaries:
        return {"sentiment": "neutral", "relationship_health": "unknown"}

    # Calculate days since last message
    last_thread = threads[0]
    last_msg = last_thread.get("messages", [{}])[-1]
    last_headers = {
        h["name"]: h["value"]
        for h in last_msg.get("payload", {}).get("headers", [])
    }
    last_date_str = last_headers.get("Date", "")
    last_contact_days = 999
    last_contact_direction = "unknown"
    try:
        from email.utils import parsedate_to_datetime
        last_dt = parsedate_to_datetime(last_date_str)
        last_contact_days = (datetime.now(last_dt.tzinfo) - last_dt).days
        from_email = last_headers.get("From", "")
        last_contact_direction = "from_client" if client_email in from_email else "from_me"
    except Exception:
        pass

    combined_text = sanitize_prompt_input("\n\n===\n\n".join(thread_summaries)[:3000])

    model = getGeminiForAgent("butler")
    prompt = f"""
Analyze these email thread snippets between a business owner and their client.
Extract structured business intelligence.

CLIENT: {client_name} ({client_email})
DAYS SINCE LAST MESSAGE: {last_contact_days}
LAST MESSAGE DIRECTION: {last_contact_direction} (from_client = client emailed last, from_me = I emailed last)

EMAIL SNIPPETS (most recent threads, newest messages first):
<emails>
{combined_text}
</emails>

Return ONLY valid JSON:
{{
  "sentiment": "positive|neutral|cautious|strained",
  "relationship_health": "strong|healthy|needs_attention|at_risk",
  "summary": "2 sentences: current state of this client relationship based on emails",
  "action_needed": true or false,
  "action_description": "specific action if needed, null if not",
  "commitments_pending": [
    {{"who": "me|client", "what": "specific commitment", "mentioned_date": "date or null"}}
  ],
  "open_questions": ["specific unanswered question or unresolved item"],
  "financial_mentions": [
    {{"type": "invoice|payment|quote|refund", "amount": number or null, "context": "brief"}}
  ],
  "suggested_reply": "one sentence draft reply if action_needed is true, null otherwise"
}}

Be conservative — only extract what is clearly present in the snippets.
If snippets are too brief to draw conclusions, return neutral sentiment and no action.
"""

    result = await generate_with_retry(lambda: model.generate_content(prompt))
    raw = result.response.candidates[0].content.parts[0].text
    latency_ms = int((datetime.utcnow() - start).total_seconds() * 1000)

    try:
        intel = json.loads(raw.replace("```json", "").replace("```", "").strip())
    except Exception:
        intel = {"sentiment": "neutral", "relationship_health": "unknown"}

    intel["last_contact_days"] = last_contact_days
    intel["last_contact_direction"] = last_contact_direction

    await log_action(
        user_id=user_id,
        agent_type="butler_gmail",
        action=f"Analyzed email threads for client: {client_name}",
        input_data={"client_email": client_email, "threads_processed": len(thread_summaries)},
        output_data={"sentiment": intel.get("sentiment"), "action_needed": intel.get("action_needed")},
        latency_ms=latency_ms,
        triggered_by="scheduler"
    )

    return intel
```

---

## Email draft generation

```python
# app/services/gmail_draft.py
"""
Generates email drafts based on context and queues for HITL approval.
Never sends directly.
"""
import json
from app.services.vertex_ai import generate_with_retry, getGeminiForAgent
from app.services.gmail_agent import queue_gmail_send
from supabase import create_client
from app.config import settings


async def draft_client_reply(
    user_id: str,
    client_id: str,
    context: str,           # "follow up on invoice", "reply to scope question", etc.
    tone: str = "professional",  # professional | friendly | firm
    reference_thread: dict = None,
) -> dict:
    """
    Draft a client email and queue for approval.
    Returns the draft text for the approval card.
    """
    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

    client = db.table("clients").select(
        "name, email, what_we_do"
    ).eq("id", client_id).eq("user_id", user_id).single().execute().data
    if not client:
        raise ValueError("Client not found")

    user = db.table("users").select(
        "full_name, business_name, email"
    ).eq("id", user_id).single().execute().data

    # Get email intel cache for context
    cache = db.table("email_intel_cache").select(
        "summary, commitments_pending, open_questions"
    ).eq("user_id", user_id).eq("client_id", client_id).execute().data
    email_context = cache[0] if cache else {}

    model = getGeminiForAgent("butler")
    prompt = f"""
You are drafting a professional email on behalf of a business owner.
Write in their voice: clear, professional, and natural.

SENDER: {user.get('full_name', 'Business owner')} ({user.get('business_name', '')})
RECIPIENT: {client['name']} ({client.get('email', '')})
RELATIONSHIP CONTEXT: {client.get('what_we_do', '')}
EMAIL HISTORY SUMMARY: {email_context.get('summary', 'No email history available')}
PENDING COMMITMENTS: {json.dumps(email_context.get('commitments_pending', []))}
OPEN QUESTIONS: {json.dumps(email_context.get('open_questions', []))}

PURPOSE OF THIS EMAIL: {context}
TONE: {tone}

Write a complete email. Return JSON:
{{
  "subject": "clear, specific subject line",
  "body_text": "plain text email body (no HTML)",
  "body_html": "HTML version with basic formatting (p tags, ul/li for lists)",
  "reasoning": "one sentence: why this approach was chosen"
}}

Rules:
- Address client by first name only
- End with a clear, single call to action
- No fluff or filler phrases ("I hope this email finds you well")
- Match the {tone} tone
- Under 150 words unless the context requires more
"""

    result = await generate_with_retry(lambda: model.generate_content(prompt))
    raw = result.response.candidates[0].content.parts[0].text
    draft = json.loads(raw.replace("```json", "").replace("```", "").strip())

    # Queue for approval
    await queue_gmail_send(
        user_id=user_id,
        to_email=client["email"],
        to_name=client["name"],
        subject=draft["subject"],
        body_html=draft["body_html"],
        body_text=draft["body_text"],
        context=f"Email to {client['name']}: {context}. Reasoning: {draft.get('reasoning')}",
        related_client_id=client_id,
    )

    return draft


async def draft_invoice_email(
    user_id: str,
    invoice_id: str,
) -> dict:
    """Draft a professional invoice cover email. Queues for approval."""
    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

    invoice = db.table("invoices").select(
        "*, clients(name, email, what_we_do)"
    ).eq("id", invoice_id).eq("user_id", user_id).single().execute().data
    if not invoice:
        raise ValueError("Invoice not found")

    return await draft_client_reply(
        user_id=user_id,
        client_id=invoice.get("client_id"),
        context=f"Sending Invoice #{invoice.get('id', '')[:8]} for "
                f"{invoice.get('currency', 'USD')} {invoice.get('total', 0):,.2f}. "
                f"Work: {invoice['clients'].get('what_we_do', '')}",
        tone="professional"
    )
```

---

## Gmail intel router

```python
# app/routers/gmail_intel.py
from fastapi import APIRouter, Depends, BackgroundTasks
from app.dependencies import get_current_user
from app.services.gmail_intel import sync_client_email_intel
from app.services.gmail_draft import draft_client_reply, draft_invoice_email

router = APIRouter(prefix="/gmail", tags=["gmail"])

@router.post("/sync")
async def sync_email_intel(
    background_tasks: BackgroundTasks,
    force: bool = False,
    user=Depends(get_current_user)
):
    """Manually trigger Gmail intelligence sync for all clients."""
    background_tasks.add_task(sync_client_email_intel, user["id"], force)
    return {"status": "syncing"}

@router.get("/intel")
async def get_email_intel(user=Depends(get_current_user)):
    """Get cached email intelligence for all clients."""
    from supabase import create_client
    from app.config import settings
    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    return db.table("email_intel_cache").select(
        "client_name, client_id, sentiment, relationship_health, "
        "summary, action_needed, action_description, last_contact_days, "
        "last_contact_direction, commitments_pending, open_questions, processed_at"
    ).eq("user_id", user["id"]).order("last_contact_days").execute().data

@router.post("/draft/{client_id}")
async def draft_email(
    client_id: str,
    body: dict,
    user=Depends(get_current_user)
):
    """Draft an email to a client based on context."""
    context = body.get("context", "follow up")
    tone = body.get("tone", "professional")
    return await draft_client_reply(user["id"], client_id, context, tone)

@router.post("/draft-invoice/{invoice_id}")
async def draft_invoice_cover_email(
    invoice_id: str,
    user=Depends(get_current_user)
):
    """Draft an invoice cover email."""
    return await draft_invoice_email(user["id"], invoice_id)
```
