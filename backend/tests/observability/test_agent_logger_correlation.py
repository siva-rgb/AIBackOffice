"""agent_logger <-> request_id correlation (M11.2).

The single audit trail row (`agent_logs`) must carry the request_id of the
HTTP request that triggered it, so an ops engineer can grep the access log
and find every AI action that fired on the same request — and vice versa.
"""

from __future__ import annotations

from app import store
from app.services import agent_logger
from app.utils.request_context import (
    begin_request_context,
    end_request_context,
)


def teardown_function(_):
    end_request_context()


def test_log_row_carries_request_id_when_scope_is_open(user_id):
    rid = begin_request_context()
    try:
        log = agent_logger.log_action(
            user_id=user_id, agent_type="invoice_follow_up", action="send_reminder"
        )
    finally:
        end_request_context()
    assert log is not None
    assert isinstance(log.output, dict)
    assert log.output.get("_request_id") == rid


def test_log_row_omits_request_id_when_no_scope(user_id):
    log = agent_logger.log_action(
        user_id=user_id, agent_type="invoice_follow_up", action="send_reminder"
    )
    assert log is not None
    if isinstance(log.output, dict):
        assert "_request_id" not in log.output


def test_existing_cost_usd_round_trip_keeps_working(user_id):
    """The new code path must not break the existing _cost_usd envelope."""
    begin_request_context()
    try:
        agent_logger.log_action(
            user_id=user_id,
            agent_type="invoice_follow_up",
            action="send_reminder",
            cost_usd=0.0042,
            output={"ok": True},
        )
    finally:
        end_request_context()
    logs = store.list_agent_logs(user_id)
    assert len(logs) == 1
    # _cost_usd is on the output envelope — preserved through round-trip.
    assert logs[0].cost_usd == 0.0042
    assert logs[0].output["ok"] is True
