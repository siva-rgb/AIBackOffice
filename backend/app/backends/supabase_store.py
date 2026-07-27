from __future__ import annotations

from datetime import datetime, timedelta, timezone

from supabase import create_client

from ..config import settings
from ..models import (
    AgentLog,
    Alert,
    Client,
    ClientNote,
    Contract,
    Engagement,
    Invoice,
    ManagerTask,
    Proposal,
    QuickCapture,
    Retainer,
    Story,
    Task,
    Transaction,
    User,
)
from .repository import TenantQuery

# Supabase-backed data backend (KORA_DATA_BACKEND=supabase). Same function
# surface as memory_store, so nothing else in the app changes.
#
# All user-data queries MUST go through the `repo(user_id)` wrapper, which
# automatically injects `eq("user_id", ...)` on every read/write and
# validates that insert rows carry the caller's user_id. The raw `_sb` client
# is only for truly tenant-agnostic operations (auth, admin, cross-tenant).

_sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)


def repo(user_id: str) -> TenantQuery:
    return TenantQuery(_sb, user_id)


def _dump(model) -> dict:
    return model.model_dump(by_alias=False, mode="json")


# ---- row <-> model helpers -------------------------------------------------
def _agent_to_row(log: AgentLog) -> dict:
    row = _dump(log)
    cost = row.pop("cost_usd", None)
    if cost is not None and isinstance(row.get("output"), dict):
        row["output"] = {**row["output"], "_cost_usd": cost}
    elif cost is not None:
        row["output"] = {"_value": row.get("output"), "_cost_usd": cost}
    return row


def _agent_from_row(row: dict) -> AgentLog:
    out = row.get("output")
    if isinstance(out, dict) and "_cost_usd" in out:
        out = dict(out)
        row = {**row, "cost_usd": out.pop("_cost_usd"), "output": out}
    return AgentLog(**row)


def _contract_to_row(c: Contract) -> dict:
    row = _dump(c)
    provider = row.pop("provider_name", None)
    terms = dict(row.get("terms") or {})
    if provider is not None:
        terms["_provider_name"] = provider
    row["terms"] = terms
    return row


def _contract_from_row(row: dict) -> Contract:
    terms = dict(row.get("terms") or {})
    provider = terms.pop("_provider_name", None)
    return Contract(**{**row, "terms": terms, "provider_name": provider})


# ---- Users -----------------------------------------------------------------
# User operations use `_sb` directly because user_id IS the tenant identity
# and the users table is accessed by id/email (not a separate tenant column).


def get_user(user_id: str) -> User | None:
    r = _sb.table("users").select("*").eq("id", user_id).limit(1).execute()
    return User(**r.data[0]) if r.data else None


def get_user_by_email(email: str) -> User | None:
    r = _sb.table("users").select("*").eq("email", email).limit(1).execute()
    return User(**r.data[0]) if r.data else None


def verify_token(token: str) -> User | None:
    """Verify a Supabase access token and return the matching profile row."""
    try:
        resp = _sb.auth.get_user(token)
        au = getattr(resp, "user", None)
        if not au:
            return None
        return get_user(au.id)
    except Exception:
        return None


def get_user_by_stripe_customer(customer_id: str) -> User | None:
    r = _sb.table("users").select("*").eq("stripe_customer_id", customer_id).limit(1).execute()
    return User(**r.data[0]) if r.data else None


def update_user(user_id: str, patch: dict) -> User | None:
    r = _sb.table("users").update(patch).eq("id", user_id).execute()
    return User(**r.data[0]) if r.data else None


# ---- Transactions ----------------------------------------------------------
def list_transactions(user_id: str) -> list[Transaction]:
    r = repo(user_id).select("transactions").order("date", desc=True).execute()
    return [Transaction(**row) for row in r.data]


def insert_transactions(rows: list[Transaction]) -> list[Transaction]:
    if not rows:
        return []
    user_id = rows[0].user_id
    existing = repo(user_id).select("transactions").order("date", desc=True).execute()
    seen = {(e["date"], e["description"], round(float(e["amount"]), 2)) for e in existing.data}
    new: list[Transaction] = []
    for row in rows:
        key = (row.date, row.description, round(float(row.amount), 2))
        if key not in seen:
            seen.add(key)
            new.append(row)
    if new:
        repo(user_id).raw_table("transactions").insert([_dump(t) for t in new]).execute()
    return new


def upsert_transactions(rows: list[Transaction]) -> list[Transaction]:
    if rows:
        user_id = rows[0].user_id
        repo(user_id).raw_table("transactions").upsert([_dump(t) for t in rows]).execute()
    return rows


def update_transaction(user_id: str, transaction_id: str, patch: dict) -> Transaction | None:
    r = repo(user_id).update("transactions", patch, transaction_id).execute()
    return Transaction(**r.data[0]) if r.data else None


# ---- Invoices --------------------------------------------------------------
def list_invoices(user_id: str) -> list[Invoice]:
    r = repo(user_id).select("invoices").order("created_at", desc=True).execute()
    return [Invoice(**row) for row in r.data]


def get_invoice(user_id: str, invoice_id: str) -> Invoice | None:
    r = repo(user_id).select("invoices").eq("id", invoice_id).limit(1).execute()
    return Invoice(**r.data[0]) if r.data else None


def insert_invoice(invoice: Invoice) -> Invoice:
    repo(invoice.user_id).insert("invoices", _dump(invoice)).execute()
    return invoice


def update_invoice(user_id: str, invoice_id: str, patch: dict) -> Invoice | None:
    r = repo(user_id).update("invoices", patch, invoice_id).execute()
    return Invoice(**r.data[0]) if r.data else None


def update_invoice_pdf(user_id: str, invoice_id: str, pdf_path: str) -> Invoice | None:
    return update_invoice(user_id, invoice_id, {"pdf_path": pdf_path})


def update_invoice_email(user_id: str, invoice_id: str, message_id: str) -> Invoice | None:
    from datetime import datetime, timezone

    return update_invoice(
        user_id,
        invoice_id,
        {
            "email_message_id": message_id,
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "status": "sent",
        },
    )


def next_invoice_number(user_id: str) -> str:
    year = datetime.now(timezone.utc).year
    r = repo(user_id).select("invoices").gte("created_at", f"{year}-01-01").execute()
    return f"INV-{year}-{(r.count or 0) + 1:03d}"


# ---- Agent logs ------------------------------------------------------------
def list_agent_logs(user_id: str) -> list[AgentLog]:
    r = repo(user_id).select("agent_logs").order("created_at", desc=True).execute()
    return [_agent_from_row(row) for row in r.data]


def list_all_agent_logs() -> list[AgentLog]:
    r = _sb.table("agent_logs").select("*").order("created_at", desc=True).limit(1000).execute()
    return [_agent_from_row(row) for row in r.data]


def insert_agent_log(log: AgentLog) -> AgentLog:
    repo(log.user_id).insert("agent_logs", _agent_to_row(log)).execute()
    return log


# ---- Alerts ----------------------------------------------------------------
def list_alerts(user_id: str) -> list[Alert]:
    r = repo(user_id).select("alerts").order("created_at", desc=True).execute()
    return [Alert(**row) for row in r.data]


def insert_alert(alert: Alert) -> Alert:
    repo(alert.user_id).insert("alerts", _dump(alert)).execute()
    return alert


def alert_fired_recently(user_id: str, type_: str, within_days: int = 7) -> bool:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=within_days)).isoformat()
    r = repo(user_id).select("alerts").eq("type", type_).gte("created_at", cutoff).limit(1).execute()
    return bool(r.data)


def mark_alert_read(user_id: str, alert_id: str) -> Alert | None:
    r = repo(user_id).update("alerts", {"read": True, "read_at": datetime.now(timezone.utc).isoformat()}, alert_id).execute()
    return Alert(**r.data[0]) if r.data else None


# ---- Contracts -------------------------------------------------------------
def list_contracts(user_id: str) -> list[Contract]:
    r = repo(user_id).select("contracts").order("created_at", desc=True).execute()
    return [_contract_from_row(row) for row in r.data]


def get_contract(user_id: str, contract_id: str) -> Contract | None:
    r = repo(user_id).select("contracts").eq("id", contract_id).limit(1).execute()
    return _contract_from_row(r.data[0]) if r.data else None


def insert_contract(contract: Contract) -> Contract:
    repo(contract.user_id).insert("contracts", _contract_to_row(contract)).execute()
    return contract


def update_contract(user_id: str, contract_id: str, patch: dict) -> Contract | None:
    r = repo(user_id).update("contracts", patch, contract_id).execute()
    return _contract_from_row(r.data[0]) if r.data else None


# ---- Manager tasks (supervisor approval queue) -----------------------------
def list_manager_tasks(user_id: str, status: str | None = None) -> list[ManagerTask]:
    q = repo(user_id).select("manager_tasks")
    if status:
        q = q.eq("status", status)
    r = q.order("created_at", desc=True).execute()
    return [ManagerTask(**row) for row in r.data]


def get_manager_task(user_id: str, task_id: str) -> ManagerTask | None:
    r = repo(user_id).select("manager_tasks").eq("id", task_id).limit(1).execute()
    return ManagerTask(**r.data[0]) if r.data else None


def find_open_manager_task(user_id: str, kind: str, source_record_id: str | None) -> ManagerTask | None:
    q = repo(user_id).select("manager_tasks").eq("kind", kind).eq("status", "proposed")
    q = q.is_("source_record_id", "null") if source_record_id is None else q.eq("source_record_id", source_record_id)
    r = q.limit(1).execute()
    return ManagerTask(**r.data[0]) if r.data else None


def insert_manager_task(task: ManagerTask) -> ManagerTask:
    repo(task.user_id).insert("manager_tasks", _dump(task)).execute()
    return task


def update_manager_task(user_id: str, task_id: str, patch: dict) -> ManagerTask | None:
    r = repo(user_id).update("manager_tasks", patch, task_id).execute()
    return ManagerTask(**r.data[0]) if r.data else None


# ---- Manager memory (supervisor continuity) --------------------------------
def get_manager_memory(user_id: str) -> dict:
    r = _sb.table("users").select("manager_memory").eq("id", user_id).limit(1).execute()
    return (r.data[0].get("manager_memory") or {}) if r.data else {}


def set_manager_memory(user_id: str, memory: dict) -> dict:
    _sb.table("users").update({"manager_memory": memory}).eq("id", user_id).execute()
    return memory


# ---- Butler: clients -------------------------------------------------------
def list_clients(user_id: str, status: str | None = None) -> list[Client]:
    q = repo(user_id).select("clients")
    if status:
        q = q.eq("status", status)
    r = q.order("last_activity_at", desc=True).execute()
    return [Client(**row) for row in r.data]


def get_client(user_id: str, client_id: str) -> Client | None:
    r = repo(user_id).select("clients").eq("id", client_id).limit(1).execute()
    return Client(**r.data[0]) if r.data else None


def insert_client(client: Client) -> Client:
    repo(client.user_id).insert("clients", _dump(client)).execute()
    return client


def update_client(user_id: str, client_id: str, patch: dict) -> Client | None:
    r = repo(user_id).update("clients", patch, client_id).execute()
    return Client(**r.data[0]) if r.data else None


def delete_client(user_id: str, client_id: str) -> bool:
    r = repo(user_id).delete("clients", client_id).execute()
    return bool(r.data)


# ---- Butler: engagements ---------------------------------------------------
def list_engagements(user_id: str, client_id: str | None = None) -> list[Engagement]:
    q = repo(user_id).select("engagements")
    if client_id:
        q = q.eq("client_id", client_id)
    r = q.order("created_at", desc=True).execute()
    return [Engagement(**row) for row in r.data]


def get_engagement(user_id: str, engagement_id: str) -> Engagement | None:
    r = repo(user_id).select("engagements").eq("id", engagement_id).limit(1).execute()
    return Engagement(**r.data[0]) if r.data else None


def insert_engagement(engagement: Engagement) -> Engagement:
    repo(engagement.user_id).insert("engagements", _dump(engagement)).execute()
    return engagement


def update_engagement(user_id: str, engagement_id: str, patch: dict) -> Engagement | None:
    r = repo(user_id).update("engagements", patch, engagement_id).execute()
    return Engagement(**r.data[0]) if r.data else None


# ---- Task ledger ------------------------------------------------------------
def list_tasks(
    user_id: str, *, client_id: str | None = None, engagement_id: str | None = None, status: str | None = None, statuses: list[str] | None = None
) -> list[Task]:
    q = repo(user_id).select("tasks")
    if client_id is not None:
        q = q.eq("client_id", client_id)
    if engagement_id is not None:
        q = q.eq("engagement_id", engagement_id)
    if status is not None:
        q = q.eq("status", status)
    if statuses:
        q = q.in_("status", list(statuses))
    r = q.order("created_at", desc=True).execute()
    return [Task(**row) for row in (r.data or [])]


def get_task(user_id: str, task_id: str) -> Task | None:
    r = repo(user_id).select("tasks").eq("id", task_id).limit(1).execute()
    return Task(**r.data[0]) if r.data else None


def find_task_by_source_ref(user_id: str, source_ref: str) -> Task | None:
    r = repo(user_id).select("tasks").eq("source_ref", source_ref).limit(1).execute()
    return Task(**r.data[0]) if r.data else None


def find_task_by_external_ref(user_id: str, external_ref: str) -> Task | None:
    r = repo(user_id).select("tasks").eq("external_ref", external_ref).limit(1).execute()
    return Task(**r.data[0]) if r.data else None


def insert_task(task: Task) -> Task:
    repo(task.user_id).insert("tasks", _dump(task)).execute()
    return task


def update_task(user_id: str, task_id: str, patch: dict) -> Task | None:
    r = repo(user_id).update("tasks", patch, task_id).execute()
    return Task(**r.data[0]) if r.data else None


def delete_task(user_id: str, task_id: str) -> bool:
    r = repo(user_id).delete("tasks", task_id).execute()
    return bool(r.data)


# ---- Story layer (children of tasks) ---------------------------------------
def list_stories(user_id: str, *, task_id: str | None = None, client_id: str | None = None, statuses: list[str] | None = None) -> list[Story]:
    q = repo(user_id).select("stories")
    if task_id is not None:
        q = q.eq("task_id", task_id)
    if client_id is not None:
        q = q.eq("client_id", client_id)
    if statuses:
        q = q.in_("status", list(statuses))
    r = q.order("created_at").execute()
    return [Story(**row) for row in (r.data or [])]


def get_story(user_id: str, story_id: str) -> Story | None:
    r = repo(user_id).select("stories").eq("id", story_id).limit(1).execute()
    return Story(**r.data[0]) if r.data else None


def insert_story(story: Story) -> Story:
    repo(story.user_id).insert("stories", _dump(story)).execute()
    return story


def update_story(user_id: str, story_id: str, patch: dict) -> Story | None:
    # Observations arrive as models when set from the service layer; JSONB needs plain dicts.
    if "observations" in patch:
        patch = {
            **patch,
            "observations": [o.model_dump(by_alias=False, mode="json") if hasattr(o, "model_dump") else o for o in (patch["observations"] or [])],
        }
    r = repo(user_id).update("stories", patch, story_id).execute()
    return Story(**r.data[0]) if r.data else None


def delete_story(user_id: str, story_id: str) -> bool:
    r = repo(user_id).delete("stories", story_id).execute()
    return bool(r.data)


def delete_stories_for_task(user_id: str, task_id: str) -> int:
    r = repo(user_id).raw_table("stories").delete().eq("task_id", task_id).execute()
    return len(r.data or [])


# ---- Butler: client notes --------------------------------------------------
def list_client_notes(user_id: str, client_id: str) -> list[ClientNote]:
    r = repo(user_id).select("client_notes").eq("client_id", client_id).order("created_at", desc=True).limit(50).execute()
    return [ClientNote(**row) for row in r.data]


def insert_client_note(note: ClientNote) -> ClientNote:
    repo(note.user_id).insert("client_notes", _dump(note)).execute()
    return note


# ---- Butler: quick captures ------------------------------------------------
def list_captures(user_id: str, requires_review: bool | None = None) -> list[QuickCapture]:
    q = repo(user_id).select("quick_captures")
    if requires_review is not None:
        q = q.eq("requires_review", requires_review)
    r = q.order("created_at", desc=True).execute()
    return [QuickCapture(**row) for row in r.data]


def get_capture(user_id: str, capture_id: str) -> QuickCapture | None:
    r = repo(user_id).select("quick_captures").eq("id", capture_id).limit(1).execute()
    return QuickCapture(**r.data[0]) if r.data else None


def insert_capture(capture: QuickCapture) -> QuickCapture:
    repo(capture.user_id).insert("quick_captures", _dump(capture)).execute()
    return capture


def update_capture(user_id: str, capture_id: str, patch: dict) -> QuickCapture | None:
    r = repo(user_id).update("quick_captures", patch, capture_id).execute()
    return QuickCapture(**r.data[0]) if r.data else None


# ---- Butler: proposals -----------------------------------------------------
def list_proposals(user_id: str) -> list[Proposal]:
    r = repo(user_id).select("proposals").order("created_at", desc=True).execute()
    return [Proposal(**row) for row in r.data]


def get_proposal(user_id: str, proposal_id: str) -> Proposal | None:
    r = repo(user_id).select("proposals").eq("id", proposal_id).limit(1).execute()
    return Proposal(**r.data[0]) if r.data else None


def insert_proposal(proposal: Proposal) -> Proposal:
    repo(proposal.user_id).insert("proposals", _dump(proposal)).execute()
    return proposal


def update_proposal(user_id: str, proposal_id: str, patch: dict) -> Proposal | None:
    r = repo(user_id).update("proposals", patch, proposal_id).execute()
    return Proposal(**r.data[0]) if r.data else None


# ---- Butler: retainers -----------------------------------------------------
def list_retainers(user_id: str, status: str | None = None) -> list[Retainer]:
    q = repo(user_id).select("retainers")
    if status:
        q = q.eq("status", status)
    r = q.order("created_at", desc=True).execute()
    return [Retainer(**row) for row in r.data]


def get_retainer(user_id: str, retainer_id: str) -> Retainer | None:
    r = repo(user_id).select("retainers").eq("id", retainer_id).limit(1).execute()
    return Retainer(**r.data[0]) if r.data else None


def insert_retainer(retainer: Retainer) -> Retainer:
    repo(retainer.user_id).insert("retainers", _dump(retainer)).execute()
    return retainer


def update_retainer(user_id: str, retainer_id: str, patch: dict) -> Retainer | None:
    r = repo(user_id).update("retainers", patch, retainer_id).execute()
    return Retainer(**r.data[0]) if r.data else None


# ---- Butler: butler memory (briefing continuity) ---------------------------
def get_butler_memory(user_id: str) -> dict:
    r = _sb.table("users").select("butler_memory").eq("id", user_id).limit(1).execute()
    return (r.data[0].get("butler_memory") or {}) if r.data else {}


def set_butler_memory(user_id: str, memory: dict) -> dict:
    _sb.table("users").update({"butler_memory": memory}).eq("id", user_id).execute()
    return memory


# ---- Client view cache (M3 PM agent fan-out) -------------------------------
def get_client_view(user_id: str, client_id: str) -> dict | None:
    r = repo(user_id).select("client_view_cache").eq("client_id", client_id).limit(1).execute()
    return r.data[0] if r.data else None


def upsert_client_view(user_id: str, client_id: str, view: dict, token_cost: dict, refreshed_at: str) -> dict:
    row = {"user_id": user_id, "client_id": client_id, "view": view, "token_cost": token_cost, "refreshed_at": refreshed_at}
    repo(user_id).raw_table("client_view_cache").upsert(row, on_conflict="user_id,client_id").execute()
    return row


def delete_client_view(user_id: str, client_id: str) -> bool:
    r = repo(user_id).raw_table("client_view_cache").delete().eq("client_id", client_id).execute()
    return bool(r.data)


# ---- Playbook (Agent Intelligence) -----------------------------------------
def upsert_playbook_entry(user_id: str, entry: dict) -> dict:
    from datetime import datetime, timezone
    import uuid

    now = datetime.now(timezone.utc).isoformat()
    category = entry.get("category", "")
    key = entry.get("key", "")
    client_id = entry.get("client_id")

    q = repo(user_id).select("business_playbook").eq("category", category).eq("key", key)
    if client_id is None:
        q = q.is_("client_id", "null")
    else:
        q = q.eq("client_id", client_id)
    existing_rows = q.limit(1).execute().data

    if existing_rows:
        existing = existing_rows[0]
        count = existing["observation_count"] + 1
        new_confidence = float(existing["confidence"])
        if new_confidence < 1.0:
            new_confidence = round(1 - (1 / (1 + 0.3 * count)), 4)
        patch = {
            "observation_count": count,
            "confidence": new_confidence,
            "last_observed_at": now,
        }
        if entry.get("summary"):
            patch["summary"] = entry["summary"]
        if entry.get("value"):
            patch["value"] = entry["value"]
        r = repo(user_id).raw_table("business_playbook").update(patch).eq("id", existing["id"]).execute()
        return r.data[0] if r.data else existing
    else:
        new_entry = {
            "id": entry.get("id") or str(uuid.uuid4()),
            "user_id": user_id,
            "category": category,
            "client_id": client_id,
            "key": key,
            "value": entry.get("value", {}),
            "summary": entry.get("summary"),
            "confidence": entry.get("confidence", 0.5),
            "source": entry.get("source", "observation"),
            "observation_count": 1,
            "first_observed_at": now,
            "last_observed_at": now,
            "expires_at": entry.get("expires_at"),
            "created_at": now,
        }
        insert_r = repo(user_id).insert("business_playbook", new_entry).execute()
        return insert_r.data[0] if insert_r.data else new_entry


def get_playbook_entries(
    user_id: str,
    category: str | None = None,
    client_id: str | None = None,
    min_confidence: float = 0.0,
    limit: int = 100,
) -> list[dict]:
    q = repo(user_id).select("business_playbook").gte("confidence", min_confidence)
    if category:
        q = q.eq("category", category)
    if client_id is not None:
        q = q.eq("client_id", client_id)
    r = q.order("confidence", desc=True).limit(limit).execute()
    return r.data or []


def get_playbook_corrections(user_id: str) -> list[dict]:
    r = repo(user_id).select("business_playbook").gte("confidence", 1.0).execute()
    return r.data or []


def get_playbook_for_client(user_id: str, client_id: str) -> list[dict]:
    r = repo(user_id).select("business_playbook").eq("client_id", client_id).order("confidence", desc=True).execute()
    return r.data or []


def update_playbook_entry(user_id: str, entry_id: str, patch: dict) -> dict | None:
    r = repo(user_id).raw_table("business_playbook").update(patch).eq("id", entry_id).execute()
    return r.data[0] if r.data else None


def delete_playbook_entry(user_id: str, entry_id: str) -> bool:
    r = repo(user_id).delete("business_playbook", entry_id).execute()
    return bool(r.data)


def decay_playbook_entries(user_id: str) -> int:
    from datetime import datetime, timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    r = repo(user_id).select("business_playbook").lt("confidence", 1.0).lt("last_observed_at", cutoff).execute()
    rows = r.data or []
    for row in rows:
        new_conf = max(0.0, round(float(row["confidence"]) - 0.1, 4))
        repo(user_id).raw_table("business_playbook").update({"confidence": new_conf}).eq("id", row["id"]).execute()
    return len(rows)


# ---- Stripe Connect --------------------------------------------------------


def upsert_stripe_connection(user_id: str, data: dict) -> dict:
    data["user_id"] = user_id
    r = repo(user_id).raw_table("stripe_connections").upsert(data, on_conflict="user_id").execute()
    return r.data[0] if r.data else data


def get_stripe_connection(user_id: str) -> dict | None:
    r = repo(user_id).select("stripe_connections").eq("connected", True).execute()
    return r.data[0] if r.data else None


def update_stripe_connection(user_id: str, updates: dict) -> dict:
    r = repo(user_id).raw_table("stripe_connections").update(updates).execute()
    return r.data[0] if r.data else updates


def delete_stripe_connection(user_id: str) -> None:
    repo(user_id).raw_table("stripe_connections").delete().execute()


# ---- Notion connection (task ledger mirror) --------------------------------
def upsert_notion_connection(user_id: str, data: dict) -> dict:
    data["user_id"] = user_id
    r = repo(user_id).raw_table("notion_connections").upsert(data, on_conflict="user_id").execute()
    return r.data[0] if r.data else data


def get_notion_connection(user_id: str) -> dict | None:
    r = repo(user_id).select("notion_connections").execute()
    return r.data[0] if r.data else None


def update_notion_connection(user_id: str, updates: dict) -> dict:
    r = repo(user_id).raw_table("notion_connections").update(updates).execute()
    return r.data[0] if r.data else updates


def delete_notion_connection(user_id: str) -> None:
    repo(user_id).raw_table("notion_connections").delete().execute()


# ---- Graph memory (kg_nodes / kg_edges) ------------------------------------
# Small per-user graphs (100s–1000s of rows) — the service loads all of a user's
# nodes/edges and traverses in Python, so the store stays a thin, backend-symmetric
# CRUD layer (no recursive CTEs, no OR-of-IN filters).


def upsert_kg_node(user_id: str, node: dict) -> dict:
    import uuid

    now = datetime.now(timezone.utc).isoformat()
    node_type = node.get("node_type", "")
    entity_id = node.get("entity_id")
    label = node.get("label", "")
    incoming_salience = float(node.get("salience", 0.5))

    q = repo(user_id).select("kg_nodes").eq("node_type", node_type)
    if entity_id is not None:
        q = q.eq("entity_id", entity_id)
    else:
        q = q.is_("entity_id", "null").eq("label", label)
    existing_rows = q.limit(1).execute().data

    if existing_rows:
        ex = existing_rows[0]
        salience = min(1.0, round(max(float(ex.get("salience", 0.5)), incoming_salience) + 0.02, 4))
        patch = {
            "label": label or ex.get("label"),
            "props": {**(ex.get("props") or {}), **(node.get("props") or {})},
            "salience": salience,
            "last_seen": now,
        }
        r = repo(user_id).raw_table("kg_nodes").update(patch).eq("id", ex["id"]).execute()
        return r.data[0] if r.data else {**ex, **patch}
    new_node = {
        "id": node.get("id") or str(uuid.uuid4()),
        "user_id": user_id,
        "node_type": node_type,
        "entity_id": entity_id,
        "label": label,
        "props": node.get("props", {}),
        "salience": incoming_salience,
        "first_seen": now,
        "last_seen": now,
        "created_at": now,
    }
    insert_r = repo(user_id).insert("kg_nodes", new_node).execute()
    return insert_r.data[0] if insert_r.data else new_node


def upsert_kg_edge(user_id: str, edge: dict) -> dict:
    import uuid

    now = datetime.now(timezone.utc).isoformat()
    src_id = edge.get("src_id")
    dst_id = edge.get("dst_id")
    rel = edge.get("rel", "")
    incoming_weight = float(edge.get("weight", 1))

    existing_rows = repo(user_id).select("kg_edges").eq("src_id", src_id).eq("dst_id", dst_id).eq("rel", rel).limit(1).execute().data
    if existing_rows:
        ex = existing_rows[0]
        patch = {
            "weight": max(float(ex.get("weight", 1)), incoming_weight),
            "props": {**(ex.get("props") or {}), **(edge.get("props") or {})},
            "last_seen": now,
        }
        r = repo(user_id).raw_table("kg_edges").update(patch).eq("id", ex["id"]).execute()
        return r.data[0] if r.data else {**ex, **patch}
    new_edge = {
        "id": edge.get("id") or str(uuid.uuid4()),
        "user_id": user_id,
        "src_id": src_id,
        "dst_id": dst_id,
        "rel": rel,
        "weight": incoming_weight,
        "props": edge.get("props", {}),
        "first_seen": now,
        "last_seen": now,
        "created_at": now,
    }
    insert_r = repo(user_id).insert("kg_edges", new_edge).execute()
    return insert_r.data[0] if insert_r.data else new_edge


def get_kg_nodes(user_id: str) -> list[dict]:
    r = repo(user_id).select("kg_nodes").execute()
    return r.data or []


def get_kg_edges(user_id: str) -> list[dict]:
    r = repo(user_id).select("kg_edges").execute()
    return r.data or []


def delete_kg_for_user(user_id: str) -> None:
    repo(user_id).raw_table("kg_edges").delete().execute()
    repo(user_id).raw_table("kg_nodes").delete().execute()


# ---- Semantic memory (agent_memory) ----------------------------------------
# Same small-per-user assumption as the graph: recall loads a user's candidate
# rows and scores in Python. Embeddings live in a JSONB column (no pgvector).


def upsert_agent_memory(user_id: str, row: dict) -> dict:
    import uuid

    now = datetime.now(timezone.utc).isoformat()
    kind = row.get("kind", "")
    ref_id = row.get("ref_id")

    if ref_id is not None:
        existing_rows = repo(user_id).select("agent_memory").eq("kind", kind).eq("ref_id", ref_id).limit(1).execute().data
        if existing_rows:
            ex = existing_rows[0]
            patch: dict = {
                "metadata": {**(ex.get("metadata") or {}), **(row.get("metadata") or {})},
                "updated_at": now,
            }
            if row.get("content"):
                patch["content"] = row["content"]
            if row.get("embedding") is not None:
                patch["embedding"] = row["embedding"]
            if row.get("client_id") is not None:
                patch["client_id"] = row["client_id"]
            if row.get("salience") is not None:
                patch["salience"] = float(row["salience"])
            if row.get("source") is not None:
                patch["source"] = row["source"]
            r = repo(user_id).raw_table("agent_memory").update(patch).eq("id", ex["id"]).execute()
            return r.data[0] if r.data else {**ex, **patch}

    new_row = {
        "id": row.get("id") or str(uuid.uuid4()),
        "user_id": user_id,
        "kind": kind,
        "client_id": row.get("client_id"),
        "ref_type": row.get("ref_type"),
        "ref_id": ref_id,
        "content": row.get("content", ""),
        "embedding": row.get("embedding"),
        "salience": float(row.get("salience", 0.5)),
        "source": row.get("source"),
        "metadata": row.get("metadata") or {},
        "created_at": now,
        "updated_at": now,
    }
    insert_r = repo(user_id).insert("agent_memory", new_row).execute()
    return insert_r.data[0] if insert_r.data else new_row


def get_agent_memory(user_id: str, *, client_id: str | None = None, kinds: list[str] | None = None, limit: int | None = None) -> list[dict]:
    q = repo(user_id).select("agent_memory")
    if client_id is not None:
        q = q.eq("client_id", client_id)
    if kinds:
        q = q.in_("kind", list(kinds))
    q = q.order("updated_at", desc=True)
    if limit:
        q = q.limit(limit)
    return q.execute().data or []


def delete_agent_memory_for_user(user_id: str) -> None:
    repo(user_id).raw_table("agent_memory").delete().execute()


def delete_agent_memory(user_id: str, *, kind: str | None = None, ref_id_prefix: str | None = None) -> int:
    """Delete a user's agent_memory rows, narrowed by kind and/or ref_id prefix.

    The prefix is matched as a literal: `%`/`_`/`\\` are escaped so the SQL LIKE
    trailing wildcard is the ONLY wildcard, keeping this equivalent to the mock
    backend's `str.startswith` for any prefix (Notion ids can't contain them, but
    the helper is generic)."""
    q = repo(user_id).raw_table("agent_memory").delete()
    if kind is not None:
        q = q.eq("kind", kind)
    if ref_id_prefix is not None:
        literal = ref_id_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        q = q.like("ref_id", f"{literal}%")
    return len(q.execute().data or [])
