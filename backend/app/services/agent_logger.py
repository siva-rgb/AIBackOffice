from __future__ import annotations

import json
from datetime import datetime, timezone

from .. import store
from ..models import AgentLog

# The single audit trail for every AI action in Kora (SKILL.md §13). Logging
# must never raise into the caller's flow — a failed log is swallowed.


def _truncate(value):
    try:
        s = json.dumps(value, default=str)
    except TypeError:
        return value
    if len(s) > 4000:
        return {"_truncated": True, "preview": s[:4000]}
    return value


def log_action(
    *,
    user_id: str,
    agent_type: str,
    action: str,
    input=None,
    output=None,
    model_used: str = "gemini-1.5-pro",
    tokens_used: int | None = None,
    latency_ms: int | None = None,
    cost_usd: float | None = None,
    status: str = "success",
    error_message: str | None = None,
    triggered_by: str = "user",
    source_record_type: str | None = None,
    source_record_id: str | None = None,
) -> AgentLog | None:
    try:
        log = AgentLog(
            id=store.uid("log"),
            user_id=user_id,
            agent_type=agent_type,
            action=action,
            input=_truncate(input),
            output=_truncate(output),
            model_used=model_used,
            tokens_used=tokens_used,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            status=status,
            error_message=error_message,
            triggered_by=triggered_by,
            source_record_type=source_record_type,
            source_record_id=source_record_id,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        return store.insert_agent_log(log)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[agent-logger] failed to write log row: {exc}")
        return None
