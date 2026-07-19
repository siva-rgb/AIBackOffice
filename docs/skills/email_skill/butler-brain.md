# Google Butler — Butler Brain Reference

The Butler brain runs ONE Gemini call. Everything else is deterministic data gathering.

---

## Unified state gathering

```python
# Add to app/services/butler_agent.py

async def gather_full_state(user_id: str) -> dict:
    """
    Gather ALL data sources into one state dict.
    No AI calls here — everything is a DB read or Google API read (if connected).
    The result of this function is passed to ONE Gemini call.
    """
    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    now = datetime.utcnow()
    thirty_days_ago = (now - timedelta(days=30)).isoformat()

    state = {}

    # ── Financial (existing) ──
    overdue = db.table("invoices").select(
        "id, client_name, total, currency, due_date, follow_up_count"
    ).eq("user_id", user_id).eq("status", "overdue").execute().data
    state["overdue_invoices"] = overdue
    state["overdue_total"] = sum(i["total"] for i in overdue) if overdue else 0

    income = db.table("transactions").select("amount").eq(
        "user_id", user_id).eq("type", "income").gte("date", thirty_days_ago).execute().data
    state["income_30d"] = sum(t["amount"] for t in income) if income else 0

    user_row = db.table("users").select(
        "profile, butler_memory"
    ).eq("id", user_id).single().execute().data
    state["monthly_goal"] = (user_row.get("profile") or {}).get("monthly_revenue_goal", 0)
    state["existing_memory"] = user_row.get("butler_memory") or {}

    # ── Client (existing Butler) ──
    clients = db.table("clients").select(
        "id, name, health_score, health_label, status, last_activity_at"
    ).eq("user_id", user_id).eq("status", "active").execute().data
    state["clients"] = clients
    state["at_risk_clients"] = [c for c in clients if (c.get("health_score") or 100) < 50]

    engagements = db.table("engagements").select("*").eq(
        "user_id", user_id).in_("status", ["active", "on_track", "at_risk"]).execute().data
    state["at_risk_engagements"] = [e for e in engagements if e["status"] == "at_risk"]

    # ── Manager tasks ──
    pending = db.table("manager_tasks").select("id").eq(
        "user_id", user_id).eq("status", "proposed").execute().data
    state["pending_decisions"] = len(pending)

    # ── Google intelligence (only if connected) ──
    conn = db.table("google_connections").select("connected").eq(
        "user_id", user_id).execute().data
    google_connected = conn and conn[0].get("connected")
    state["google_connected"] = bool(google_connected)

    if google_connected:
        # Email intel (from cache — already processed by gmail_intel worker)
        email_cache = db.table("email_intel_cache").select(
            "client_name, sentiment, action_needed, action_description, "
            "last_contact_days, last_contact_direction, relationship_health"
        ).eq("user_id", user_id).execute().data

        state["clients_needing_reply"] = [
            e["client_name"] for e in email_cache
            if e.get("action_needed") and e.get("last_contact_direction") == "from_client"
        ][:3]
        state["silent_clients_email"] = [
            e["client_name"] for e in email_cache
            if (e.get("last_contact_days") or 0) > 14
        ][:3]
        state["strained_relationships"] = [
            e["client_name"] for e in email_cache
            if e.get("sentiment") in ("cautious", "strained")
        ]

        # Calendar (live API call — lightweight, no caching needed)
        from app.services.calendar_intel import (
            get_todays_meetings_with_clients,
            get_unlogged_past_meetings
        )
        todays = await get_todays_meetings_with_clients(user_id)
        state["todays_client_meetings"] = [
            e["title"] for e in todays if e["is_client_meeting"]
        ]
        unlogged = await get_unlogged_past_meetings(user_id)
        state["unlogged_meetings_count"] = len(unlogged)
        state["unlogged_meeting_clients"] = [
            c for m in unlogged for c in m["client_names"]
        ][:3]

        # Drive items pending review
        drive_items = db.table("manager_tasks").select("id").eq(
            "user_id", user_id).eq("status", "proposed").eq(
            "source_record_type", "drive_file").execute().data
        state["drive_items_pending"] = len(drive_items)

        # Meeting action items
        open_actions = db.table("meeting_action_items").select("*").eq(
            "user_id", user_id).eq("status", "open").execute().data
        state["open_action_items"] = len(open_actions)
        overdue_actions = [
            a for a in open_actions
            if a.get("due_date") and a["due_date"] < now.date().isoformat()
        ]
        state["overdue_action_items"] = len(overdue_actions)

    return state
```

---

## Briefing prompt

```python
def build_briefing_prompt(state: dict) -> str:
    prev_summary = state["existing_memory"].get("last_briefing_summary", "")
    goal_pct = int((state["income_30d"] / state["monthly_goal"]) * 100) \
               if state["monthly_goal"] > 0 else 0

    google_section = ""
    if state.get("google_connected"):
        google_section = f"""
EMAIL INTELLIGENCE:
- Clients who replied and need your response: {', '.join(state.get('clients_needing_reply', [])) or 'none'}
- Clients silent for 14+ days: {', '.join(state.get('silent_clients_email', [])) or 'none'}
- Strained relationships: {', '.join(state.get('strained_relationships', [])) or 'none'}

CALENDAR:
- Client meetings today: {', '.join(state.get('todays_client_meetings', [])) or 'none'}
- Past meetings with no notes logged: {state.get('unlogged_meetings_count', 0)}
  (Clients: {', '.join(state.get('unlogged_meeting_clients', [])) or 'none'})

MEETING FOLLOW-UPS:
- Open action items: {state.get('open_action_items', 0)}
- Overdue: {state.get('overdue_action_items', 0)}

DRIVE:
- New documents needing review: {state.get('drive_items_pending', 0)}
"""

    return f"""
You are Kora, an AI business partner generating a morning briefing.
Sound like a smart colleague — specific, warm, concise. Use real numbers.
Return ONLY valid JSON.

TODAY: {datetime.utcnow().strftime('%A, %B %-d, %Y')}

FINANCIAL:
- Income last 30 days: ${state['income_30d']:,.0f}
- Monthly goal: ${state['monthly_goal']:,.0f} ({goal_pct}% achieved)
- Overdue invoices: {len(state['overdue_invoices'])} totalling ${state['overdue_total']:,.0f}

CLIENT RELATIONSHIPS:
- Active clients: {len(state.get('clients', []))}
- At-risk clients: {len(state.get('at_risk_clients', []))}
- At-risk engagements: {len(state.get('at_risk_engagements', []))}

DECISIONS WAITING:
- Pending approvals: {state['pending_decisions']}
{google_section}
PREVIOUS BRIEFING: {prev_summary or 'First briefing.'}

Return JSON:
{{
  "headline": "One sentence. The single most important thing right now.",
  "two_sentence_summary": "Where they stand + what matters most today.",
  "key_insight": "One observation with a real number from the data.",
  "focus_today": ["Action 1 — most important", "Action 2", "Action 3 (optional)"],
  "going_well": "One genuine positive. Omit if nothing qualifies.",
  "watch_out": "One risk or pattern. Omit if nothing qualifies.",
  "tone": "energetic|steady|cautious"
}}
"""
```

---

## Morning briefing worker

```python
# workers/butler_google_sync.py
"""
Cloud Scheduler: 0 7 * * * (07:00 UTC daily)
Runs Google sync → then generates morning briefing.
"""
import asyncio
from app.services.gmail_intel import sync_client_email_intel
from app.services.drive_intel import sync_drive_intel
from app.services.butler_agent import gather_full_state, build_briefing_prompt
from app.services.vertex_ai import generate_with_retry, getGeminiForAgent
from app.services.agent_logger import log_action
from supabase import create_client
from app.config import settings
from datetime import datetime
import json

async def run_for_user(user_id: str):
    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    start = datetime.utcnow()

    # Step 1: Sync Google sources (if connected)
    conn = db.table("google_connections").select("connected").eq(
        "user_id", user_id).execute().data
    if conn and conn[0].get("connected"):
        await sync_client_email_intel(user_id)
        await sync_drive_intel(user_id)
        # Calendar: no sync needed — fetched live in gather_full_state()

    # Step 2: Gather all state
    state = await gather_full_state(user_id)

    # Step 3: ONE Gemini call
    model = getGeminiForAgent("butler")
    prompt = build_briefing_prompt(state)
    result = await generate_with_retry(lambda: model.generate_content(prompt))
    raw = result.response.candidates[0].content.parts[0].text
    try:
        briefing = json.loads(raw.replace("```json", "").replace("```", "").strip())
    except Exception:
        briefing = {"headline": "Your briefing is ready.", "two_sentence_summary": raw[:200]}

    latency_ms = int((datetime.utcnow() - start).total_seconds() * 1000)

    # Step 4: Persist briefing
    butler_memory = {
        "last_briefing_at": datetime.utcnow().isoformat(),
        "last_briefing_summary": briefing.get("two_sentence_summary", ""),
        "client_count": len(state.get("clients", [])),
    }
    db.table("users").update({"butler_memory": butler_memory}).eq("id", user_id).execute()

    db.table("alerts").insert({
        "user_id": user_id,
        "type": "morning_briefing",
        "severity": "info",
        "title": "Morning briefing",
        "body": briefing.get("headline", "Your briefing is ready."),
        "read": False,
        "action_url": "/butler"
    }).execute()

    await log_action(
        user_id=user_id,
        agent_type="butler",
        action="Generated morning briefing",
        input_data={"google_connected": state.get("google_connected"),
                    "clients": len(state.get("clients", []))},
        output_data=briefing,
        latency_ms=latency_ms,
        triggered_by="scheduler"
    )

    return briefing


async def run():
    db = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    users = db.table("users").select("id, plan").neq("plan", "free").execute().data
    for user in users:
        try:
            await run_for_user(user["id"])
            await asyncio.sleep(1)
        except Exception as e:
            print(f"Butler sync failed for {user['id']}: {e}")

if __name__ == "__main__":
    asyncio.run(run())
```
