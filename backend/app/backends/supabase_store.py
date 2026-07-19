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
    Task,
    Transaction,
    User,
)

# Supabase-backed data backend (KORA_DATA_BACKEND=supabase). Same function
# surface as memory_store, so nothing else in the app changes.
#
# Mapping notes: models are camelCase-aliased Pydantic but dump to snake_case
# (= DB columns). Two model fields have no column in the applied schema, so we
# tuck them into adjacent JSONB to stay lossless without extra DDL:
#   - AgentLog.cost_usd      -> output["_cost_usd"]
#   - Contract.provider_name -> terms["_provider_name"]

_sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)


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
    r = _sb.table("transactions").select("*").eq("user_id", user_id).order("date", desc=True).execute()
    return [Transaction(**row) for row in r.data]


def insert_transactions(rows: list[Transaction]) -> list[Transaction]:
    if not rows:
        return []
    user_id = rows[0].user_id
    existing = _sb.table("transactions").select("date,description,amount").eq("user_id", user_id).execute()
    seen = {(e["date"], e["description"], round(float(e["amount"]), 2)) for e in existing.data}
    new: list[Transaction] = []
    for row in rows:
        key = (row.date, row.description, round(float(row.amount), 2))
        if key not in seen:
            seen.add(key)
            new.append(row)
    if new:
        _sb.table("transactions").insert([_dump(t) for t in new]).execute()
    return new


def upsert_transactions(rows: list[Transaction]) -> list[Transaction]:
    if rows:
        _sb.table("transactions").upsert([_dump(t) for t in rows]).execute()
    return rows


def update_transaction(user_id: str, transaction_id: str, patch: dict) -> Transaction | None:
    r = _sb.table("transactions").update(patch).eq("id", transaction_id).eq("user_id", user_id).execute()
    return Transaction(**r.data[0]) if r.data else None


# ---- Invoices --------------------------------------------------------------
def list_invoices(user_id: str) -> list[Invoice]:
    r = _sb.table("invoices").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
    return [Invoice(**row) for row in r.data]


def get_invoice(user_id: str, invoice_id: str) -> Invoice | None:
    r = _sb.table("invoices").select("*").eq("id", invoice_id).eq("user_id", user_id).limit(1).execute()
    return Invoice(**r.data[0]) if r.data else None


def insert_invoice(invoice: Invoice) -> Invoice:
    _sb.table("invoices").insert(_dump(invoice)).execute()
    return invoice


def update_invoice(user_id: str, invoice_id: str, patch: dict) -> Invoice | None:
    r = _sb.table("invoices").update(patch).eq("id", invoice_id).eq("user_id", user_id).execute()
    return Invoice(**r.data[0]) if r.data else None


def update_invoice_pdf(user_id: str, invoice_id: str, pdf_path: str) -> Invoice | None:
    return update_invoice(user_id, invoice_id, {"pdf_path": pdf_path})


def update_invoice_email(user_id: str, invoice_id: str, message_id: str) -> Invoice | None:
    from datetime import datetime, timezone
    return update_invoice(user_id, invoice_id, {
        "email_message_id": message_id,
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "status": "sent",
    })


def next_invoice_number(user_id: str) -> str:
    year = datetime.now(timezone.utc).year
    r = (
        _sb.table("invoices")
        .select("id", count="exact")
        .eq("user_id", user_id)
        .gte("created_at", f"{year}-01-01")
        .execute()
    )
    return f"INV-{year}-{(r.count or 0) + 1:03d}"


# ---- Agent logs ------------------------------------------------------------
def list_agent_logs(user_id: str) -> list[AgentLog]:
    r = _sb.table("agent_logs").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
    return [_agent_from_row(row) for row in r.data]


def list_all_agent_logs() -> list[AgentLog]:
    r = _sb.table("agent_logs").select("*").order("created_at", desc=True).limit(1000).execute()
    return [_agent_from_row(row) for row in r.data]


def insert_agent_log(log: AgentLog) -> AgentLog:
    _sb.table("agent_logs").insert(_agent_to_row(log)).execute()
    return log


# ---- Alerts ----------------------------------------------------------------
def list_alerts(user_id: str) -> list[Alert]:
    r = _sb.table("alerts").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
    return [Alert(**row) for row in r.data]


def insert_alert(alert: Alert) -> Alert:
    _sb.table("alerts").insert(_dump(alert)).execute()
    return alert


def alert_fired_recently(user_id: str, type_: str, within_days: int = 7) -> bool:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=within_days)).isoformat()
    r = (
        _sb.table("alerts")
        .select("id")
        .eq("user_id", user_id)
        .eq("type", type_)
        .gte("created_at", cutoff)
        .limit(1)
        .execute()
    )
    return bool(r.data)


def mark_alert_read(user_id: str, alert_id: str) -> Alert | None:
    r = _sb.table("alerts").update({"read": True, "read_at": datetime.now(timezone.utc).isoformat()}).eq(
        "id", alert_id
    ).eq("user_id", user_id).execute()
    return Alert(**r.data[0]) if r.data else None


# ---- Contracts -------------------------------------------------------------
def list_contracts(user_id: str) -> list[Contract]:
    r = _sb.table("contracts").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
    return [_contract_from_row(row) for row in r.data]


def get_contract(user_id: str, contract_id: str) -> Contract | None:
    r = _sb.table("contracts").select("*").eq("id", contract_id).eq("user_id", user_id).limit(1).execute()
    return _contract_from_row(r.data[0]) if r.data else None


def insert_contract(contract: Contract) -> Contract:
    _sb.table("contracts").insert(_contract_to_row(contract)).execute()
    return contract


def update_contract(user_id: str, contract_id: str, patch: dict) -> Contract | None:
    r = _sb.table("contracts").update(patch).eq("id", contract_id).eq("user_id", user_id).execute()
    return _contract_from_row(r.data[0]) if r.data else None


# ---- Manager tasks (supervisor approval queue) -----------------------------
def list_manager_tasks(user_id: str, status: str | None = None) -> list[ManagerTask]:
    q = _sb.table("manager_tasks").select("*").eq("user_id", user_id)
    if status:
        q = q.eq("status", status)
    r = q.order("created_at", desc=True).execute()
    return [ManagerTask(**row) for row in r.data]


def get_manager_task(user_id: str, task_id: str) -> ManagerTask | None:
    r = _sb.table("manager_tasks").select("*").eq("id", task_id).eq("user_id", user_id).limit(1).execute()
    return ManagerTask(**r.data[0]) if r.data else None


def find_open_manager_task(user_id: str, kind: str, source_record_id: str | None) -> ManagerTask | None:
    q = _sb.table("manager_tasks").select("*").eq("user_id", user_id).eq("kind", kind).eq("status", "proposed")
    q = q.is_("source_record_id", "null") if source_record_id is None else q.eq("source_record_id", source_record_id)
    r = q.limit(1).execute()
    return ManagerTask(**r.data[0]) if r.data else None


def insert_manager_task(task: ManagerTask) -> ManagerTask:
    _sb.table("manager_tasks").insert(_dump(task)).execute()
    return task


def update_manager_task(user_id: str, task_id: str, patch: dict) -> ManagerTask | None:
    r = _sb.table("manager_tasks").update(patch).eq("id", task_id).eq("user_id", user_id).execute()
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
    q = _sb.table("clients").select("*").eq("user_id", user_id)
    if status:
        q = q.eq("status", status)
    r = q.order("last_activity_at", desc=True).execute()
    return [Client(**row) for row in r.data]


def get_client(user_id: str, client_id: str) -> Client | None:
    r = _sb.table("clients").select("*").eq("id", client_id).eq("user_id", user_id).limit(1).execute()
    return Client(**r.data[0]) if r.data else None


def insert_client(client: Client) -> Client:
    _sb.table("clients").insert(_dump(client)).execute()
    return client


def update_client(user_id: str, client_id: str, patch: dict) -> Client | None:
    r = _sb.table("clients").update(patch).eq("id", client_id).eq("user_id", user_id).execute()
    return Client(**r.data[0]) if r.data else None


def delete_client(user_id: str, client_id: str) -> bool:
    r = _sb.table("clients").delete().eq("id", client_id).eq("user_id", user_id).execute()
    return bool(r.data)


# ---- Butler: engagements ---------------------------------------------------
def list_engagements(user_id: str, client_id: str | None = None) -> list[Engagement]:
    q = _sb.table("engagements").select("*").eq("user_id", user_id)
    if client_id:
        q = q.eq("client_id", client_id)
    r = q.order("created_at", desc=True).execute()
    return [Engagement(**row) for row in r.data]


def get_engagement(user_id: str, engagement_id: str) -> Engagement | None:
    r = _sb.table("engagements").select("*").eq("id", engagement_id).eq("user_id", user_id).limit(1).execute()
    return Engagement(**r.data[0]) if r.data else None


def insert_engagement(engagement: Engagement) -> Engagement:
    _sb.table("engagements").insert(_dump(engagement)).execute()
    return engagement


def update_engagement(user_id: str, engagement_id: str, patch: dict) -> Engagement | None:
    r = _sb.table("engagements").update(patch).eq("id", engagement_id).eq("user_id", user_id).execute()
    return Engagement(**r.data[0]) if r.data else None


# ---- Task ledger ------------------------------------------------------------
def list_tasks(user_id: str, *, client_id: str | None = None,
               engagement_id: str | None = None, status: str | None = None,
               statuses: list[str] | None = None) -> list[Task]:
    q = _sb.table("tasks").select("*").eq("user_id", user_id)
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
    r = _sb.table("tasks").select("*").eq("id", task_id).eq("user_id", user_id).limit(1).execute()
    return Task(**r.data[0]) if r.data else None


def find_task_by_source_ref(user_id: str, source_ref: str) -> Task | None:
    r = (_sb.table("tasks").select("*").eq("user_id", user_id)
         .eq("source_ref", source_ref).limit(1).execute())
    return Task(**r.data[0]) if r.data else None


def find_task_by_external_ref(user_id: str, external_ref: str) -> Task | None:
    r = (_sb.table("tasks").select("*").eq("user_id", user_id)
         .eq("external_ref", external_ref).limit(1).execute())
    return Task(**r.data[0]) if r.data else None


def insert_task(task: Task) -> Task:
    _sb.table("tasks").insert(_dump(task)).execute()
    return task


def update_task(user_id: str, task_id: str, patch: dict) -> Task | None:
    r = _sb.table("tasks").update(patch).eq("id", task_id).eq("user_id", user_id).execute()
    return Task(**r.data[0]) if r.data else None


def delete_task(user_id: str, task_id: str) -> bool:
    r = _sb.table("tasks").delete().eq("id", task_id).eq("user_id", user_id).execute()
    return bool(r.data)


# ---- Butler: client notes --------------------------------------------------
def list_client_notes(user_id: str, client_id: str) -> list[ClientNote]:
    r = (_sb.table("client_notes").select("*").eq("user_id", user_id).eq("client_id", client_id)
         .order("created_at", desc=True).limit(50).execute())
    return [ClientNote(**row) for row in r.data]


def insert_client_note(note: ClientNote) -> ClientNote:
    _sb.table("client_notes").insert(_dump(note)).execute()
    return note


# ---- Butler: quick captures ------------------------------------------------
def list_captures(user_id: str, requires_review: bool | None = None) -> list[QuickCapture]:
    q = _sb.table("quick_captures").select("*").eq("user_id", user_id)
    if requires_review is not None:
        q = q.eq("requires_review", requires_review)
    r = q.order("created_at", desc=True).execute()
    return [QuickCapture(**row) for row in r.data]


def get_capture(user_id: str, capture_id: str) -> QuickCapture | None:
    r = _sb.table("quick_captures").select("*").eq("id", capture_id).eq("user_id", user_id).limit(1).execute()
    return QuickCapture(**r.data[0]) if r.data else None


def insert_capture(capture: QuickCapture) -> QuickCapture:
    _sb.table("quick_captures").insert(_dump(capture)).execute()
    return capture


def update_capture(user_id: str, capture_id: str, patch: dict) -> QuickCapture | None:
    r = _sb.table("quick_captures").update(patch).eq("id", capture_id).eq("user_id", user_id).execute()
    return QuickCapture(**r.data[0]) if r.data else None


# ---- Butler: proposals -----------------------------------------------------
def list_proposals(user_id: str) -> list[Proposal]:
    r = _sb.table("proposals").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
    return [Proposal(**row) for row in r.data]


def get_proposal(user_id: str, proposal_id: str) -> Proposal | None:
    r = _sb.table("proposals").select("*").eq("id", proposal_id).eq("user_id", user_id).limit(1).execute()
    return Proposal(**r.data[0]) if r.data else None


def insert_proposal(proposal: Proposal) -> Proposal:
    _sb.table("proposals").insert(_dump(proposal)).execute()
    return proposal


def update_proposal(user_id: str, proposal_id: str, patch: dict) -> Proposal | None:
    r = _sb.table("proposals").update(patch).eq("id", proposal_id).eq("user_id", user_id).execute()
    return Proposal(**r.data[0]) if r.data else None


# ---- Butler: retainers -----------------------------------------------------
def list_retainers(user_id: str, status: str | None = None) -> list[Retainer]:
    q = _sb.table("retainers").select("*").eq("user_id", user_id)
    if status:
        q = q.eq("status", status)
    r = q.order("created_at", desc=True).execute()
    return [Retainer(**row) for row in r.data]


def get_retainer(user_id: str, retainer_id: str) -> Retainer | None:
    r = _sb.table("retainers").select("*").eq("id", retainer_id).eq("user_id", user_id).limit(1).execute()
    return Retainer(**r.data[0]) if r.data else None


def insert_retainer(retainer: Retainer) -> Retainer:
    _sb.table("retainers").insert(_dump(retainer)).execute()
    return retainer


def update_retainer(user_id: str, retainer_id: str, patch: dict) -> Retainer | None:
    r = _sb.table("retainers").update(patch).eq("id", retainer_id).eq("user_id", user_id).execute()
    return Retainer(**r.data[0]) if r.data else None


# ---- Butler: butler memory (briefing continuity) ---------------------------
def get_butler_memory(user_id: str) -> dict:
    r = _sb.table("users").select("butler_memory").eq("id", user_id).limit(1).execute()
    return (r.data[0].get("butler_memory") or {}) if r.data else {}


def set_butler_memory(user_id: str, memory: dict) -> dict:
    _sb.table("users").update({"butler_memory": memory}).eq("id", user_id).execute()
    return memory


# ---- Playbook (Agent Intelligence) -----------------------------------------
def upsert_playbook_entry(user_id: str, entry: dict) -> dict:
    from datetime import datetime, timezone
    import uuid

    now = datetime.now(timezone.utc).isoformat()
    category = entry.get("category", "")
    key = entry.get("key", "")
    client_id = entry.get("client_id")

    # Fetch existing to compute confidence growth in Python
    q = (
        _sb.table("business_playbook")
        .select("*")
        .eq("user_id", user_id)
        .eq("category", category)
        .eq("key", key)
    )
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
        r = _sb.table("business_playbook").update(patch).eq("id", existing["id"]).execute()
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
        r = _sb.table("business_playbook").insert(new_entry).execute()
        return r.data[0] if r.data else new_entry


def get_playbook_entries(
    user_id: str,
    category: str | None = None,
    client_id: str | None = None,
    min_confidence: float = 0.0,
    limit: int = 100,
) -> list[dict]:
    q = (
        _sb.table("business_playbook")
        .select("*")
        .eq("user_id", user_id)
        .gte("confidence", min_confidence)
    )
    if category:
        q = q.eq("category", category)
    if client_id is not None:
        q = q.eq("client_id", client_id)
    r = q.order("confidence", desc=True).limit(limit).execute()
    return r.data or []


def get_playbook_corrections(user_id: str) -> list[dict]:
    r = (
        _sb.table("business_playbook")
        .select("*")
        .eq("user_id", user_id)
        .gte("confidence", 1.0)
        .execute()
    )
    return r.data or []


def get_playbook_for_client(user_id: str, client_id: str) -> list[dict]:
    r = (
        _sb.table("business_playbook")
        .select("*")
        .eq("user_id", user_id)
        .eq("client_id", client_id)
        .order("confidence", desc=True)
        .execute()
    )
    return r.data or []


def update_playbook_entry(user_id: str, entry_id: str, patch: dict) -> dict | None:
    r = (
        _sb.table("business_playbook")
        .update(patch)
        .eq("id", entry_id)
        .eq("user_id", user_id)
        .execute()
    )
    return r.data[0] if r.data else None


def delete_playbook_entry(user_id: str, entry_id: str) -> bool:
    r = (
        _sb.table("business_playbook")
        .delete()
        .eq("id", entry_id)
        .eq("user_id", user_id)
        .execute()
    )
    return bool(r.data)


def decay_playbook_entries(user_id: str) -> int:
    from datetime import datetime, timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    r = (
        _sb.table("business_playbook")
        .select("id, confidence")
        .eq("user_id", user_id)
        .lt("confidence", 1.0)
        .lt("last_observed_at", cutoff)
        .execute()
    )
    rows = r.data or []
    for row in rows:
        new_conf = max(0.0, round(float(row["confidence"]) - 0.1, 4))
        _sb.table("business_playbook").update({"confidence": new_conf}).eq("id", row["id"]).execute()
    return len(rows)


# ---- Stripe Connect --------------------------------------------------------

def upsert_stripe_connection(user_id: str, data: dict) -> dict:
    data["user_id"] = user_id
    r = _sb.table("stripe_connections").upsert(data, on_conflict="user_id").execute()
    return r.data[0] if r.data else data


def get_stripe_connection(user_id: str) -> dict | None:
    r = _sb.table("stripe_connections").select("*").eq("user_id", user_id).eq("connected", True).execute()
    return r.data[0] if r.data else None


def update_stripe_connection(user_id: str, updates: dict) -> dict:
    r = _sb.table("stripe_connections").update(updates).eq("user_id", user_id).execute()
    return r.data[0] if r.data else updates


def delete_stripe_connection(user_id: str) -> None:
    _sb.table("stripe_connections").delete().eq("user_id", user_id).execute()


# ---- Notion connection (task ledger mirror) --------------------------------
def upsert_notion_connection(user_id: str, data: dict) -> dict:
    data["user_id"] = user_id
    r = _sb.table("notion_connections").upsert(data, on_conflict="user_id").execute()
    return r.data[0] if r.data else data


def get_notion_connection(user_id: str) -> dict | None:
    r = _sb.table("notion_connections").select("*").eq("user_id", user_id).execute()
    return r.data[0] if r.data else None


def update_notion_connection(user_id: str, updates: dict) -> dict:
    r = _sb.table("notion_connections").update(updates).eq("user_id", user_id).execute()
    return r.data[0] if r.data else updates


def delete_notion_connection(user_id: str) -> None:
    _sb.table("notion_connections").delete().eq("user_id", user_id).execute()


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

    q = _sb.table("kg_nodes").select("*").eq("user_id", user_id).eq("node_type", node_type)
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
        r = _sb.table("kg_nodes").update(patch).eq("id", ex["id"]).execute()
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
    r = _sb.table("kg_nodes").insert(new_node).execute()
    return r.data[0] if r.data else new_node


def upsert_kg_edge(user_id: str, edge: dict) -> dict:
    import uuid
    now = datetime.now(timezone.utc).isoformat()
    src_id = edge.get("src_id")
    dst_id = edge.get("dst_id")
    rel = edge.get("rel", "")
    incoming_weight = float(edge.get("weight", 1))

    existing_rows = (
        _sb.table("kg_edges").select("*")
        .eq("user_id", user_id).eq("src_id", src_id).eq("dst_id", dst_id).eq("rel", rel)
        .limit(1).execute().data
    )
    if existing_rows:
        ex = existing_rows[0]
        patch = {
            "weight": max(float(ex.get("weight", 1)), incoming_weight),  # max → idempotent re-sync
            "props": {**(ex.get("props") or {}), **(edge.get("props") or {})},
            "last_seen": now,
        }
        r = _sb.table("kg_edges").update(patch).eq("id", ex["id"]).execute()
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
    r = _sb.table("kg_edges").insert(new_edge).execute()
    return r.data[0] if r.data else new_edge


def get_kg_nodes(user_id: str) -> list[dict]:
    r = _sb.table("kg_nodes").select("*").eq("user_id", user_id).execute()
    return r.data or []


def get_kg_edges(user_id: str) -> list[dict]:
    r = _sb.table("kg_edges").select("*").eq("user_id", user_id).execute()
    return r.data or []


def delete_kg_for_user(user_id: str) -> None:
    # Edges first (FK to nodes), then nodes.
    _sb.table("kg_edges").delete().eq("user_id", user_id).execute()
    _sb.table("kg_nodes").delete().eq("user_id", user_id).execute()


# ---- Semantic memory (agent_memory) ----------------------------------------
# Same small-per-user assumption as the graph: recall loads a user's candidate
# rows and scores in Python. Embeddings live in a JSONB column (no pgvector).

def upsert_agent_memory(user_id: str, row: dict) -> dict:
    import uuid
    now = datetime.now(timezone.utc).isoformat()
    kind = row.get("kind", "")
    ref_id = row.get("ref_id")

    if ref_id is not None:
        existing_rows = (
            _sb.table("agent_memory").select("*")
            .eq("user_id", user_id).eq("kind", kind).eq("ref_id", ref_id)
            .limit(1).execute().data
        )
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
            r = _sb.table("agent_memory").update(patch).eq("id", ex["id"]).execute()
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
    r = _sb.table("agent_memory").insert(new_row).execute()
    return r.data[0] if r.data else new_row


def get_agent_memory(user_id: str, *, client_id: str | None = None,
                     kinds: list[str] | None = None, limit: int | None = None) -> list[dict]:
    q = _sb.table("agent_memory").select("*").eq("user_id", user_id)
    if client_id is not None:
        q = q.eq("client_id", client_id)
    if kinds:
        q = q.in_("kind", list(kinds))
    q = q.order("updated_at", desc=True)
    if limit:
        q = q.limit(limit)
    return q.execute().data or []


def delete_agent_memory_for_user(user_id: str) -> None:
    _sb.table("agent_memory").delete().eq("user_id", user_id).execute()
