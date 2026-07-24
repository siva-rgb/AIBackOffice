"""Digest email delivery behind the approval gate (M8).

The digest can now reach the user's inbox WITHOUT weakening the core contract:
`no_outbound_send_without_human_approval`. `queue_digest_email` only ever
*queues* a send_email_gmail task; the send happens in `approve_task` →
`execute_gmail_send`. These pin: connected+approved → sent with a message id;
no approval or no Gmail → draft-only, no send; and a repeat never double-sends.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app import store
from app.models import Alert, User
from app.services import alert_agent, gmail_agent, supervisor


def _now():
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
def owner(user_id):
    """Register a test user in the mock store so get_user/update_user find it."""
    u = User(id=user_id, email="owner@example.com", full_name="Owner", plan="pro",
             created_at=_now())
    store._b._users.append(u)
    yield u
    store._b._users[:] = [x for x in store._b._users if x.id != user_id]


@pytest.fixture
def gmail_on(monkeypatch):
    """Pretend Gmail is connected, and stub the actual send to return a fake id
    (execute_gmail_send hits Google, which we can't reach in a test)."""
    monkeypatch.setattr(gmail_agent, "is_gmail_connected", lambda uid: True)
    sends = []

    def fake_execute(uid, payload):
        sends.append(payload)
        return "gmail-msg-abc"
    monkeypatch.setattr(gmail_agent, "execute_gmail_send", fake_execute)
    # supervisor imports execute_gmail_send lazily from gmail_agent, so patching
    # the module attribute is enough.
    return sends


# ── Without Gmail → draft-only, nothing queued, nothing sent ────────────────

def test_no_gmail_means_draft_only(user_id, owner, monkeypatch):
    monkeypatch.setattr(gmail_agent, "is_gmail_connected", lambda uid: False)

    result = alert_agent.queue_digest_email(user_id)
    assert result["delivered"] is False and result.get("draftOnly") is True
    assert "gmail isn't connected" in result["note"].lower()
    # No send task was created.
    assert not [t for t in store.list_manager_tasks(user_id) if t.kind == "send_email_gmail"]


def test_no_email_on_file_is_a_clear_error(user_id, owner, monkeypatch):
    store.update_user(user_id, {"email": ""})
    monkeypatch.setattr(gmail_agent, "is_gmail_connected", lambda uid: True)
    result = alert_agent.queue_digest_email(user_id)
    assert result["ok"] is False and "email" in result["note"].lower()


# ── With Gmail → queues for approval, but does NOT send yet ──────────────────

def test_queue_creates_a_proposed_task_and_sends_nothing(user_id, owner, gmail_on):
    result = alert_agent.queue_digest_email(user_id)

    assert result["queued"] is True and result["delivered"] is False
    tasks = [t for t in store.list_manager_tasks(user_id) if t.kind == "send_email_gmail"]
    assert len(tasks) == 1 and tasks[0].status == "proposed"
    assert tasks[0].payload["to_email"] == "owner@example.com"
    # The invariant: queueing sent nothing.
    assert gmail_on == [], "queue_digest_email sent an email without approval"


def test_queue_is_idempotent_for_the_day(user_id, owner, gmail_on):
    first = alert_agent.queue_digest_email(user_id)
    second = alert_agent.queue_digest_email(user_id)
    assert second["taskId"] == first["taskId"]
    assert "already awaiting" in second["note"].lower()
    tasks = [t for t in store.list_manager_tasks(user_id) if t.kind == "send_email_gmail"]
    assert len(tasks) == 1, "a second run double-queued the digest"


# ── Approval → sent, with a gmailMessageId in the note ──────────────────────

def test_approval_sends_and_reports_a_message_id(user_id, owner, gmail_on):
    task_id = alert_agent.queue_digest_email(user_id)["taskId"]

    outcome = supervisor.approve_task(user_id, task_id)
    assert len(gmail_on) == 1, "approval did not trigger exactly one send"
    assert outcome["result"]["gmailMessageId"] == "gmail-msg-abc"
    assert "sent to owner@example.com" in outcome["result"]["note"].lower()
    # Task is resolved, not still proposed.
    assert store.get_manager_task(user_id, task_id).status in ("approved", "done")


def test_approving_twice_does_not_double_send(user_id, owner, gmail_on):
    task_id = alert_agent.queue_digest_email(user_id)["taskId"]

    supervisor.approve_task(user_id, task_id)
    again = supervisor.approve_task(user_id, task_id)
    assert len(gmail_on) == 1, "a second approval re-sent the email"
    assert "already" in again["result"]["note"].lower()


# ── The digest body is deterministic and reflects real alerts ───────────────

def test_digest_body_reflects_unread_alerts(user_id, owner):
    store.insert_alert(Alert(id=store.uid("a"), user_id=user_id, type="overdue",
                             severity="warning", title="INV-12 overdue",
                             body="Acme owes 3,000", read=False, created_at=_now()))
    email = alert_agent.build_digest_email(user_id)
    assert email["alertCount"] == 1
    assert "INV-12 overdue" in email["bodyText"]
    assert "<li>" in email["bodyHtml"]


def test_digest_body_when_all_clear(user_id, owner):
    email = alert_agent.build_digest_email(user_id)
    assert email["alertCount"] == 0
    assert "all clear" in email["bodyText"].lower()
