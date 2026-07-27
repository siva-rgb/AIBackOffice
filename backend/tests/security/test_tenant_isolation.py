"""M1.4 — Regression tests asserting cross-tenant reads/writes are rejected.

All tests run against the mock store (KORA_DATA_BACKEND=mock, set at import in
conftest). Each entity is exercised through the shared store surface.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app import store


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _other_id() -> str:
    return str(uuid.uuid4())


# ── Transactions ────────────────────────────────────────────────────────────

def test_list_transactions_user_scoped(user_id):
    from app.models import Transaction
    others_id = _other_id()
    now = _now()
    t_own = Transaction(id="t-own", user_id=user_id, date="2026-01-01", description="mine",
                        amount=100, type="income", created_at=now, category="software_subscriptions")
    t_other = Transaction(id="t-other", user_id=others_id, date="2026-01-01", description="theirs",
                          amount=200, type="income", created_at=now, category="software_subscriptions")
    store.insert_transactions([t_own, t_other])
    rows = store.list_transactions(user_id)
    assert len(rows) == 1
    assert rows[0].id == "t-own"


def test_get_transaction_wrong_user(user_id):
    from app.models import Transaction
    others_id = _other_id()
    now = _now()
    t = Transaction(id="t-get-other", user_id=others_id, date="2026-01-01", description="x",
                    amount=1, type="income", created_at=now, category="software_subscriptions")
    store.insert_transactions([t])
    result = store.update_transaction(user_id, "t-get-other", {"description": "evil"})
    assert result is None


# ── Invoices ────────────────────────────────────────────────────────────────

def test_list_invoices_user_scoped(user_id):
    from app.models import Invoice
    others_id = _other_id()
    now = _now()
    own = Invoice(id="inv-own", user_id=user_id, invoice_number="INV-U1",
                  client_name="Own", client_email="a@b.com", total=100,
                  currency="USD", status="draft", due_date="2026-02-01",
                  created_at=now, subtotal=100, tax_rate=0, tax_amount=0)
    other = Invoice(id="inv-other", user_id=others_id, invoice_number="INV-U2",
                    client_name="Other", client_email="c@d.com", total=200,
                    currency="USD", status="draft", due_date="2026-02-01",
                    created_at=now, subtotal=200, tax_rate=0, tax_amount=0)
    store.insert_invoice(own)
    store.insert_invoice(other)
    rows = store.list_invoices(user_id)
    assert len(rows) == 1
    assert rows[0].id == "inv-own"


def test_get_invoice_returns_none_for_wrong_user(user_id):
    from app.models import Invoice
    others_id = _other_id()
    now = _now()
    inv = Invoice(id="inv-gw", user_id=others_id, invoice_number="INV-GW1",
                  client_name="X", client_email="a@b.com", total=100,
                  currency="USD", status="draft", due_date="2026-02-01",
                  created_at=now, subtotal=100, tax_rate=0, tax_amount=0)
    store.insert_invoice(inv)
    result = store.get_invoice(user_id, "inv-gw")
    assert result is None


# ── Contracts ───────────────────────────────────────────────────────────────

def test_list_contracts_user_scoped(user_id):
    from app.models import Contract
    others_id = _other_id()
    now = _now()
    own = Contract(id="c-own", user_id=user_id, client_name="Own", type="service_contract",
                   status="draft", terms={}, created_at=now)
    other = Contract(id="c-other", user_id=others_id, client_name="Other", type="service_contract",
                     status="draft", terms={}, created_at=now)
    store.insert_contract(own)
    store.insert_contract(other)
    rows = store.list_contracts(user_id)
    assert len(rows) == 1
    assert rows[0].id == "c-own"


def test_get_contract_wrong_user(user_id):
    from app.models import Contract
    others_id = _other_id()
    now = _now()
    c = Contract(id="c-gw", user_id=others_id, client_name="X", type="service_contract",
                 status="draft", terms={}, created_at=now)
    store.insert_contract(c)
    result = store.get_contract(user_id, "c-gw")
    assert result is None


# ── Alerts ──────────────────────────────────────────────────────────────────

def test_list_alerts_isolation(user_id):
    from app.models import Alert
    others_id = _other_id()
    now = _now()
    own = Alert(id="al-own", user_id=user_id, type="overdue", severity="warning",
                title="test", body="test", read=False, created_at=now)
    other = Alert(id="al-other", user_id=others_id, type="overdue", severity="warning",
                  title="test2", body="test2", read=False, created_at=now)
    store.insert_alert(own)
    store.insert_alert(other)
    rows = store.list_alerts(user_id)
    assert len(rows) == 1
    assert rows[0].id == "al-own"


# ── Manager tasks ───────────────────────────────────────────────────────────

def test_list_manager_tasks_isolation(user_id):
    from app.models import ManagerTask
    others_id = _other_id()
    now = _now()
    own = ManagerTask(id="mt-own", user_id=user_id, title="test", kind="send_follow_up",
                      status="proposed", created_at=now)
    other = ManagerTask(id="mt-other", user_id=others_id, title="test", kind="send_follow_up",
                        status="proposed", created_at=now)
    store.insert_manager_task(own)
    store.insert_manager_task(other)
    rows = store.list_manager_tasks(user_id)
    assert len(rows) == 1
    assert rows[0].id == "mt-own"


def test_get_manager_task_wrong_user(user_id):
    from app.models import ManagerTask
    others_id = _other_id()
    now = _now()
    mt = ManagerTask(id="mt-gw", user_id=others_id, title="test", kind="send_follow_up",
                     status="proposed", created_at=now)
    store.insert_manager_task(mt)
    result = store.get_manager_task(user_id, "mt-gw")
    assert result is None


# ── Agent logs ──────────────────────────────────────────────────────────────

def test_agent_log_is_user_scoped(user_id):
    from app.models import AgentLog
    others_id = _other_id()
    now = _now()
    own = AgentLog(id="a-own", user_id=user_id, agent_type="bookkeeper", action="test",
                   status="success", model_used="mock", triggered_by="user",
                   created_at=now, input_data={}, output_data={"result": "ok"})
    other = AgentLog(id="a-other", user_id=others_id, agent_type="bookkeeper", action="test",
                     status="success", model_used="mock", triggered_by="user",
                     created_at=now, input_data={}, output_data={"result": "ok"})
    store.insert_agent_log(own)
    store.insert_agent_log(other)
    rows = store.list_agent_logs(user_id)
    assert len(rows) == 1
    assert rows[0].id == "a-own"


# ── Clients ─────────────────────────────────────────────────────────────────

def test_list_clients_isolation(user_id):
    from app.models import Client
    others_id = _other_id()
    now = _now()
    own = Client(id="cli-own", user_id=user_id, name="Own Client", email="own@test.com",
                 created_at=now)
    other = Client(id="cli-other", user_id=others_id, name="Other Client", email="other@test.com",
                   created_at=now)
    store.insert_client(own)
    store.insert_client(other)
    rows = store.list_clients(user_id)
    assert len(rows) == 1
    assert rows[0].id == "cli-own"


def test_get_client_wrong_user(user_id):
    from app.models import Client
    others_id = _other_id()
    now = _now()
    c = Client(id="cli-gw", user_id=others_id, name="Other", email="other@x.com", created_at=now)
    store.insert_client(c)
    result = store.get_client(user_id, "cli-gw")
    assert result is None


def test_update_client_wrong_user(user_id):
    from app.models import Client
    others_id = _other_id()
    now = _now()
    c = Client(id="cli-uw", user_id=others_id, name="Other", email="other@x.com", created_at=now)
    store.insert_client(c)
    result = store.update_client(user_id, "cli-uw", {"name": "evil"})
    assert result is None


def test_delete_client_wrong_user(user_id):
    from app.models import Client
    others_id = _other_id()
    now = _now()
    c = Client(id="cli-dw", user_id=others_id, name="Other", email="other@x.com", created_at=now)
    store.insert_client(c)
    result = store.delete_client(user_id, "cli-dw")
    assert result is False


# ── Engagements ─────────────────────────────────────────────────────────────

def test_list_engagements_isolation(user_id):
    from app.models import Engagement
    others_id = _other_id()
    now = _now()
    own = Engagement(id="eng-own", user_id=user_id, client_id="cli-own", title="Test",
                     status="active", created_at=now)
    other = Engagement(id="eng-other", user_id=others_id, client_id="cli-other", title="Test",
                       status="active", created_at=now)
    store.insert_engagement(own)
    store.insert_engagement(other)
    rows = store.list_engagements(user_id)
    assert len(rows) == 1
    assert rows[0].id == "eng-own"


# ── Tasks ───────────────────────────────────────────────────────────────────

def test_list_tasks_isolation(user_id):
    from app.models import Task
    others_id = _other_id()
    now = _now()
    own = Task(id="task-own", user_id=user_id, title="My Task", client_id="cli-1",
               created_at=now)
    other = Task(id="task-other", user_id=others_id, title="Other Task", client_id="cli-2",
                 created_at=now)
    store.insert_task(own)
    store.insert_task(other)
    rows = store.list_tasks(user_id)
    assert len(rows) == 1
    assert rows[0].id == "task-own"


def test_update_task_wrong_user(user_id):
    from app.models import Task
    others_id = _other_id()
    now = _now()
    t = Task(id="task-uw", user_id=others_id, title="Other", client_id="cli-2", created_at=now)
    store.insert_task(t)
    result = store.update_task(user_id, "task-uw", {"title": "evil"})
    assert result is None


def test_delete_task_wrong_user(user_id):
    from app.models import Task
    others_id = _other_id()
    now = _now()
    t = Task(id="task-dw", user_id=others_id, title="Other", client_id="cli-2", created_at=now)
    store.insert_task(t)
    result = store.delete_task(user_id, "task-dw")
    assert result is False


# ── Stories ─────────────────────────────────────────────────────────────────

def test_list_stories_isolation(user_id):
    from app.models import Story
    others_id = _other_id()
    now = _now()
    own = Story(id="story-own", user_id=user_id, task_id="t-1", client_id="c-1",
                title="S", created_at=now)
    other = Story(id="story-other", user_id=others_id, task_id="t-2", client_id="c-2",
                  title="S", created_at=now)
    store.insert_story(own)
    store.insert_story(other)
    rows = store.list_stories(user_id)
    assert len(rows) == 1
    assert rows[0].id == "story-own"


# ── Quick captures ──────────────────────────────────────────────────────────

def test_list_captures_isolation(user_id):
    from app.models import QuickCapture
    others_id = _other_id()
    now = _now()
    own = QuickCapture(id="qc-own", user_id=user_id, raw_text="1", requires_review=False,
                       created_at=now)
    other = QuickCapture(id="qc-other", user_id=others_id, raw_text="2", requires_review=False,
                         created_at=now)
    store.insert_capture(own)
    store.insert_capture(other)
    rows = store.list_captures(user_id)
    assert len(rows) == 1
    assert rows[0].id == "qc-own"


# ── Proposals ───────────────────────────────────────────────────────────────

def test_list_proposals_isolation(user_id):
    from app.models import Proposal
    others_id = _other_id()
    now = _now()
    own = Proposal(id="pr-own", user_id=user_id, client_id="c-1", title="Prop",
                   status="draft", created_at=now, client_email="a@b.com")
    other = Proposal(id="pr-other", user_id=others_id, client_id="c-2", title="Prop",
                     status="draft", created_at=now, client_email="c@d.com")
    store.insert_proposal(own)
    store.insert_proposal(other)
    rows = store.list_proposals(user_id)
    assert len(rows) == 1
    assert rows[0].id == "pr-own"


def test_get_proposal_wrong_user(user_id):
    from app.models import Proposal
    others_id = _other_id()
    now = _now()
    p = Proposal(id="pr-gw", user_id=others_id, client_id="c-2", title="Test",
                 status="draft", created_at=now, client={})
    store.insert_proposal(p)
    result = store.get_proposal(user_id, "pr-gw")
    assert result is None


# ── Retainers ───────────────────────────────────────────────────────────────

def test_retainers_isolation(user_id):
    from app.models import Retainer
    others_id = _other_id()
    now = _now()
    own = Retainer(id="ret-own", user_id=user_id, client_id="c-1", title="Test",
                   amount=100, frequency="monthly", start_date="2026-01-01",
                   next_invoice_date="2026-03-01", status="active", created_at=now)
    other = Retainer(id="ret-other", user_id=others_id, client_id="c-2", title="Test",
                     amount=200, frequency="monthly", start_date="2026-01-01",
                     next_invoice_date="2026-03-01", status="active", created_at=now)
    store.insert_retainer(own)
    store.insert_retainer(other)
    rows = store.list_retainers(user_id)
    assert len(rows) == 1
    assert rows[0].id == "ret-own"


def test_get_retainer_wrong_user(user_id):
    from app.models import Retainer
    others_id = _other_id()
    now = _now()
    r = Retainer(id="ret-gw", user_id=others_id, client_id="c-2", title="Test",
                 amount=100, frequency="monthly", start_date="2026-01-01",
                 next_invoice_date="2026-03-01", status="active", created_at=now)
    store.insert_retainer(r)
    result = store.get_retainer(user_id, "ret-gw")
    assert result is None


# ── Cross-tenant insert validation at TenantQuery level ─────────────────────

@pytest.mark.skipif(True, reason="Requires supabase package; validates repo._check_user_id logic")
def test_insert_with_mismatched_user_id_rejects():
    """The TenantQuery._check_user_id rejects inserts with a foreign user_id."""
    from app.backends.repository import repo
    from supabase import create_client

    user_id = str(uuid.uuid4())
    sb = create_client("http://localhost:9999", "fake-service-role")
    r = repo(sb, user_id)
    with pytest.raises(ValueError, match="Cross-tenant"):
        r.insert("invoices", {"user_id": _other_id(), "amount": 100})