"""Task / project ledger — the canonical record of client work.

KORA owns this ledger; external PM tools (Notion first) mirror it via
`external_ref`. Everything the agents need to guarantee "nothing gets missed"
lives here:

  * `create_task` / `update_task` / `list_tasks` — the CRUD the API + agents use.
  * `auto_capture_*` — turns detected commitments into tracked work. This is the
    heart of the feature: an action item in a meeting, a promise in an email, or
    a signed contract's milestones all become real tasks, idempotently
    (`source_ref` keys the upsert so re-syncs update instead of duplicating).
  * `build_task_brief` — compact prompt block so every agent knows what's open,
    overdue and blocked before it speaks or drafts.

All auto-capture is best-effort and never raises into its caller.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from .. import store
from ..models import Task

OPEN_STATUSES = ["todo", "in_progress", "blocked"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _ref(*parts: str) -> str:
    """Stable idempotency key for an auto-captured task."""
    raw = "|".join(str(p or "") for p in parts)
    return hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()[:32]


def is_overdue(task) -> bool:
    due = getattr(task, "due_date", None)
    status = getattr(task, "status", "")
    if not due or status in ("done", "cancelled"):
        return False
    return str(due)[:10] < _today()


# ── CRUD ────────────────────────────────────────────────────────────────────
def create_task(user_id: str, data: dict) -> Task:
    """Create a task. If `source_ref` is supplied and already exists, the
    existing task is updated instead (idempotent auto-capture)."""
    source_ref = data.get("source_ref")
    if source_ref:
        existing = store.find_task_by_source_ref(user_id, source_ref)
        if existing:
            patch = {k: v for k, v in data.items()
                     if k in ("title", "description_md", "due_date", "owner",
                              "client_id", "engagement_id", "priority") and v is not None}
            if patch:
                patch["updated_at"] = _now()
                return store.update_task(user_id, existing.id, patch) or existing
            return existing

    task = Task(
        id=store.uid("task"),
        user_id=user_id,
        client_id=data.get("client_id"),
        engagement_id=data.get("engagement_id"),
        title=str(data.get("title", "")).strip()[:300] or "Untitled task",
        description_md=data.get("description_md"),
        status=data.get("status", "todo"),
        priority=data.get("priority", "medium"),
        due_date=data.get("due_date"),
        owner=data.get("owner"),
        source=data.get("source", "manual"),
        source_ref=source_ref,
        external_ref=data.get("external_ref"),
        external_url=data.get("external_url"),
        created_at=_now(),
        updated_at=_now(),
    )
    store.insert_task(task)
    return task


def update_task(user_id: str, task_id: str, patch: dict) -> Task | None:
    """Patch a task. Stamps completed_at when it transitions into done."""
    patch = {k: v for k, v in patch.items() if v is not None}
    if not patch:
        return store.get_task(user_id, task_id)
    if patch.get("status") == "done":
        patch.setdefault("completed_at", _now())
    elif "status" in patch:
        patch["completed_at"] = None
    patch["updated_at"] = _now()
    return store.update_task(user_id, task_id, patch)


def list_tasks(user_id: str, **filters) -> list:
    return store.list_tasks(user_id, **filters)


def stats(user_id: str) -> dict:
    tasks = store.list_tasks(user_id)
    open_tasks = [t for t in tasks if t.status in OPEN_STATUSES]
    return {
        "total": len(tasks),
        "open": len(open_tasks),
        "overdue": sum(1 for t in open_tasks if is_overdue(t)),
        "blocked": sum(1 for t in tasks if t.status == "blocked"),
        "dueToday": sum(1 for t in open_tasks if str(t.due_date or "")[:10] == _today()),
        "done": sum(1 for t in tasks if t.status == "done"),
    }


# ── Auto-capture: commitments → tracked work ────────────────────────────────
def auto_capture_from_meeting(user_id: str, client_id: str | None,
                              next_steps: list, meeting_id: str | None = None) -> int:
    """Meeting action items / next steps → tasks. Idempotent per (meeting, action)."""
    created = 0
    for step in next_steps or []:
        if not isinstance(step, dict):
            continue
        action = (step.get("action") or step.get("what") or "").strip()
        if not action:
            continue
        try:
            create_task(user_id, {
                "title": action,
                "client_id": client_id,
                "due_date": step.get("by_when") or step.get("due_date"),
                "owner": step.get("owner") or "me",
                "source": "meeting",
                "source_ref": _ref("meeting", meeting_id, action),
                "description_md": f"Captured from a meeting on {_today()}.",
                "priority": "high" if step.get("by_when") else "medium",
            })
            created += 1
        except Exception as exc:
            print(f"[tasks] meeting capture skipped: {exc}")
    return created


def auto_capture_from_email(user_id: str, client_id: str | None, intel: dict) -> int:
    """Pending commitments detected in client email → tasks. Idempotent per
    (client, who, what)."""
    created = 0
    client_name = (intel or {}).get("client_name", "")
    for c in (intel or {}).get("commitments_pending", []) or []:
        if not isinstance(c, dict):
            continue
        what = (c.get("what") or "").strip()
        if not what:
            continue
        who = (c.get("who") or "me").strip()
        try:
            create_task(user_id, {
                "title": what if who == "me" else f"Follow up: {what}",
                "client_id": client_id,
                "due_date": c.get("mentioned_date") or c.get("by_when"),
                "owner": who,
                "source": "email",
                "source_ref": _ref("email", client_id, who, what),
                "description_md": f"Commitment detected in email with {client_name or 'the client'}.",
            })
            created += 1
        except Exception as exc:
            print(f"[tasks] email capture skipped: {exc}")
    return created


def auto_capture_from_contract(user_id: str, contract, client_id: str | None = None) -> int:
    """A signed contract's milestones → delivery tasks (the work owed, alongside
    the invoices cross_module already creates for the money owed)."""
    created = 0
    milestones = (getattr(contract, "terms", None) or {}).get("milestones") or []
    for m in milestones:
        if not isinstance(m, dict):
            continue
        label = (m.get("label") or "").strip()
        if not label:
            continue
        try:
            create_task(user_id, {
                "title": f"Deliver: {label}",
                "client_id": client_id,
                "owner": "me",
                "source": "contract",
                "source_ref": _ref("contract", getattr(contract, "id", ""), label),
                "description_md": (
                    f"Milestone from contract '{getattr(contract, 'title', '') or 'contract'}'"
                    f" with {getattr(contract, 'client_name', '') or 'the client'}."
                ),
                "priority": "high",
            })
            created += 1
        except Exception as exc:
            print(f"[tasks] contract capture skipped: {exc}")
    return created


# ── Agent-facing context ────────────────────────────────────────────────────
def build_task_brief(user_id: str, client_id: str | None = None,
                     max_chars: int = 450) -> str:
    """Compact open-work block for prompt injection, or "". Overdue and blocked
    lead — those are what an agent must not contradict or forget."""
    try:
        tasks = store.list_tasks(user_id, client_id=client_id, statuses=OPEN_STATUSES)
    except Exception:
        return ""
    if not tasks:
        return ""

    # Each task appears in exactly one bucket — a task that is both overdue and
    # blocked is listed once (as overdue, the more urgent framing).
    overdue = [t for t in tasks if is_overdue(t)]
    overdue_ids = {t.id for t in overdue}
    blocked = [t for t in tasks if t.status == "blocked" and t.id not in overdue_ids]
    listed_ids = overdue_ids | {t.id for t in blocked}
    others = [t for t in tasks if t.id not in listed_ids]

    lines: list[str] = [f"Open work ({len(tasks)} task{'s' if len(tasks) != 1 else ''}):"]
    for t in overdue[:4]:
        lines.append(f"- OVERDUE (due {str(t.due_date)[:10]}): {t.title}")
    for t in blocked[:3]:
        lines.append(f"- BLOCKED: {t.title}")
    for t in others[:4]:
        due = f" (due {str(t.due_date)[:10]})" if t.due_date else ""
        lines.append(f"- {t.status}: {t.title}{due}")

    out = "\n".join(lines)
    if len(out) > max_chars:
        out = out[:max_chars].rsplit("\n", 1)[0]
    return out
