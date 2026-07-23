"""Task ledger — auto-capture idempotency and the agent-facing brief.

Idempotency is the load-bearing guarantee: meeting/email syncs re-run daily, so
capturing the same commitment twice would fill the ledger with duplicates.
"""
from __future__ import annotations

from types import SimpleNamespace

from app import store
from app.services import task_ledger as TL


# ── Auto-capture: commitments become tracked work, exactly once ────────────

def test_meeting_action_items_become_tasks_idempotently(user_id):
    steps = [
        {"action": "Send revised wireframes", "owner": "me", "by_when": "2026-08-20"},
        {"action": "Client to provide brand assets", "owner": "client", "by_when": "2026-08-18"},
    ]

    assert TL.auto_capture_from_meeting(user_id, "client-1", steps, "meeting-1") == 2
    assert len(store.list_tasks(user_id)) == 2

    # The daily sync re-runs over the same meeting — must not duplicate.
    TL.auto_capture_from_meeting(user_id, "client-1", steps, "meeting-1")
    assert len(store.list_tasks(user_id)) == 2, "re-running the meeting sync duplicated tasks"


def test_email_commitments_become_tasks_idempotently(user_id):
    intel = {
        "client_name": "Acme",
        "commitments_pending": [
            {"who": "me", "what": "Send the updated quote", "mentioned_date": "2026-08-19"},
            {"who": "client", "what": "Confirm the launch date"},
        ],
    }

    assert TL.auto_capture_from_email(user_id, "client-1", intel) == 2
    TL.auto_capture_from_email(user_id, "client-1", intel)
    assert len(store.list_tasks(user_id)) == 2, "re-running the email sync duplicated tasks"


def test_signed_contract_milestones_become_delivery_tasks(user_id):
    contract = SimpleNamespace(
        id="contract-1",
        title="Website build",
        client_name="Acme",
        terms={"milestones": [
            {"label": "Phase 1 design", "amount": 2000},
            {"label": "Phase 2 build", "amount": 3000},
        ]},
    )

    assert TL.auto_capture_from_contract(user_id, contract, "client-1") == 2
    titles = [t.title for t in store.list_tasks(user_id)]
    assert "Deliver: Phase 1 design" in titles

    TL.auto_capture_from_contract(user_id, contract, "client-1")
    assert len(store.list_tasks(user_id)) == 2, "re-signing duplicated delivery tasks"


def test_capture_ignores_entries_with_no_content(user_id):
    TL.auto_capture_from_meeting(user_id, "client-1", [{"owner": "me"}, {"action": "   "}], "m-1")
    TL.auto_capture_from_email(user_id, "client-1", {"commitments_pending": [{"who": "me"}]})
    assert store.list_tasks(user_id) == []


# ── The agent-facing brief ─────────────────────────────────────────────────

def test_overdue_and_blocked_task_is_listed_exactly_once(user_id):
    """Regression: the brief used to print a task twice when it was both.

    Duplicated lines waste the context budget the brief exists to conserve.
    """
    task = TL.create_task(user_id, {"title": "Both overdue and blocked", "due_date": "2026-01-01"})
    TL.update_task(user_id, task.id, {"status": "blocked"})
    TL.create_task(user_id, {"title": "An ordinary task"})

    brief = TL.build_task_brief(user_id)

    assert brief.count("Both overdue and blocked") == 1
    assert "OVERDUE" in brief          # listed under the more urgent framing
    assert "An ordinary task" in brief


def test_brief_is_empty_when_there_is_no_open_work(user_id):
    """Empty string, not a header with nothing under it — it gets injected into prompts."""
    assert TL.build_task_brief(user_id) == ""

    task = TL.create_task(user_id, {"title": "Finished thing"})
    TL.update_task(user_id, task.id, {"status": "done"})
    assert TL.build_task_brief(user_id) == ""


# ── Status transitions + stats ─────────────────────────────────────────────

def test_completing_and_reopening_maintains_completed_at(user_id):
    task = TL.create_task(user_id, {"title": "A task"})
    assert task.completed_at is None

    TL.update_task(user_id, task.id, {"status": "done"})
    assert store.get_task(user_id, task.id).completed_at is not None

    TL.update_task(user_id, task.id, {"status": "in_progress"})
    assert store.get_task(user_id, task.id).completed_at is None, "reopening left a stale completed_at"


def test_stats_counts_overdue_and_blocked(user_id):
    TL.create_task(user_id, {"title": "Overdue", "due_date": "2026-01-01"})
    blocked = TL.create_task(user_id, {"title": "Blocked"})
    TL.update_task(user_id, blocked.id, {"status": "blocked"})
    done = TL.create_task(user_id, {"title": "Done"})
    TL.update_task(user_id, done.id, {"status": "done"})

    stats = TL.stats(user_id)
    assert stats["total"] == 3
    assert stats["open"] == 2       # done is not open
    assert stats["overdue"] == 1
    assert stats["blocked"] == 1
    assert stats["done"] == 1


def test_a_done_task_is_never_counted_overdue(user_id):
    task = TL.create_task(user_id, {"title": "Late but finished", "due_date": "2026-01-01"})
    TL.update_task(user_id, task.id, {"status": "done"})
    assert TL.stats(user_id)["overdue"] == 0
