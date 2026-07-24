"""Regression cover for the agent audit trail (M6).

`agent_logger.log_action` is the single audit trail for every AI action. Two
properties matter: it attributes each action (who/what/why/which record), and it
NEVER raises into the caller's flow — a failed log must not break the agent.
"""
from __future__ import annotations

from app import store
from app.services import agent_logger


def test_log_action_attributes_the_action(user_id):
    agent_logger.log_action(
        user_id=user_id, agent_type="invoice_follow_up",
        action="Sent reminder for INV-12",
        input={"invoice": "INV-12"}, output={"ok": True},
        triggered_by="scheduler",
        source_record_type="invoice", source_record_id="INV-12",
    )
    logs = store.list_agent_logs(user_id)
    assert len(logs) == 1
    log = logs[0]
    assert log.agent_type == "invoice_follow_up"
    assert log.triggered_by == "scheduler"
    assert log.source_record_type == "invoice"
    assert log.source_record_id == "INV-12"
    assert log.status == "success"


def test_oversized_payloads_are_truncated_not_dropped(user_id):
    big = {"blob": "x" * 10_000}
    agent_logger.log_action(user_id=user_id, agent_type="bookkeeper", action="big", input=big)
    log = store.list_agent_logs(user_id)[0]
    # The row is still written; the giant field is replaced by a bounded preview.
    assert isinstance(log.input, dict)
    assert log.input.get("_truncated") is True
    assert len(log.input.get("preview", "")) <= 4000


def test_logging_never_raises_into_the_caller(user_id, monkeypatch):
    """A broken store must not take down the agent that was only trying to log."""
    def boom(_log):
        raise RuntimeError("db down")
    monkeypatch.setattr(store, "insert_agent_log", boom)

    # Must return None, not propagate.
    assert agent_logger.log_action(user_id=user_id, agent_type="bookkeeper", action="x") is None


def test_small_payloads_pass_through_untouched(user_id):
    agent_logger.log_action(user_id=user_id, agent_type="bookkeeper", action="x",
                            input={"a": 1}, output=["ok"])
    log = store.list_agent_logs(user_id)[0]
    assert log.input == {"a": 1} and log.output == ["ok"]
