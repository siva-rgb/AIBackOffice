"""Regression cover for contract-signed → invoice creation (M6).

`on_contract_signed` is where a signed contract's payment schedule becomes real
invoices — the bridge between the legal side and the money side. It must create
exactly one invoice per positive milestone, with the right amount and due date,
and it must never invent money from an empty or zero-value schedule.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from app import store
from app.models import Contract, ContractType
from app.services import cross_module


def _contract(user_id, milestones):
    return Contract(
        id=store.uid("contract"), user_id=user_id, type=ContractType.service_contract,
        title="Website build", client_name="Acme Corp", client_email="ap@acme.com",
        terms={"milestones": milestones},
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def test_each_positive_milestone_becomes_one_invoice(user_id):
    c = _contract(user_id, [
        {"label": "Deposit", "amount": 1000, "due_in_days": 0},
        {"label": "On delivery", "amount": 2500, "due_in_days": 30},
    ])
    invoices = cross_module.on_contract_signed(user_id, c)

    assert len(invoices) == 2
    assert [i.total for i in invoices] == [1000.0, 2500.0]
    assert all(i.contract_id == c.id and i.status == "draft" for i in invoices)
    assert all(i.client_name == "Acme Corp" for i in invoices)
    # Due date reflects due_in_days from today (0 and 30).
    assert invoices[0].due_date == date.today().isoformat()
    assert invoices[1].due_date == (date.today() + timedelta(days=30)).isoformat()
    # They are actually persisted, not just returned.
    persisted = [i for i in store.list_invoices(user_id) if i.contract_id == c.id]
    assert len(persisted) == 2


def test_zero_and_negative_milestones_create_nothing(user_id):
    c = _contract(user_id, [
        {"label": "Freebie", "amount": 0, "due_in_days": 7},
        {"label": "Bad", "amount": -50, "due_in_days": 7},
    ])
    assert cross_module.on_contract_signed(user_id, c) == []


def test_no_milestones_is_a_safe_noop(user_id):
    c = _contract(user_id, [])
    assert cross_module.on_contract_signed(user_id, c) == []
    # No alert should be raised when nothing was created.
    assert not [a for a in store.list_alerts(user_id) if a.type == "contract_signed"]


def test_signing_raises_an_alert_when_invoices_are_created(user_id):
    c = _contract(user_id, [{"label": "Deposit", "amount": 500, "due_in_days": 0}])
    cross_module.on_contract_signed(user_id, c)
    alerts = [a for a in store.list_alerts(user_id) if a.type == "contract_signed"]
    assert len(alerts) == 1 and "1" in alerts[0].body


def test_string_milestone_amounts_are_coerced(user_id):
    """Contract terms are free-form JSON — an amount can arrive as a string."""
    c = _contract(user_id, [{"label": "Deposit", "amount": "750", "due_in_days": 14}])
    invoices = cross_module.on_contract_signed(user_id, c)
    assert len(invoices) == 1 and invoices[0].total == 750.0
