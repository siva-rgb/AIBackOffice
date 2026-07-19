from __future__ import annotations

from datetime import datetime, timezone

from .. import store
from ..models import Alert, Client, ClientNote, QuickCapture
from . import agent_logger
from .invoice_agent import _days_overdue
from .vertex_ai import generate_with_retry, get_ai

# Butler / AI business partner (manager_skill/SKILL.md). A context + intelligence
# layer above the point agents. Clients link to invoices/contracts by
# case-insensitive name match (no FK on the hot tables → backward compatible).
# Health scores are computed SERVER-SIDE only and never trusted from the client.
# The morning briefing gathers state deterministically, then makes ONE LLM call.

_SILENT_DAYS = 21  # client considered "silent" after this many days of no activity


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _days_since(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).days
    except ValueError:
        return None


def _norm(name: str | None) -> str:
    return (name or "").strip().lower()


# --- Client ↔ invoice/contract linkage (by name) ----------------------------
def _client_invoices(user_id: str, client_name: str):
    target = _norm(client_name)
    return [i for i in store.list_invoices(user_id) if _norm(i.client_name) == target]


def _client_contracts(user_id: str, client_name: str):
    target = _norm(client_name)
    return [c for c in store.list_contracts(user_id) if _norm(c.client_name) == target]


def _financials(invoices) -> dict:
    invoiced = sum(i.total for i in invoices)
    paid = sum(i.total for i in invoices if i.status == "paid")
    outstanding = sum(i.total for i in invoices if i.status in ("sent", "viewed", "overdue"))
    overdue = [i for i in invoices if i.status == "overdue" or
               (i.status in ("sent", "viewed") and _days_overdue(i.due_date) > 0)]
    return {
        "invoiced": round(invoiced, 2),
        "paid": round(paid, 2),
        "outstanding": round(outstanding, 2),
        "overdueCount": len(overdue),
        "overdueTotal": round(sum(i.total for i in overdue), 2),
    }


# --- Health score (deterministic, server-side) ------------------------------
def compute_client_health(user_id: str, client: Client, *, persist: bool = True) -> dict:
    """Score a client relationship 0-100 from real signals: overdue money, stalled
    work, and silence. Deterministic and cheap — no LLM, never trusts client input."""
    invoices = _client_invoices(user_id, client.name)
    fin = _financials(invoices)
    engagements = store.list_engagements(user_id, client.id)
    at_risk = [e for e in engagements if e.status == "at_risk"]
    active = [e for e in engagements if e.status in ("active", "on_track", "at_risk", "planning")]
    silent_days = _days_since(client.last_activity_at)

    score = 100
    risks: list[str] = []
    positives: list[str] = []

    if fin["overdueCount"]:
        score -= min(40, 15 + fin["overdueCount"] * 10)
        risks.append(f"{fin['overdueCount']} overdue invoice(s) totalling {fin['overdueTotal']:,.0f}")
    elif fin["paid"] > 0 and fin["outstanding"] == 0:
        positives.append("All invoices paid")

    if at_risk:
        score -= 20
        risks.append(f"{len(at_risk)} engagement(s) marked at risk")
    elif active:
        positives.append(f"{len(active)} engagement(s) progressing")

    if silent_days is not None and silent_days > _SILENT_DAYS:
        score -= 15
        risks.append(f"No activity logged in {silent_days} days")
    elif silent_days is not None and silent_days <= 7:
        positives.append("Recent activity")

    if client.status == "churned":
        score = min(score, 20)
    if client.status == "prospect" and not invoices:
        score = max(score, 60)

    score = max(0, min(100, score))
    label = ("on_track" if score >= 75 else "at_risk" if score >= 55
             else "needs_attention" if score >= 35 else "critical")

    if persist:
        try:
            store.update_client(user_id, client.id, {
                "health_score": score, "health_label": label, "health_updated_at": _now(),
            })
        except Exception as exc:  # pragma: no cover
            print(f"[butler] health persist skipped: {exc}")

    return {"healthScore": score, "healthLabel": label, "risks": risks, "positiveSignals": positives,
            "financials": fin}


# --- Client list + detail (for the frontend) --------------------------------
def list_clients_enriched(user_id: str, status: str | None = None) -> list[dict]:
    out = []
    for c in store.list_clients(user_id, status=status):
        invoices = _client_invoices(user_id, c.name)
        fin = _financials(invoices)
        engagements = store.list_engagements(user_id, c.id)
        active = [e for e in engagements if e.status in ("active", "on_track", "at_risk", "planning")]
        row = c.model_dump(by_alias=True)
        row["financials"] = fin
        row["activeEngagementCount"] = len(active)
        row["daysSinceActivity"] = _days_since(c.last_activity_at)
        out.append(row)
    return out


def get_client_detail(user_id: str, client_id: str) -> dict | None:
    c = store.get_client(user_id, client_id)
    if not c:
        return None
    invoices = _client_invoices(user_id, c.name)
    contracts = _client_contracts(user_id, c.name)
    engagements = store.list_engagements(user_id, c.id)
    notes = store.list_client_notes(user_id, c.id)
    proposals = [p for p in store.list_proposals(user_id) if p.client_id == c.id]
    retainers = [r for r in store.list_retainers(user_id) if r.client_id == c.id]
    health = compute_client_health(user_id, c, persist=True)
    c = store.get_client(user_id, client_id) or c  # re-read with fresh health
    detail = c.model_dump(by_alias=True)
    detail.update({
        "financials": health["financials"],
        "healthRisks": health["risks"],
        "healthPositives": health["positiveSignals"],
        "daysSinceActivity": _days_since(c.last_activity_at),
        "engagements": [e.model_dump(by_alias=True) for e in engagements],
        "notes": [n.model_dump(by_alias=True) for n in notes],
        "invoices": [{"id": i.id, "invoiceNumber": i.invoice_number, "total": i.total,
                      "status": i.status, "dueDate": i.due_date} for i in invoices],
        "contracts": [{"id": ct.id, "title": ct.title, "type": ct.type, "status": ct.status}
                      for ct in contracts],
        "proposals": [{"id": p.id, "title": p.title, "totalAmount": p.total_amount,
                       "status": p.status} for p in proposals],
        "retainers": [{"id": r.id, "title": r.title, "amount": r.amount,
                       "billingCycle": r.billing_cycle, "status": r.status} for r in retainers],
    })
    # Task ledger — the open work owed on this relationship.
    try:
        from .task_ledger import is_overdue
        tasks = store.list_tasks(user_id, client_id=c.id)
        detail["tasks"] = [
            {"id": t.id, "title": t.title, "status": t.status, "priority": t.priority,
             "dueDate": t.due_date, "owner": t.owner, "source": t.source,
             "overdue": is_overdue(t)}
            for t in tasks
        ]
        detail["openTaskCount"] = sum(1 for t in tasks if t.status in ("todo", "in_progress", "blocked"))
    except Exception:
        detail["tasks"] = []
        detail["openTaskCount"] = 0

    # Relationship-graph facts (learned intelligence linked to this client). The
    # structured records above come from the Python join; this adds the fact edges
    # (email/meeting commitments etc.) that only live in the graph.
    try:
        from .graph_memory import query_subgraph
        sub = query_subgraph(user_id, c.name)
        detail["graphFacts"] = [
            {"rel": r["rel"], "label": r["label"]}
            for r in sub.get("relations", []) if r.get("type") == "fact"
        ]
    except Exception:
        detail["graphFacts"] = []
    return detail


def touch_client(user_id: str, client_id: str) -> None:
    try:
        store.update_client(user_id, client_id, {"last_activity_at": _now()})
    except Exception:
        pass


# --- Quick capture: parse one note (inline, never raises) -------------------
def parse_capture(user_id: str, capture_id: str, raw_text: str) -> QuickCapture | None:
    """Parse a stored capture into structured state and apply safe actions.
    Inline (Kora has no worker runtime); best-effort — failures are recorded,
    never lost. Returns the updated capture."""
    clients = store.list_clients(user_id)
    known = [c.name for c in clients]
    try:
        call = generate_with_retry(lambda: get_ai().parse_capture({"text": raw_text, "known_clients": known}))
        parsed = call.data if isinstance(call.data, dict) else {}
        entities = parsed.get("entities") or {}
        confidence = float(parsed.get("confidence", 0.5) or 0.5)
        actions = _apply_capture_actions(user_id, capture_id, entities, confidence, clients)
        status = "parsed" if confidence >= 0.5 else "partial"
        updated = store.update_capture(user_id, capture_id, {
            "parse_status": status,
            "parsed_intent": str(parsed.get("intent", "unknown"))[:40],
            "parsed_entities": entities,
            "ai_confidence": round(confidence, 2),
            "actions_taken": actions,
            "requires_review": confidence < 0.7,
            "parsed_at": _now(),
        })
        agent_logger.log_action(
            user_id=user_id, agent_type="butler",
            action=f"Parsed quick capture: {parsed.get('intent', 'unknown')}",
            input={"captureId": capture_id, "chars": len(raw_text)},
            output={"intent": parsed.get("intent"), "confidence": confidence, "actions": len(actions)},
            model_used=call.model_used, tokens_used=call.tokens_used, latency_ms=call.latency_ms,
            cost_usd=call.cost_usd, triggered_by="user", source_record_type="quick_capture",
            source_record_id=capture_id)
        return updated
    except Exception as exc:
        print(f"[butler] capture parse failed: {exc}")
        return store.update_capture(user_id, capture_id, {
            "parse_status": "failed", "requires_review": True,
            "parsed_entities": {"error": str(exc)[:200]}, "parsed_at": _now()})


def _apply_capture_actions(user_id, capture_id, entities, confidence, clients) -> list[dict]:
    actions: list[dict] = []
    name = entities.get("client_name")
    client = next((c for c in clients if _norm(c.name) == _norm(name)), None) if name else None

    # Always save a note when we have a matched client + content.
    note_content = (entities.get("note_content") or "").strip()
    if client and note_content:
        try:
            store.insert_client_note(ClientNote(
                id=store.uid("note"), user_id=user_id, client_id=client.id,
                quick_capture_id=capture_id, note_type="update",
                content_md=note_content, is_ai_generated=True, created_at=_now()))
            touch_client(user_id, client.id)
            actions.append({"type": "created_note", "clientId": client.id})
        except Exception as exc:
            print(f"[butler] note insert skipped: {exc}")

    # Update an active engagement's status only on high confidence.
    status_update = entities.get("status_update")
    if client and status_update and confidence >= 0.7:
        engagements = store.list_engagements(user_id, client.id)
        active = [e for e in engagements if e.status in ("active", "on_track", "at_risk", "planning")]
        if active:
            target = active[0]
            try:
                store.update_engagement(user_id, target.id, {"status": status_update, "updated_at": _now()})
                actions.append({"type": "updated_engagement", "id": target.id, "newStatus": status_update})
            except Exception as exc:
                print(f"[butler] engagement update skipped: {exc}")
    return actions


# --- Morning briefing -------------------------------------------------------
def _gather_state(user_id: str) -> dict:
    user = store.get_user(user_id)
    profile = user.profile if user else None
    clients = store.list_clients(user_id, status="active")
    all_clients = store.list_clients(user_id)
    engagements = [e for e in store.list_engagements(user_id)
                   if e.status in ("active", "on_track", "at_risk", "planning")]
    invoices = store.list_invoices(user_id)
    overdue = [i for i in invoices if i.status == "overdue" or
               (i.status in ("sent", "viewed") and _days_overdue(i.due_date) > 0)]
    txns = store.list_transactions(user_id)
    ym = datetime.now(timezone.utc).date().isoformat()[:7]
    income_30d = round(sum(abs(t.amount) for t in txns if t.type == "income" and t.date[:7] == ym), 2)
    pending = store.list_manager_tasks(user_id, status="proposed")
    captures_review = store.list_captures(user_id, requires_review=True)
    silent = [c.name for c in all_clients
              if (_days_since(c.last_activity_at) or 0) > _SILENT_DAYS][:3]

    state = {
        "user": user, "profile": profile,
        "currency": (user.currency if user else "USD"),
        "client_count": len(clients),
        "active_engagement_count": len(engagements),
        "at_risk_engagements": len([e for e in engagements if e.status == "at_risk"]),
        "overdue_count": len(overdue),
        "overdue_total": round(sum(i.total for i in overdue), 2),
        "income_30d": income_30d,
        "monthly_goal": (profile.monthly_revenue_goal if profile else None),
        "silent_clients": silent,
        "pending_decisions": len(pending),
        "captures_review": len(captures_review),
        "all_clients": all_clients,
        # Google state populated below (only when Supabase is configured)
        "google_connected": False,
        "clients_needing_reply": [],
        "silent_clients_email": [],
        "strained_relationships": [],
        "todays_client_meetings": [],
        "unlogged_meetings_count": 0,
        "open_action_items": 0,
        "overdue_action_items": 0,
    }
    _enrich_with_google_state(user_id, state)
    return state


def _enrich_with_google_state(user_id: str, state: dict) -> None:
    """Pull Google-connected intelligence into the state dict (best-effort)."""
    from ..config import settings as _settings
    if not _settings.SUPABASE_URL:
        return
    try:
        from supabase import create_client
        db = create_client(_settings.SUPABASE_URL, _settings.SUPABASE_SERVICE_ROLE_KEY)

        conn_rows = db.table("google_connections").select("connected").eq(
            "user_id", user_id).execute().data
        if not conn_rows or not conn_rows[0].get("connected"):
            return
        state["google_connected"] = True

        # Email intel from cache
        email_cache = db.table("email_intel_cache").select(
            "client_name, sentiment, action_needed, last_contact_days, last_contact_direction"
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
        ][:3]

        # Calendar (live, lightweight)
        from .calendar_intel import (
            get_todays_meetings_with_clients,
            get_unlogged_past_meetings,
        )
        todays = get_todays_meetings_with_clients(user_id)
        state["todays_client_meetings"] = [
            e["title"] for e in todays if e.get("is_client_meeting")
        ]
        unlogged = get_unlogged_past_meetings(user_id)
        state["unlogged_meetings_count"] = len(unlogged)

        # Meeting action items
        today_iso = datetime.now(timezone.utc).date().isoformat()
        open_actions = db.table("meeting_action_items").select(
            "id, due_date"
        ).eq("user_id", user_id).eq("status", "open").execute().data
        state["open_action_items"] = len(open_actions)
        state["overdue_action_items"] = sum(
            1 for a in open_actions
            if a.get("due_date") and a["due_date"] < today_iso
        )
    except Exception as exc:
        print(f"[butler] google state enrich failed: {exc}")


def _assess(state: dict) -> list[dict]:
    findings: list[dict] = []
    if state["overdue_total"]:
        findings.append({"type": "overdue_invoices",
                         "severity": "critical" if state["overdue_total"] > 1000 else "warning",
                         "detail": f"{state['overdue_count']} invoices overdue totalling {state['overdue_total']:,.0f}"})
    if state["at_risk_engagements"]:
        findings.append({"type": "at_risk_engagements", "severity": "warning",
                         "detail": f"{state['at_risk_engagements']} engagement(s) at risk"})
    if state["silent_clients"]:
        findings.append({"type": "silent_clients", "severity": "info",
                         "detail": f"No activity for {', '.join(state['silent_clients'])} in {_SILENT_DAYS}+ days"})
    goal = state["monthly_goal"]
    if goal:
        pct = (state["income_30d"] / goal) * 100 if goal else 0
        if pct < 50:
            findings.append({"type": "goal_behind", "severity": "warning",
                             "detail": f"At {pct:.0f}% of the monthly goal"})
    if state["pending_decisions"]:
        findings.append({"type": "pending_decisions", "severity": "info",
                         "detail": f"{state['pending_decisions']} action(s) awaiting approval"})
    return findings


def _refresh_health(user_id: str, clients) -> None:
    for c in clients:
        try:
            compute_client_health(user_id, c, persist=True)
        except Exception:
            pass


def generate_morning_briefing(user_id: str, triggered_by: str = "user") -> dict:
    state = _gather_state(user_id)
    _refresh_health(user_id, state["all_clients"])
    findings = _assess(state)
    prev = {}
    try:
        prev = store.get_butler_memory(user_id)
    except Exception:
        pass

    # Read supervisor memory so butler knows about escalation state and payment patterns.
    supervisor_memory: dict = {}
    try:
        supervisor_memory = store.get_manager_memory(user_id)
    except Exception:
        pass

    payload = {
        "business_name": (state["user"].business_name if state["user"] else None),
        "business_type": (state["profile"].business_type if state["profile"] else None),
        "currency": state["currency"],
        "client_count": state["client_count"],
        "active_engagement_count": state["active_engagement_count"],
        "at_risk_engagements": state["at_risk_engagements"],
        "income_30d": state["income_30d"],
        "monthly_goal": state["monthly_goal"],
        "overdue_count": state["overdue_count"],
        "overdue_total": state["overdue_total"],
        "silent_clients": state["silent_clients"],
        "pending_decisions": state["pending_decisions"],
        "captures_review": state["captures_review"],
        "findings": findings,
        "previous_summary": prev.get("lastBriefing", {}).get("twoSentenceSummary"),
        # Supervisor cross-run memory injected so butler can reference escalations
        "supervisor_last_run": supervisor_memory.get("lastRunAt"),
        "supervisor_status_line": supervisor_memory.get("lastBriefing", {}).get("statusLine"),
        "recent_escalations": [
            {"invoiceId": k, **v}
            for k, v in (supervisor_memory.get("escalationState") or {}).items()
            if v.get("lastAction")
        ][:5],
        "slow_payers": [
            {"clientName": v["clientName"], "avgDaysToPayment": v["avgDaysToPayment"]}
            for v in (supervisor_memory.get("paymentPatterns") or {}).values()
            if v.get("avgDaysToPayment", 0) > 14
        ][:3],
        # Google Butler enrichment
        "google_connected": state.get("google_connected", False),
        "clients_needing_reply": state.get("clients_needing_reply", []),
        "silent_clients_email": state.get("silent_clients_email", []),
        "strained_relationships": state.get("strained_relationships", []),
        "todays_client_meetings": state.get("todays_client_meetings", []),
        "unlogged_meetings_count": state.get("unlogged_meetings_count", 0),
        "open_action_items": state.get("open_action_items", 0),
        "overdue_action_items": state.get("overdue_action_items", 0),
    }
    try:
        from .playbook import assemble_context
        business_context = assemble_context(user_id, "briefing")
        if business_context:
            payload["business_context"] = business_context
    except Exception:
        pass
    ai = get_ai()
    model = tokens = latency = cost = None
    try:
        call = generate_with_retry(lambda: ai.compose_butler_briefing(payload))
        raw = call.data if isinstance(call.data, dict) else {}
        model, tokens, latency, cost = call.model_used, call.tokens_used, call.latency_ms, call.cost_usd
    except Exception as exc:
        raw = {"headline": "Your briefing is ready.", "two_sentence_summary": "Here's where things stand."}
        print(f"[butler] briefing failed: {exc}")

    briefing = _normalize_briefing(raw)
    try:
        from .validation import validate_briefing
        briefing = validate_briefing(briefing, state, user_id)
    except Exception:
        pass
    ran_at = _now()

    # Persist as an alert for the dashboard (deduped to once/day).
    try:
        if not store.alert_fired_recently(user_id, "morning_briefing", within_days=1):
            store.insert_alert(Alert(
                id=store.uid("alert"), user_id=user_id, type="morning_briefing", severity="info",
                title="Morning briefing", body=briefing["headline"],
                action_label="Open Butler", action_url="/butler", read=False, created_at=ran_at))
    except Exception:
        pass

    # Persist butler memory (rolling continuity).
    try:
        insights = ([briefing["keyInsight"]] + (prev.get("rollingInsights") or []))[:5] if briefing["keyInsight"] else (prev.get("rollingInsights") or [])
        store.set_butler_memory(user_id, {
            "lastBriefingAt": ran_at,
            "lastBriefing": briefing,
            "clientCount": state["client_count"],
            "activeEngagementCount": state["active_engagement_count"],
            "rollingInsights": insights,
        })
    except Exception as exc:
        print(f"[butler] memory not saved: {exc}")

    agent_logger.log_action(
        user_id=user_id, agent_type="butler", action="Generated morning briefing",
        input={"clients": state["client_count"], "findings": len(findings)},
        output={"headline": briefing["headline"]},
        model_used=model or "deterministic", tokens_used=tokens, latency_ms=latency, cost_usd=cost,
        triggered_by=triggered_by, source_record_type="butler")

    return {"briefing": briefing, "ranAt": ran_at}


def _normalize_briefing(raw: dict) -> dict:
    def s(key, *alts):
        for k in (key, *alts):
            v = raw.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""
    focus = raw.get("focus_today") or raw.get("focusToday") or []
    focus = [str(f).strip() for f in focus if isinstance(f, (str,)) and str(f).strip()][:3]
    return {
        "headline": s("headline") or "Here's where your business stands today.",
        "twoSentenceSummary": s("two_sentence_summary", "twoSentenceSummary", "summary"),
        "keyInsight": s("key_insight", "keyInsight"),
        "focusToday": focus,
        "goingWell": s("going_well", "goingWell"),
        "watchOut": s("watch_out", "watchOut"),
        "tone": (s("tone") or "steady"),
    }


def butler_snapshot(user_id: str) -> dict:
    """Cheap page-load snapshot (no LLM): memory + last briefing + headline stats."""
    try:
        memory = store.get_butler_memory(user_id)
    except Exception:
        memory = {}
    state = _gather_state(user_id)
    review_count = state["captures_review"]
    return {
        "memory": memory,
        "lastBriefing": memory.get("lastBriefing"),
        "lastBriefingAt": memory.get("lastBriefingAt"),
        "stats": {
            "clientCount": state["client_count"],
            "activeEngagements": state["active_engagement_count"],
            "atRiskEngagements": state["at_risk_engagements"],
            "overdueCount": state["overdue_count"],
            "overdueTotal": state["overdue_total"],
            "currency": state["currency"],
        },
        "reviewQueueCount": review_count,
    }
