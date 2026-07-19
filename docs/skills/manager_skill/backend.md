# Butler — Backend Implementation Reference

Tech stack: FastAPI (Python 3.11), Supabase (supabase-py), Vertex AI (Gemini 1.5 Pro).
All patterns follow the existing Kora backend conventions in `app/`.

---

## File layout (new files only)

```
backend/app/
  routers/
    clients.py          — CRUD for clients, engagements, notes
    captures.py         — quick_capture submit + review queue
    proposals.py        — proposal CRUD + generation
    retainers.py        — retainer CRUD + scheduling
    butler.py           — butler briefing endpoint + health score
  services/
    client_store.py     — DB helpers for all butler tables (mirrors store.py pattern)
    butler_agent.py     — orchestrating butler agent
    capture_agent.py    — quick_capture AI parsing
    proposal_agent.py   — proposal generation (extends contract_agent.py)
    retainer_agent.py   — retainer invoice scheduling
    health_agent.py     — per-client health score computation
  models/
    client.py           — Pydantic models for clients, engagements
    capture.py          — Pydantic models for quick_captures
    proposal.py         — Pydantic models for proposals
    retainer.py         — Pydantic models for retainers

workers/
  morning_briefing.py   — Cloud Scheduler 07:00 UTC daily
  retainer_invoicer.py  — Cloud Scheduler 06:30 UTC daily (creates retainer invoices)
  client_health.py      — Cloud Scheduler 06:00 UTC daily (updates health scores)
```

---

## Phase 1 — Client entity

### Pydantic models (`app/models/client.py`)

```python
from pydantic import BaseModel, Field, EmailStr
from typing import Optional
from datetime import datetime
from uuid import UUID

class ClientCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=50)
    company: Optional[str] = Field(None, max_length=200)
    industry: Optional[str] = Field(None, max_length=100)
    client_type: str = Field('individual', pattern='^(individual|company|agency|marketplace)$')
    status: str = Field('active', pattern='^(active|inactive|prospect|churned)$')
    what_we_do: Optional[str] = Field(None, max_length=500)
    notes_md: Optional[str] = Field(None, max_length=5000)
    timezone: Optional[str] = None
    currency: str = Field('USD', max_length=3)

class ClientUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    industry: Optional[str] = None
    client_type: Optional[str] = None
    status: Optional[str] = None
    what_we_do: Optional[str] = None
    notes_md: Optional[str] = None
    timezone: Optional[str] = None
    currency: Optional[str] = None

class EngagementCreate(BaseModel):
    client_id: UUID
    title: str = Field(..., min_length=1, max_length=200)
    description_md: Optional[str] = Field(None, max_length=2000)
    engagement_type: str = Field('project',
        pattern='^(project|retainer|one_off|ongoing)$')
    status: str = Field('active',
        pattern='^(planning|active|on_track|at_risk|paused|done|cancelled)$')
    start_date: Optional[str] = None   # ISO date string
    target_end_date: Optional[str] = None
    budget: Optional[float] = Field(None, ge=0)
    budget_currency: str = 'USD'
    contract_id: Optional[UUID] = None
```

### Router (`app/routers/clients.py`)

```python
from fastapi import APIRouter, Depends, HTTPException
from app.dependencies import get_current_user
from app.services.client_store import ClientStore
from app.models.client import ClientCreate, ClientUpdate, EngagementCreate
from app.utils.security import sanitize_prompt_input
from uuid import UUID

router = APIRouter(prefix="/clients", tags=["clients"])

@router.get("")
async def list_clients(
    status: str = None,
    user=Depends(get_current_user)
):
    store = ClientStore(user["id"])
    return await store.list_clients(status=status)

@router.post("")
async def create_client(
    body: ClientCreate,
    user=Depends(get_current_user)
):
    # Sanitize freeform text before storing
    if body.what_we_do:
        body.what_we_do = sanitize_prompt_input(body.what_we_do)
    if body.notes_md:
        body.notes_md = sanitize_prompt_input(body.notes_md)
    store = ClientStore(user["id"])
    return await store.create_client(body)

@router.get("/{client_id}")
async def get_client(client_id: UUID, user=Depends(get_current_user)):
    store = ClientStore(user["id"])
    client = await store.get_client(str(client_id))
    if not client:
        raise HTTPException(404, "Client not found")
    return client

@router.patch("/{client_id}")
async def update_client(
    client_id: UUID,
    body: ClientUpdate,
    user=Depends(get_current_user)
):
    store = ClientStore(user["id"])
    return await store.update_client(str(client_id), body)

@router.delete("/{client_id}")
async def delete_client(client_id: UUID, user=Depends(get_current_user)):
    store = ClientStore(user["id"])
    await store.delete_client(str(client_id))
    return {"deleted": True}

# Engagement sub-routes
@router.get("/{client_id}/engagements")
async def list_engagements(client_id: UUID, user=Depends(get_current_user)):
    store = ClientStore(user["id"])
    return await store.list_engagements(str(client_id))

@router.post("/{client_id}/engagements")
async def create_engagement(
    client_id: UUID,
    body: EngagementCreate,
    user=Depends(get_current_user)
):
    if body.description_md:
        body.description_md = sanitize_prompt_input(body.description_md)
    store = ClientStore(user["id"])
    return await store.create_engagement(str(client_id), body)

# Client notes
@router.get("/{client_id}/notes")
async def list_notes(client_id: UUID, user=Depends(get_current_user)):
    store = ClientStore(user["id"])
    return await store.list_notes(str(client_id))
```

### DB store (`app/services/client_store.py`)

```python
from supabase import create_client
from app.config import settings

class ClientStore:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

    async def list_clients(self, status: str = None):
        q = self.db.table("clients").select(
            "*, engagements(id, title, status), "
            "invoices(id, total, status, due_date)"
        ).eq("user_id", self.user_id).order("last_activity_at", desc=True)
        if status:
            q = q.eq("status", status)
        res = q.execute()
        return res.data

    async def create_client(self, body) -> dict:
        res = self.db.table("clients").insert({
            "user_id": self.user_id,
            **body.model_dump(exclude_none=True),
            "last_activity_at": "now()"
        }).execute()
        return res.data[0]

    async def get_client(self, client_id: str) -> dict | None:
        res = self.db.table("clients").select(
            "*, engagements(*), client_notes(*), "
            "invoices(id, total, status, due_date, sent_at), "
            "contracts(id, type, status, signed_at), "
            "proposals(id, title, total_amount, status), "
            "retainers(id, title, amount, billing_cycle, status)"
        ).eq("id", client_id).eq("user_id", self.user_id).single().execute()
        return res.data

    async def update_client(self, client_id: str, body) -> dict:
        update_data = {k: v for k, v in body.model_dump().items() if v is not None}
        update_data["last_activity_at"] = "now()"
        res = self.db.table("clients").update(update_data).eq(
            "id", client_id).eq("user_id", self.user_id).execute()
        return res.data[0]

    async def delete_client(self, client_id: str):
        self.db.table("clients").delete().eq(
            "id", client_id).eq("user_id", self.user_id).execute()

    async def list_engagements(self, client_id: str) -> list:
        res = self.db.table("engagements").select("*").eq(
            "client_id", client_id).eq("user_id", self.user_id).order(
            "created_at", desc=True).execute()
        return res.data

    async def create_engagement(self, client_id: str, body) -> dict:
        res = self.db.table("engagements").insert({
            "user_id": self.user_id,
            "client_id": client_id,
            **body.model_dump(exclude_none=True)
        }).execute()
        # Update client last_activity_at
        self.db.table("clients").update({"last_activity_at": "now()"}).eq(
            "id", client_id).execute()
        return res.data[0]

    async def list_notes(self, client_id: str) -> list:
        res = self.db.table("client_notes").select("*").eq(
            "client_id", client_id).eq("user_id", self.user_id).order(
            "created_at", desc=True).limit(50).execute()
        return res.data
```

---

## Phase 2 — Quick capture

### Router (`app/routers/captures.py`)

```python
from fastapi import APIRouter, Depends, BackgroundTasks
from app.dependencies import get_current_user
from app.services.capture_agent import parse_capture
from app.utils.security import sanitize_prompt_input
from pydantic import BaseModel, Field

router = APIRouter(prefix="/captures", tags=["captures"])

class CaptureCreate(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    source: str = Field('web', pattern='^(web|mobile|email|sms)$')

@router.post("")
async def submit_capture(
    body: CaptureCreate,
    background_tasks: BackgroundTasks,
    user=Depends(get_current_user)
):
    # Sanitize immediately — before any storage
    safe_text = sanitize_prompt_input(body.text)

    # Store raw note first — never lose user input
    from app.services.client_store import ClientStore
    from supabase import create_client
    from app.config import settings
    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    res = db.table("quick_captures").insert({
        "user_id": user["id"],
        "raw_text": safe_text,
        "source": body.source,
        "parse_status": "pending"
    }).execute()
    capture_id = res.data[0]["id"]

    # Parse in background — don't block the response
    background_tasks.add_task(parse_capture, user["id"], capture_id, safe_text)

    return {"id": capture_id, "status": "pending"}

@router.get("/review")
async def list_review_queue(user=Depends(get_current_user)):
    """Items that need human review (low AI confidence or failed parse)."""
    from supabase import create_client
    from app.config import settings
    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    res = db.table("quick_captures").select("*").eq(
        "user_id", user["id"]).eq("requires_review", True).order(
        "created_at", desc=True).execute()
    return res.data
```

### Capture agent (`app/services/capture_agent.py`)

```python
import json
from datetime import datetime
from app.services.vertex_ai import generate_with_retry, getGeminiForAgent
from app.services.agent_logger import log_action
from app.services.client_store import ClientStore

async def parse_capture(user_id: str, capture_id: str, raw_text: str):
    """
    Parse a quick_capture note into structured business state updates.
    Called as a background task — never raises, always updates DB.
    """
    from supabase import create_client
    from app.config import settings
    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

    start = datetime.utcnow()
    try:
        # Get existing clients for entity matching context
        store = ClientStore(user_id)
        clients = await store.list_clients()
        client_names = [c["name"] for c in clients] if clients else []

        model = getGeminiForAgent("butler")
        prompt = _build_capture_prompt(raw_text, client_names)

        result = await generate_with_retry(lambda: model.generate_content(prompt))
        raw_response = result.response.candidates[0].content.parts[0].text
        parsed = _parse_capture_response(raw_response)

        latency_ms = int((datetime.utcnow() - start).total_seconds() * 1000)

        # Apply actions to DB
        actions_taken = await _apply_capture_actions(user_id, parsed, capture_id, db)

        # Update capture record
        confidence = parsed.get("confidence", 0.5)
        db.table("quick_captures").update({
            "parse_status": "parsed",
            "parsed_intent": parsed.get("intent"),
            "parsed_entities": parsed.get("entities", {}),
            "ai_confidence": confidence,
            "actions_taken": actions_taken,
            "requires_review": confidence < 0.7,
            "parsed_at": datetime.utcnow().isoformat()
        }).eq("id", capture_id).execute()

        await log_action(
            user_id=user_id,
            agent_type="butler",
            action=f"Parsed quick capture: {parsed.get('intent', 'unknown')}",
            input_data={"capture_id": capture_id, "text_length": len(raw_text)},
            output_data={"intent": parsed.get("intent"), "actions": len(actions_taken)},
            latency_ms=latency_ms,
            triggered_by="user"
        )

    except Exception as e:
        db.table("quick_captures").update({
            "parse_status": "failed",
            "requires_review": True,
            "parsed_entities": {"error": str(e)}
        }).eq("id", capture_id).execute()


def _build_capture_prompt(text: str, known_clients: list[str]) -> str:
    clients_context = ", ".join(known_clients[:20]) if known_clients else "none yet"
    return f"""
You are parsing a quick business note from a freelancer or small business owner.
Extract structured information and determine what business state to update.

Known clients: {clients_context}

Note to parse:
<note>
{text}
</note>

Return ONLY valid JSON, no markdown, no explanation:
{{
  "intent": "client_update|new_client|engagement_update|financial|note|proposal|unknown",
  "confidence": 0.0-1.0,
  "entities": {{
    "client_name": "string or null — match to known clients if possible",
    "amount": "number or null",
    "currency": "string or null",
    "date": "ISO date string or null",
    "action": "what happened in one word: finished|started|delayed|signed|paid|blocked|meeting",
    "engagement_title": "string or null — what project/work this is about",
    "status_update": "on_track|at_risk|done|paused or null",
    "note_content": "cleaned version of the note for saving as client_note"
  }},
  "suggested_actions": [
    {{
      "type": "update_engagement_status|create_client|create_note|update_client|flag_for_review",
      "target": "what record to update (client name, engagement title)",
      "value": "new value"
    }}
  ]
}}
"""


def _parse_capture_response(raw: str) -> dict:
    clean = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(clean)


async def _apply_capture_actions(
    user_id: str, parsed: dict, capture_id: str, db
) -> list:
    """Apply AI-suggested actions to the database. Returns list of actions taken."""
    actions_taken = []
    store = ClientStore(user_id)
    entities = parsed.get("entities", {})
    client_name = entities.get("client_name")

    # Find matching client
    client = None
    if client_name:
        clients = await store.list_clients()
        for c in clients:
            if c["name"].lower() == client_name.lower():
                client = c
                break

    # Always save a client_note
    if client and entities.get("note_content"):
        db.table("client_notes").insert({
            "user_id": user_id,
            "client_id": client["id"],
            "quick_capture_id": capture_id,
            "note_type": "update",
            "content_md": entities["note_content"],
            "is_ai_generated": True
        }).execute()
        db.table("clients").update({"last_activity_at": "now()"}).eq(
            "id", client["id"]).execute()
        actions_taken.append({"type": "created_note", "client_id": client["id"]})

    # Update engagement status if confidence is high enough
    if parsed.get("confidence", 0) >= 0.7 and client and entities.get("status_update"):
        engagements = await store.list_engagements(client["id"])
        if engagements:
            # Update most recent active engagement
            active = [e for e in engagements if e["status"] in ("active", "on_track", "at_risk")]
            if active:
                target = active[0]
                db.table("engagements").update({
                    "status": entities["status_update"],
                    "updated_at": "now()"
                }).eq("id", target["id"]).execute()
                actions_taken.append({
                    "type": "updated_engagement",
                    "id": target["id"],
                    "new_status": entities["status_update"]
                })

    return actions_taken
```

---

## Phase 3 — Morning briefing

### Worker (`workers/morning_briefing.py`)

```python
"""
Cloud Scheduler: 0 7 * * * (07:00 UTC daily)
Generates the morning butler briefing for every active user.
Extends the existing daily_digest by adding client + work context.
"""
import asyncio
from datetime import datetime, timedelta
from app.services.butler_agent import generate_morning_briefing
from app.services.client_store import ClientStore
from supabase import create_client
from app.config import settings

async def run():
    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    users = db.table("users").select("id, plan, butler_memory").execute().data

    for user in users:
        if user["plan"] == "free":
            continue  # briefing is starter+ feature
        try:
            await generate_morning_briefing(user["id"])
            await asyncio.sleep(1)  # pace between users
        except Exception as e:
            print(f"Briefing failed for {user['id']}: {e}")

if __name__ == "__main__":
    asyncio.run(run())
```

### Butler agent (`app/services/butler_agent.py`)

```python
"""
The core orchestrating agent. Runs gather → assess → brief.
ONE Gemini call per run. All data gathering is deterministic.
"""
import json
from datetime import datetime, timedelta
from app.services.vertex_ai import generate_with_retry, getGeminiForAgent
from app.services.agent_logger import log_action
from app.services.client_store import ClientStore
from supabase import create_client
from app.config import settings

async def generate_morning_briefing(user_id: str) -> dict:
    start = datetime.utcnow()
    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

    # Step 1: Gather state (deterministic, no AI)
    state = await _gather_state(user_id, db)

    # Step 2: Assess (rule-based findings)
    findings = _assess(state)

    # Step 3: ONE Gemini call to compose briefing
    model = getGeminiForAgent("butler")
    prompt = _build_briefing_prompt(state, findings)
    result = await generate_with_retry(lambda: model.generate_content(prompt))
    raw = result.response.candidates[0].content.parts[0].text
    briefing = _parse_briefing(raw)

    latency_ms = int((datetime.utcnow() - start).total_seconds() * 1000)

    # Step 4: Persist briefing and update butler_memory
    butler_memory = {
        "last_briefing_at": datetime.utcnow().isoformat(),
        "last_briefing_summary": briefing.get("two_sentence_summary", ""),
        "client_count": state["client_count"],
        "active_engagement_count": state["active_engagement_count"],
        "rolling_insights": _update_rolling_insights(
            state.get("existing_memory", {}).get("rolling_insights", []),
            briefing.get("key_insight", "")
        )
    }
    db.table("users").update({"butler_memory": butler_memory}).eq("id", user_id).execute()

    # Store as alert for the dashboard
    db.table("alerts").insert({
        "user_id": user_id,
        "type": "morning_briefing",
        "severity": "info",
        "title": "Morning briefing",
        "body": briefing.get("headline", "Your business summary is ready."),
        "read": False,
        "action_url": "/butler"
    }).execute()

    await log_action(
        user_id=user_id,
        agent_type="butler",
        action="Generated morning briefing",
        input_data={"clients": state["client_count"], "findings": len(findings)},
        output_data=briefing,
        latency_ms=latency_ms,
        triggered_by="scheduler"
    )

    return briefing


async def _gather_state(user_id: str, db) -> dict:
    """All data gathering. No AI calls. Returns a flat snapshot dict."""
    store = ClientStore(user_id)
    now = datetime.utcnow()
    thirty_days_ago = (now - timedelta(days=30)).isoformat()
    seven_days = (now + timedelta(days=7)).date().isoformat()

    clients = await store.list_clients(status="active")
    engagements = db.table("engagements").select("*").eq(
        "user_id", user_id).in_("status", ["active","on_track","at_risk"]).execute().data
    overdue_invoices = db.table("invoices").select(
        "id, client_name, total, currency, due_date, follow_up_count"
    ).eq("user_id", user_id).eq("status", "overdue").execute().data
    pending_invoices = db.table("invoices").select(
        "id, client_name, total, currency, due_date"
    ).eq("user_id", user_id).eq("status", "sent").lte("due_date", seven_days).execute().data
    pending_tasks = db.table("manager_tasks").select("*").eq(
        "user_id", user_id).eq("status", "proposed").execute().data
    income_30d = db.table("transactions").select("amount").eq(
        "user_id", user_id).eq("type", "income").gte("date", thirty_days_ago).execute().data
    user_row = db.table("users").select(
        "butler_memory, profile"
    ).eq("id", user_id).single().execute().data

    total_income = sum(t["amount"] for t in income_30d) if income_30d else 0
    overdue_total = sum(i["total"] for i in overdue_invoices) if overdue_invoices else 0
    at_risk_count = len([e for e in engagements if e["status"] == "at_risk"])
    silent_clients = [
        c for c in clients
        if c.get("last_activity_at") and
        (now - datetime.fromisoformat(c["last_activity_at"].replace("Z",""))).days > 21
    ]

    return {
        "client_count": len(clients),
        "clients": clients[:10],  # top 10 for prompt context
        "active_engagement_count": len(engagements),
        "at_risk_count": at_risk_count,
        "overdue_invoice_count": len(overdue_invoices),
        "overdue_total": overdue_total,
        "pending_due_soon": len(pending_invoices),
        "pending_decisions": len(pending_tasks),
        "income_30d": total_income,
        "monthly_goal": (user_row.get("profile") or {}).get("monthly_revenue_goal", 0),
        "silent_clients": [c["name"] for c in silent_clients[:3]],
        "existing_memory": user_row.get("butler_memory") or {}
    }


def _assess(state: dict) -> list[dict]:
    """Rule-based findings. Returns list of finding dicts for the briefing prompt."""
    findings = []
    if state["overdue_total"] > 0:
        findings.append({
            "type": "overdue_invoices",
            "severity": "critical" if state["overdue_total"] > 1000 else "warning",
            "detail": f"{state['overdue_invoice_count']} invoices overdue totalling ${state['overdue_total']:,.0f}"
        })
    if state["at_risk_count"] > 0:
        findings.append({
            "type": "at_risk_engagements",
            "severity": "warning",
            "detail": f"{state['at_risk_count']} engagement(s) marked at risk"
        })
    if state["silent_clients"]:
        findings.append({
            "type": "silent_clients",
            "severity": "info",
            "detail": f"No activity logged for {', '.join(state['silent_clients'])} in 21+ days"
        })
    if state["monthly_goal"] > 0:
        pct = (state["income_30d"] / state["monthly_goal"]) * 100
        if pct < 50:
            findings.append({
                "type": "goal_behind",
                "severity": "warning",
                "detail": f"At {pct:.0f}% of monthly goal (${state['income_30d']:,.0f} of ${state['monthly_goal']:,.0f})"
            })
    if state["pending_decisions"] > 0:
        findings.append({
            "type": "pending_decisions",
            "severity": "info",
            "detail": f"{state['pending_decisions']} action(s) need your approval"
        })
    return findings


def _build_briefing_prompt(state: dict, findings: list) -> str:
    prev_summary = state["existing_memory"].get("last_briefing_summary", "")
    return f"""
You are Kora, an AI business partner generating a morning briefing for a freelancer or small business owner.
Be specific, warm, and concise. Reference real numbers. Sound like a smart colleague, not a dashboard.

BUSINESS SNAPSHOT:
- Active clients: {state['client_count']}
- Active engagements: {state['active_engagement_count']}
- At-risk engagements: {state['at_risk_count']}
- Income last 30 days: ${state['income_30d']:,.0f}
- Monthly goal: ${state['monthly_goal']:,.0f} (0 = not set)
- Overdue invoices: {state['overdue_invoice_count']} totalling ${state['overdue_total']:,.0f}
- Invoices due this week: {state['pending_due_soon']}
- Decisions waiting for approval: {state['pending_decisions']}
- Clients with no activity in 21+ days: {', '.join(state['silent_clients']) or 'none'}

FINDINGS:
{json.dumps(findings, indent=2)}

PREVIOUS SUMMARY: {prev_summary or 'First briefing.'}

Return ONLY valid JSON:
{{
  "headline": "One sentence. The single most important thing right now.",
  "two_sentence_summary": "2 sentences. Where they stand + what matters most today.",
  "key_insight": "One specific observation with a real number.",
  "focus_today": ["up to 3 specific actions, ordered by importance"],
  "going_well": "One thing that is genuinely positive (skip if nothing)",
  "watch_out": "One risk or pattern to watch (skip if nothing)"
}}
"""


def _parse_briefing(raw: str) -> dict:
    clean = raw.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        return {"headline": "Your briefing is ready.", "two_sentence_summary": raw[:200]}


def _update_rolling_insights(existing: list, new_insight: str) -> list:
    if not new_insight:
        return existing
    updated = [new_insight] + existing
    return updated[:5]  # keep last 5
```

### Butler API router (`app/routers/butler.py`)

```python
from fastapi import APIRouter, Depends
from app.dependencies import get_current_user
from app.services.butler_agent import generate_morning_briefing
from app.services.health_agent import compute_client_health

router = APIRouter(prefix="/butler", tags=["butler"])

@router.get("")
async def get_butler_state(user=Depends(get_current_user)):
    """Get current butler memory + last briefing. Used on page load."""
    from supabase import create_client
    from app.config import settings
    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    user_row = db.table("users").select("butler_memory").eq(
        "id", user["id"]).single().execute().data
    last_briefing = db.table("alerts").select("*").eq(
        "user_id", user["id"]).eq("type", "morning_briefing").order(
        "created_at", desc=True).limit(1).execute().data
    return {
        "memory": user_row.get("butler_memory") or {},
        "last_briefing": last_briefing[0] if last_briefing else None
    }

@router.post("/run")
async def run_butler(user=Depends(get_current_user)):
    """On-demand briefing trigger (button on Butler page)."""
    briefing = await generate_morning_briefing(user["id"])
    return briefing

@router.post("/clients/{client_id}/health")
async def refresh_client_health(client_id: str, user=Depends(get_current_user)):
    """Refresh health score for a single client."""
    result = await compute_client_health(user["id"], client_id)
    return result
```

---

## Phase 4 — Proposal generator

### Proposal router (`app/routers/proposals.py`)

```python
from fastapi import APIRouter, Depends
from app.dependencies import get_current_user
from app.services.proposal_agent import generate_proposal
from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID

router = APIRouter(prefix="/proposals", tags=["proposals"])

class ProposalGenerateRequest(BaseModel):
    client_id: Optional[UUID] = None
    title: str = Field(..., min_length=1, max_length=200)
    scope_description: str = Field(..., min_length=10, max_length=2000)
    deliverables_raw: str = Field(..., max_length=2000)
    timeline_description: str = Field(..., max_length=1000)
    total_amount: float = Field(..., ge=0)
    currency: str = Field('USD', max_length=3)
    pricing_type: str = Field('fixed', pattern='^(fixed|hourly|retainer|milestone)$')
    payment_terms: str = Field('50% upfront, 50% on completion', max_length=200)
    valid_days: int = Field(30, ge=7, le=90)

@router.get("")
async def list_proposals(user=Depends(get_current_user)):
    from supabase import create_client
    from app.config import settings
    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    res = db.table("proposals").select(
        "*, clients(name, email)"
    ).eq("user_id", user["id"]).order("created_at", desc=True).execute()
    return res.data

@router.post("/generate")
async def create_proposal(body: ProposalGenerateRequest, user=Depends(get_current_user)):
    from app.utils.security import sanitize_prompt_input
    body.scope_description = sanitize_prompt_input(body.scope_description)
    body.deliverables_raw = sanitize_prompt_input(body.deliverables_raw)
    return await generate_proposal(user["id"], body)

@router.post("/{proposal_id}/accept")
async def accept_proposal(proposal_id: str, user=Depends(get_current_user)):
    """Accept a proposal → auto-generate a contract."""
    from app.services.proposal_agent import proposal_to_contract
    return await proposal_to_contract(user["id"], proposal_id)

@router.post("/{proposal_id}/send")
async def send_proposal(proposal_id: str, user=Depends(get_current_user)):
    """Queue proposal email for HITL approval."""
    from supabase import create_client
    from app.config import settings
    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    proposal = db.table("proposals").select("*, clients(name, email)").eq(
        "id", proposal_id).eq("user_id", user["id"]).single().execute().data
    # Queue as manager_task for approval
    db.table("manager_tasks").insert({
        "user_id": user["id"],
        "kind": "send_proposal",
        "title": f"Send proposal to {proposal['clients']['name']}",
        "rationale": f"Proposal '{proposal['title']}' for ${proposal['total_amount']:,.0f} ready to send.",
        "severity": "info",
        "status": "proposed",
        "payload": {"proposal_id": proposal_id},
        "source_record_type": "proposal",
        "source_record_id": proposal_id
    }).execute()
    return {"queued": True}
```

---

## Phase 5 — Retainer tracking

### Retainer invoicer worker (`workers/retainer_invoicer.py`)

```python
"""
Cloud Scheduler: 30 6 * * * (06:30 UTC daily)
Creates invoices for retainers due today or past due.
"""
import asyncio
from datetime import datetime, date
from supabase import create_client
from app.config import settings
from app.services.agent_logger import log_action

async def run():
    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    today = date.today().isoformat()

    due_retainers = db.table("retainers").select(
        "*, clients(name, email)"
    ).eq("status", "active").eq("auto_invoice", True).lte(
        "next_invoice_date", today).execute().data

    for retainer in due_retainers:
        try:
            await _create_retainer_invoice(retainer, db)
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"Retainer invoice failed for {retainer['id']}: {e}")

async def _create_retainer_invoice(retainer: dict, db):
    from dateutil.relativedelta import relativedelta
    from datetime import date

    client = retainer.get("clients", {})
    invoice_data = {
        "user_id": retainer["user_id"],
        "client_id": retainer["client_id"],
        "client_name": client.get("name", ""),
        "client_email": client.get("email", ""),
        "retainer_id": retainer["id"],
        "line_items": [{"description": retainer["title"], "qty": 1, "rate": retainer["amount"]}],
        "subtotal": retainer["amount"],
        "tax_rate": 0,
        "total": retainer["amount"],
        "currency": retainer["currency"],
        "status": "draft",   # user reviews before sending
        "due_date": (date.today() + relativedelta(days=14)).isoformat()
    }
    db.table("invoices").insert(invoice_data).execute()

    # Advance next_invoice_date by billing cycle
    next_date = _advance_date(retainer["next_invoice_date"], retainer["billing_cycle"])
    db.table("retainers").update({"next_invoice_date": next_date}).eq(
        "id", retainer["id"]).execute()

    await log_action(
        user_id=retainer["user_id"],
        agent_type="butler",
        action=f"Created retainer invoice for {client.get('name', 'client')}",
        input_data={"retainer_id": retainer["id"]},
        output_data={"amount": retainer["amount"]},
        latency_ms=0,
        triggered_by="scheduler"
    )

def _advance_date(current_date_str: str, cycle: str) -> str:
    from dateutil.relativedelta import relativedelta
    from datetime import date
    d = date.fromisoformat(current_date_str)
    delta = {"weekly": relativedelta(weeks=1), "monthly": relativedelta(months=1),
             "quarterly": relativedelta(months=3), "annual": relativedelta(years=1)}
    return (d + delta[cycle]).isoformat()

if __name__ == "__main__":
    asyncio.run(run())
```

---

## Phase 6 — Supervisor integration

Add to `services/supervisor.py` in `gather_state()`:

```python
# Add to existing gather_state() function:
from app.services.client_store import ClientStore

async def _gather_client_context(user_id: str) -> dict:
    store = ClientStore(user_id)
    clients = await store.list_clients()
    at_risk = [c for c in clients if c.get("health_score", 100) < 50]
    silent = [c for c in clients if c.get("last_activity_at") and
              (datetime.utcnow() - datetime.fromisoformat(
                  c["last_activity_at"].replace("Z",""))).days > 21]
    return {
        "total_clients": len(clients),
        "at_risk_clients": [{"name": c["name"], "health": c["health_score"]} for c in at_risk],
        "silent_clients": [c["name"] for c in silent],
        "needs_attention": len(at_risk) + len(silent)
    }

# In gather_state(), add:
# state["client_context"] = await _gather_client_context(user_id)

# In compose_briefing() prompt, add a section:
# CLIENT RELATIONSHIPS:
# Total active clients: {state['client_context']['total_clients']}
# At-risk clients: {', '.join(c['name'] for c in state['client_context']['at_risk_clients']) or 'none'}
# Silent clients (21+ days): {', '.join(state['client_context']['silent_clients']) or 'none'}
```

---

## New Cloud Scheduler jobs

```bash
# Morning briefing (new, replaces/extends daily_digest at same time)
gcloud scheduler jobs create http morning-briefing \
  --schedule="0 7 * * *" \
  --uri="https://kora-api-xxx-uc.a.run.app/workers/morning-briefing" \
  --oidc-service-account-email=kora-scheduler@$PROJECT_ID.iam.gserviceaccount.com \
  --location=us-central1

# Retainer invoicer (new)
gcloud scheduler jobs create http retainer-invoicer \
  --schedule="30 6 * * *" \
  --uri="https://kora-api-xxx-uc.a.run.app/workers/retainer-invoicer" \
  --oidc-service-account-email=kora-scheduler@$PROJECT_ID.iam.gserviceaccount.com \
  --location=us-central1

# Client health scores (new)
gcloud scheduler jobs create http client-health \
  --schedule="0 6 * * *" \
  --uri="https://kora-api-xxx-uc.a.run.app/workers/client-health" \
  --oidc-service-account-email=kora-scheduler@$PROJECT_ID.iam.gserviceaccount.com \
  --location=us-central1
```
