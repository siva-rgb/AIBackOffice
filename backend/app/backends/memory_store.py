from __future__ import annotations

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
    Transaction,
    User,
)
from ..seed import build_seed

# In-memory data backend (KORA_DATA_BACKEND=mock). A module-level singleton
# survives within a single process. Same function surface as supabase_store.

_seed = build_seed()
_users: list[User] = _seed["users"]
_transactions: list[Transaction] = _seed["transactions"]
_invoices: list[Invoice] = _seed["invoices"]
_agent_logs: list[AgentLog] = _seed["agent_logs"]
_alerts: list[Alert] = _seed["alerts"]
_contracts: list[Contract] = _seed["contracts"]
_manager_tasks: list[ManagerTask] = []
_manager_memory: dict[str, dict] = {}
# Butler tables
_clients: list[Client] = _seed.get("clients", [])
_engagements: list[Engagement] = _seed.get("engagements", [])
_client_notes: list[ClientNote] = _seed.get("client_notes", [])
_captures: list[QuickCapture] = []
_proposals: list[Proposal] = _seed.get("proposals", [])
_retainers: list[Retainer] = _seed.get("retainers", [])
_butler_memory: dict[str, dict] = {}
# Playbook tables (keyed by user_id → list of entry dicts)
_playbook: dict[str, list[dict]] = {
    "demo-user": [
        {
            "id": "pb-1",
            "user_id": "demo-user",
            "category": "correction",
            "client_id": None,
            "key": "category_override_adobe systems",
            "value": {"description_pattern": "adobe systems", "old_category": "other_expense",
                      "new_category": "software_subscriptions"},
            "summary": '"adobe systems" → software_subscriptions (corrected from other_expense)',
            "confidence": 1.0,
            "source": "correction",
            "observation_count": 1,
            "first_observed_at": "2026-06-01T10:00:00Z",
            "last_observed_at": "2026-06-01T10:00:00Z",
            "expires_at": None,
            "created_at": "2026-06-01T10:00:00Z",
        },
        {
            "id": "pb-2",
            "user_id": "demo-user",
            "category": "user_preference",
            "client_id": None,
            "key": "email_style",
            "value": {"tone": "direct", "length_preference": "shorter"},
            "summary": "User prefers direct, shorter emails",
            "confidence": 0.72,
            "source": "observation",
            "observation_count": 4,
            "first_observed_at": "2026-06-02T08:00:00Z",
            "last_observed_at": "2026-06-15T09:00:00Z",
            "expires_at": None,
            "created_at": "2026-06-02T08:00:00Z",
        },
        {
            "id": "pb-3",
            "user_id": "demo-user",
            "category": "client_intelligence",
            "client_id": None,
            "key": "payment_reliability",
            "value": {"reliability": "slow_but_pays", "paid_percentage": 85, "total_invoices": 7},
            "summary": "Payment reliability: slow but pays (85% on time, 7 invoices)",
            "confidence": 0.82,
            "source": "pattern_detection",
            "observation_count": 7,
            "first_observed_at": "2026-06-05T07:00:00Z",
            "last_observed_at": "2026-06-15T07:00:00Z",
            "expires_at": None,
            "created_at": "2026-06-05T07:00:00Z",
        },
        {
            "id": "pb-4",
            "user_id": "demo-user",
            "category": "business_rule",
            "client_id": None,
            "key": "skip_send_followup",
            "value": {"kind": "send_followup", "reason": "repeatedly dismissed day-3 follow-ups"},
            "summary": "User consistently dismisses day-3 invoice follow-ups — consider skipping",
            "confidence": 0.71,
            "source": "observation",
            "observation_count": 5,
            "first_observed_at": "2026-06-03T09:00:00Z",
            "last_observed_at": "2026-06-14T09:00:00Z",
            "expires_at": None,
            "created_at": "2026-06-03T09:00:00Z",
        },
    ]
}


# --- Users ------------------------------------------------------------------
def get_user(user_id: str) -> User | None:
    return next((u for u in _users if u.id == user_id), None)


def get_user_by_email(email: str) -> User | None:
    return next((u for u in _users if u.email == email), None)


def verify_token(token: str) -> User | None:
    # No real JWTs in mock mode.
    return None


def get_user_by_stripe_customer(customer_id: str) -> User | None:
    return next((u for u in _users if u.stripe_customer_id == customer_id), None)


def update_user(user_id: str, patch: dict) -> User | None:
    u = get_user(user_id)
    if not u:
        return None
    for k, v in patch.items():
        setattr(u, k, v)
    return u


# --- Transactions -----------------------------------------------------------
def list_transactions(user_id: str) -> list[Transaction]:
    rows = [t for t in _transactions if t.user_id == user_id]
    return sorted(rows, key=lambda t: t.date, reverse=True)


def insert_transactions(rows: list[Transaction]) -> list[Transaction]:
    inserted: list[Transaction] = []
    for row in rows:
        dupe = any(
            t.user_id == row.user_id
            and t.date == row.date
            and t.description == row.description
            and t.amount == row.amount
            for t in _transactions
        )
        if not dupe:
            _transactions.append(row)
            inserted.append(row)
    return inserted


def upsert_transactions(rows: list[Transaction]) -> list[Transaction]:
    # In memory the objects are already live in _transactions, so this is a
    # no-op that keeps the same surface as the Supabase backend.
    return rows


def update_transaction(user_id: str, transaction_id: str, patch: dict) -> Transaction | None:
    txn = next((t for t in _transactions if t.id == transaction_id and t.user_id == user_id), None)
    if not txn:
        return None
    for k, v in patch.items():
        setattr(txn, k, v)
    return txn


# --- Invoices ---------------------------------------------------------------
def list_invoices(user_id: str) -> list[Invoice]:
    rows = [i for i in _invoices if i.user_id == user_id]
    return sorted(rows, key=lambda i: i.created_at, reverse=True)


def get_invoice(user_id: str, invoice_id: str) -> Invoice | None:
    return next((i for i in _invoices if i.id == invoice_id and i.user_id == user_id), None)


def insert_invoice(invoice: Invoice) -> Invoice:
    _invoices.append(invoice)
    return invoice


def update_invoice(user_id: str, invoice_id: str, patch: dict) -> Invoice | None:
    inv = get_invoice(user_id, invoice_id)
    if not inv:
        return None
    for k, v in patch.items():
        setattr(inv, k, v)
    return inv


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
    from datetime import datetime, timezone

    year = datetime.now(timezone.utc).year
    count = sum(
        1 for i in _invoices if i.user_id == user_id and i.created_at[:4] == str(year)
    )
    return f"INV-{year}-{count + 1:03d}"


# --- Agent logs -------------------------------------------------------------
def list_agent_logs(user_id: str) -> list[AgentLog]:
    rows = [l for l in _agent_logs if l.user_id == user_id]
    return sorted(rows, key=lambda l: l.created_at, reverse=True)


def list_all_agent_logs() -> list[AgentLog]:
    return sorted(_agent_logs, key=lambda l: l.created_at, reverse=True)


def insert_agent_log(log: AgentLog) -> AgentLog:
    _agent_logs.append(log)
    return log


# --- Alerts -----------------------------------------------------------------
def list_alerts(user_id: str) -> list[Alert]:
    rows = [a for a in _alerts if a.user_id == user_id]
    return sorted(rows, key=lambda a: a.created_at, reverse=True)


def insert_alert(alert: Alert) -> Alert:
    _alerts.append(alert)
    return alert


def alert_fired_recently(user_id: str, type_: str, within_days: int = 7) -> bool:
    from datetime import datetime, timedelta, timezone

    cutoff = datetime.now(timezone.utc) - timedelta(days=within_days)
    for a in _alerts:
        if a.user_id == user_id and a.type == type_:
            try:
                if datetime.fromisoformat(a.created_at) >= cutoff:
                    return True
            except ValueError:
                continue
    return False


def mark_alert_read(user_id: str, alert_id: str) -> Alert | None:
    alert = next((a for a in _alerts if a.id == alert_id and a.user_id == user_id), None)
    if alert:
        alert.read = True
    return alert


# --- Contracts --------------------------------------------------------------
def list_contracts(user_id: str) -> list[Contract]:
    rows = [c for c in _contracts if c.user_id == user_id]
    return sorted(rows, key=lambda c: c.created_at, reverse=True)


def get_contract(user_id: str, contract_id: str) -> Contract | None:
    return next((c for c in _contracts if c.id == contract_id and c.user_id == user_id), None)


def insert_contract(contract: Contract) -> Contract:
    _contracts.append(contract)
    return contract


def update_contract(user_id: str, contract_id: str, patch: dict) -> Contract | None:
    c = get_contract(user_id, contract_id)
    if not c:
        return None
    for k, v in patch.items():
        setattr(c, k, v)
    return c


# --- Manager tasks (supervisor approval queue) ------------------------------
def list_manager_tasks(user_id: str, status: str | None = None) -> list[ManagerTask]:
    rows = [t for t in _manager_tasks if t.user_id == user_id and (status is None or t.status == status)]
    return sorted(rows, key=lambda t: t.created_at, reverse=True)


def get_manager_task(user_id: str, task_id: str) -> ManagerTask | None:
    return next((t for t in _manager_tasks if t.id == task_id and t.user_id == user_id), None)


def find_open_manager_task(user_id: str, kind: str, source_record_id: str | None) -> ManagerTask | None:
    return next(
        (t for t in _manager_tasks
         if t.user_id == user_id and t.kind == kind
         and t.source_record_id == source_record_id and t.status == "proposed"),
        None,
    )


def insert_manager_task(task: ManagerTask) -> ManagerTask:
    _manager_tasks.append(task)
    return task


def update_manager_task(user_id: str, task_id: str, patch: dict) -> ManagerTask | None:
    t = get_manager_task(user_id, task_id)
    if not t:
        return None
    for k, v in patch.items():
        setattr(t, k, v)
    return t


# --- Manager memory (supervisor continuity) ---------------------------------
def get_manager_memory(user_id: str) -> dict:
    return dict(_manager_memory.get(user_id, {}))


def set_manager_memory(user_id: str, memory: dict) -> dict:
    _manager_memory[user_id] = memory
    return memory


# --- Butler: clients --------------------------------------------------------
def list_clients(user_id: str, status: str | None = None) -> list[Client]:
    rows = [c for c in _clients if c.user_id == user_id and (status is None or c.status == status)]
    return sorted(rows, key=lambda c: c.last_activity_at or c.created_at, reverse=True)


def get_client(user_id: str, client_id: str) -> Client | None:
    return next((c for c in _clients if c.id == client_id and c.user_id == user_id), None)


def insert_client(client: Client) -> Client:
    _clients.append(client)
    return client


def update_client(user_id: str, client_id: str, patch: dict) -> Client | None:
    c = get_client(user_id, client_id)
    if not c:
        return None
    for k, v in patch.items():
        setattr(c, k, v)
    return c


def delete_client(user_id: str, client_id: str) -> bool:
    c = get_client(user_id, client_id)
    if not c:
        return False
    _clients.remove(c)
    # Postgres cascades the cached view via FK; the mock must match.
    _client_views.pop((user_id, client_id), None)
    return True


# --- Butler: engagements ----------------------------------------------------
def list_engagements(user_id: str, client_id: str | None = None) -> list[Engagement]:
    rows = [e for e in _engagements if e.user_id == user_id and (client_id is None or e.client_id == client_id)]
    return sorted(rows, key=lambda e: e.created_at, reverse=True)


def get_engagement(user_id: str, engagement_id: str) -> Engagement | None:
    return next((e for e in _engagements if e.id == engagement_id and e.user_id == user_id), None)


def insert_engagement(engagement: Engagement) -> Engagement:
    _engagements.append(engagement)
    return engagement


def update_engagement(user_id: str, engagement_id: str, patch: dict) -> Engagement | None:
    e = get_engagement(user_id, engagement_id)
    if not e:
        return None
    for k, v in patch.items():
        setattr(e, k, v)
    return e


# --- Task ledger -------------------------------------------------------------
_tasks: list = []


def list_tasks(user_id: str, *, client_id: str | None = None,
               engagement_id: str | None = None, status: str | None = None,
               statuses: list[str] | None = None) -> list:
    rows = [t for t in _tasks if t.user_id == user_id]
    if client_id is not None:
        rows = [t for t in rows if t.client_id == client_id]
    if engagement_id is not None:
        rows = [t for t in rows if t.engagement_id == engagement_id]
    if status is not None:
        rows = [t for t in rows if t.status == status]
    if statuses:
        rows = [t for t in rows if t.status in set(statuses)]
    return sorted(rows, key=lambda t: t.created_at, reverse=True)


def get_task(user_id: str, task_id: str):
    return next((t for t in _tasks if t.id == task_id and t.user_id == user_id), None)


def find_task_by_source_ref(user_id: str, source_ref: str):
    return next((t for t in _tasks if t.user_id == user_id and t.source_ref == source_ref), None)


def find_task_by_external_ref(user_id: str, external_ref: str):
    return next((t for t in _tasks if t.user_id == user_id and t.external_ref == external_ref), None)


def insert_task(task):
    _tasks.append(task)
    return task


def update_task(user_id: str, task_id: str, patch: dict):
    t = get_task(user_id, task_id)
    if not t:
        return None
    for k, v in patch.items():
        setattr(t, k, v)
    return t


def delete_task(user_id: str, task_id: str) -> bool:
    t = get_task(user_id, task_id)
    if not t:
        return False
    _tasks.remove(t)
    # Cascade to stories — Postgres does this via ON DELETE CASCADE, so the mock
    # backend must too or the two backends diverge and orphan stories here only.
    delete_stories_for_task(user_id, task_id)
    return True


# --- Story layer (children of tasks) ----------------------------------------
_stories: list = []


def list_stories(user_id: str, *, task_id: str | None = None,
                 client_id: str | None = None, statuses: list[str] | None = None) -> list:
    rows = [s for s in _stories if s.user_id == user_id]
    if task_id is not None:
        rows = [s for s in rows if s.task_id == task_id]
    if client_id is not None:
        rows = [s for s in rows if s.client_id == client_id]
    if statuses:
        allowed = set(statuses)
        rows = [s for s in rows if s.status in allowed]
    return sorted(rows, key=lambda s: s.created_at)


def get_story(user_id: str, story_id: str):
    return next((s for s in _stories if s.id == story_id and s.user_id == user_id), None)


def insert_story(story):
    _stories.append(story)
    return story


def update_story(user_id: str, story_id: str, patch: dict):
    s = get_story(user_id, story_id)
    if not s:
        return None
    for k, v in patch.items():
        setattr(s, k, v)
    return s


def delete_story(user_id: str, story_id: str) -> bool:
    s = get_story(user_id, story_id)
    if not s:
        return False
    _stories.remove(s)
    return True


def delete_stories_for_task(user_id: str, task_id: str) -> int:
    doomed = [s for s in _stories if s.user_id == user_id and s.task_id == task_id]
    for s in doomed:
        _stories.remove(s)
    return len(doomed)


# --- Butler: client notes ---------------------------------------------------
def list_client_notes(user_id: str, client_id: str) -> list[ClientNote]:
    rows = [n for n in _client_notes if n.user_id == user_id and n.client_id == client_id]
    return sorted(rows, key=lambda n: n.created_at, reverse=True)


def insert_client_note(note: ClientNote) -> ClientNote:
    _client_notes.append(note)
    return note


# --- Butler: quick captures -------------------------------------------------
def list_captures(user_id: str, requires_review: bool | None = None) -> list[QuickCapture]:
    rows = [c for c in _captures if c.user_id == user_id
            and (requires_review is None or c.requires_review == requires_review)]
    return sorted(rows, key=lambda c: c.created_at, reverse=True)


def get_capture(user_id: str, capture_id: str) -> QuickCapture | None:
    return next((c for c in _captures if c.id == capture_id and c.user_id == user_id), None)


def insert_capture(capture: QuickCapture) -> QuickCapture:
    _captures.append(capture)
    return capture


def update_capture(user_id: str, capture_id: str, patch: dict) -> QuickCapture | None:
    c = get_capture(user_id, capture_id)
    if not c:
        return None
    for k, v in patch.items():
        setattr(c, k, v)
    return c


# --- Butler: proposals ------------------------------------------------------
def list_proposals(user_id: str) -> list[Proposal]:
    rows = [p for p in _proposals if p.user_id == user_id]
    return sorted(rows, key=lambda p: p.created_at, reverse=True)


def get_proposal(user_id: str, proposal_id: str) -> Proposal | None:
    return next((p for p in _proposals if p.id == proposal_id and p.user_id == user_id), None)


def insert_proposal(proposal: Proposal) -> Proposal:
    _proposals.append(proposal)
    return proposal


def update_proposal(user_id: str, proposal_id: str, patch: dict) -> Proposal | None:
    p = get_proposal(user_id, proposal_id)
    if not p:
        return None
    for k, v in patch.items():
        setattr(p, k, v)
    return p


# --- Butler: retainers ------------------------------------------------------
def list_retainers(user_id: str, status: str | None = None) -> list[Retainer]:
    rows = [r for r in _retainers if r.user_id == user_id and (status is None or r.status == status)]
    return sorted(rows, key=lambda r: r.created_at, reverse=True)


def get_retainer(user_id: str, retainer_id: str) -> Retainer | None:
    return next((r for r in _retainers if r.id == retainer_id and r.user_id == user_id), None)


def insert_retainer(retainer: Retainer) -> Retainer:
    _retainers.append(retainer)
    return retainer


def update_retainer(user_id: str, retainer_id: str, patch: dict) -> Retainer | None:
    r = get_retainer(user_id, retainer_id)
    if not r:
        return None
    for k, v in patch.items():
        setattr(r, k, v)
    return r


# --- Butler: butler memory (briefing continuity) ----------------------------
def get_butler_memory(user_id: str) -> dict:
    return dict(_butler_memory.get(user_id, {}))


def set_butler_memory(user_id: str, memory: dict) -> dict:
    _butler_memory[user_id] = memory
    return memory


# --- Client view cache (M3 PM agent fan-out) --------------------------------
_client_views: dict[tuple[str, str], dict] = {}


def get_client_view(user_id: str, client_id: str) -> dict | None:
    row = _client_views.get((user_id, client_id))
    return dict(row) if row else None


def upsert_client_view(user_id: str, client_id: str, view: dict,
                       token_cost: dict, refreshed_at: str) -> dict:
    row = {"user_id": user_id, "client_id": client_id, "view": view,
           "token_cost": token_cost, "refreshed_at": refreshed_at}
    _client_views[(user_id, client_id)] = row
    return dict(row)


def delete_client_view(user_id: str, client_id: str) -> bool:
    return _client_views.pop((user_id, client_id), None) is not None


# --- Playbook (Agent Intelligence) ------------------------------------------
def upsert_playbook_entry(user_id: str, entry: dict) -> dict:
    from datetime import datetime, timezone
    import uuid

    entries = _playbook.setdefault(user_id, [])
    category = entry.get("category", "")
    key = entry.get("key", "")
    client_id = entry.get("client_id")
    now = datetime.now(timezone.utc).isoformat()

    existing = next(
        (e for e in entries
         if e["category"] == category and e["key"] == key and e["client_id"] == client_id),
        None,
    )
    if existing:
        count = existing["observation_count"] + 1
        existing["observation_count"] = count
        # Don't decay corrections (confidence 1.0 stays 1.0)
        if existing["confidence"] < 1.0:
            existing["confidence"] = round(1 - (1 / (1 + 0.3 * count)), 4)
        existing["last_observed_at"] = now
        if entry.get("summary"):
            existing["summary"] = entry["summary"]
        if entry.get("value"):
            existing["value"] = entry["value"]
        return existing
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
        entries.append(new_entry)
        return new_entry


def get_playbook_entries(
    user_id: str,
    category: str | None = None,
    client_id: str | None = None,
    min_confidence: float = 0.0,
    limit: int = 100,
) -> list[dict]:
    entries = _playbook.get(user_id, [])
    filtered = [
        e for e in entries
        if (category is None or e["category"] == category)
        and (client_id is None or e["client_id"] == client_id)
        and e.get("confidence", 0) >= min_confidence
    ]
    filtered.sort(key=lambda e: e.get("confidence", 0), reverse=True)
    return filtered[:limit]


def get_playbook_corrections(user_id: str) -> list[dict]:
    return [e for e in _playbook.get(user_id, []) if e.get("confidence", 0) >= 1.0]


def get_playbook_for_client(user_id: str, client_id: str) -> list[dict]:
    return [e for e in _playbook.get(user_id, []) if e.get("client_id") == client_id]


def update_playbook_entry(user_id: str, entry_id: str, patch: dict) -> dict | None:
    for e in _playbook.get(user_id, []):
        if e["id"] == entry_id:
            for k, v in patch.items():
                e[k] = v
            return e
    return None


def delete_playbook_entry(user_id: str, entry_id: str) -> bool:
    entries = _playbook.get(user_id, [])
    for e in entries:
        if e["id"] == entry_id:
            entries.remove(e)
            return True
    return False


def decay_playbook_entries(user_id: str) -> int:
    from datetime import datetime, timedelta, timezone

    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    decayed = 0
    for e in _playbook.get(user_id, []):
        if e.get("confidence", 0) >= 1.0:
            continue
        last_seen = e.get("last_observed_at")
        if last_seen:
            try:
                dt = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
                if dt < cutoff:
                    e["confidence"] = max(0.0, round(e.get("confidence", 0) - 0.1, 4))
                    decayed += 1
            except Exception:
                pass
    return decayed


# ---- Stripe Connect --------------------------------------------------------

_stripe_connections: dict[str, dict] = {}


# ---- Graph memory (kg_nodes / kg_edges) ------------------------------------
_kg_nodes: dict[str, list[dict]] = {}   # user_id -> nodes
_kg_edges: dict[str, list[dict]] = {}   # user_id -> edges


def upsert_kg_node(user_id: str, node: dict) -> dict:
    from datetime import datetime, timezone
    import uuid
    now = datetime.now(timezone.utc).isoformat()
    nodes = _kg_nodes.setdefault(user_id, [])
    node_type = node.get("node_type", "")
    entity_id = node.get("entity_id")
    label = node.get("label", "")
    incoming_salience = float(node.get("salience", 0.5))

    if entity_id is not None:
        existing = next((n for n in nodes if n["node_type"] == node_type and n.get("entity_id") == entity_id), None)
    else:
        existing = next((n for n in nodes if n["node_type"] == node_type and n.get("entity_id") is None and n["label"] == label), None)

    if existing:
        existing["label"] = label or existing["label"]
        existing["props"] = {**(existing.get("props") or {}), **(node.get("props") or {})}
        existing["salience"] = min(1.0, round(max(float(existing.get("salience", 0.5)), incoming_salience) + 0.02, 4))
        existing["last_seen"] = now
        return existing
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
    nodes.append(new_node)
    return new_node


def upsert_kg_edge(user_id: str, edge: dict) -> dict:
    from datetime import datetime, timezone
    import uuid
    now = datetime.now(timezone.utc).isoformat()
    edges = _kg_edges.setdefault(user_id, [])
    src_id, dst_id, rel = edge.get("src_id"), edge.get("dst_id"), edge.get("rel", "")
    incoming_weight = float(edge.get("weight", 1))

    existing = next((e for e in edges if e["src_id"] == src_id and e["dst_id"] == dst_id and e["rel"] == rel), None)
    if existing:
        existing["weight"] = max(float(existing.get("weight", 1)), incoming_weight)  # max → idempotent
        existing["props"] = {**(existing.get("props") or {}), **(edge.get("props") or {})}
        existing["last_seen"] = now
        return existing
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
    edges.append(new_edge)
    return new_edge


def get_kg_nodes(user_id: str) -> list[dict]:
    return list(_kg_nodes.get(user_id, []))


def get_kg_edges(user_id: str) -> list[dict]:
    return list(_kg_edges.get(user_id, []))


def delete_kg_for_user(user_id: str) -> None:
    _kg_nodes[user_id] = []
    _kg_edges[user_id] = []


# ---- Semantic memory (agent_memory) ----------------------------------------
_agent_memory: dict[str, list[dict]] = {}   # user_id -> rows


def upsert_agent_memory(user_id: str, row: dict) -> dict:
    """Idempotent on (kind, ref_id) when ref_id is present; else append."""
    from datetime import datetime, timezone
    import uuid
    now = datetime.now(timezone.utc).isoformat()
    rows = _agent_memory.setdefault(user_id, [])
    kind = row.get("kind", "")
    ref_id = row.get("ref_id")

    existing = None
    if ref_id is not None:
        existing = next((r for r in rows if r.get("kind") == kind and r.get("ref_id") == ref_id), None)
    if existing:
        if row.get("content"):
            existing["content"] = row["content"]
        if row.get("embedding") is not None:
            existing["embedding"] = row["embedding"]
        if row.get("client_id") is not None:
            existing["client_id"] = row["client_id"]
        if row.get("salience") is not None:
            existing["salience"] = float(row["salience"])
        if row.get("source") is not None:
            existing["source"] = row["source"]
        existing["metadata"] = {**(existing.get("metadata") or {}), **(row.get("metadata") or {})}
        existing["updated_at"] = now
        return existing

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
    rows.append(new_row)
    return new_row


def get_agent_memory(user_id: str, *, client_id: str | None = None,
                     kinds: list[str] | None = None, limit: int | None = None) -> list[dict]:
    rows = list(_agent_memory.get(user_id, []))
    if client_id is not None:
        rows = [r for r in rows if r.get("client_id") == client_id]
    if kinds:
        kset = set(kinds)
        rows = [r for r in rows if r.get("kind") in kset]
    rows.sort(key=lambda r: r.get("updated_at") or "", reverse=True)
    return rows[:limit] if limit else rows


def delete_agent_memory_for_user(user_id: str) -> None:
    _agent_memory[user_id] = []


def delete_agent_memory(user_id: str, *, kind: str | None = None,
                        ref_id_prefix: str | None = None) -> int:
    """Delete a user's agent_memory rows, narrowed by kind and/or ref_id prefix."""
    rows = _agent_memory.get(user_id, [])
    keep, removed = [], 0
    for r in rows:
        if kind is not None and r.get("kind") != kind:
            keep.append(r); continue
        if ref_id_prefix is not None and not str(r.get("ref_id") or "").startswith(ref_id_prefix):
            keep.append(r); continue
        removed += 1
    _agent_memory[user_id] = keep
    return removed


# ---- Notion connection (task ledger mirror) --------------------------------
_notion_connections: dict[str, dict] = {}


def upsert_notion_connection(user_id: str, data: dict) -> dict:
    data["user_id"] = user_id
    _notion_connections[user_id] = {**_notion_connections.get(user_id, {}), **data}
    return _notion_connections[user_id]


def get_notion_connection(user_id: str) -> dict | None:
    return _notion_connections.get(user_id)


def update_notion_connection(user_id: str, updates: dict) -> dict:
    _notion_connections[user_id] = {**_notion_connections.get(user_id, {}), **updates}
    return _notion_connections[user_id]


def delete_notion_connection(user_id: str) -> None:
    _notion_connections.pop(user_id, None)


def upsert_stripe_connection(user_id: str, data: dict) -> dict:
    data["user_id"] = user_id
    _stripe_connections[user_id] = {**_stripe_connections.get(user_id, {}), **data}
    return _stripe_connections[user_id]


def get_stripe_connection(user_id: str) -> dict | None:
    conn = _stripe_connections.get(user_id)
    return conn if conn and conn.get("connected") else None


def update_stripe_connection(user_id: str, updates: dict) -> dict:
    if user_id in _stripe_connections:
        _stripe_connections[user_id].update(updates)
    return _stripe_connections.get(user_id, {})


def delete_stripe_connection(user_id: str) -> None:
    _stripe_connections.pop(user_id, None)
