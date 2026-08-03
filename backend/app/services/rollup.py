"""Deterministic delivery roll-up: story → task → project → client.

Before this module, a client's health came from **money and silence** only
(`butler.compute_client_health`: overdue invoices, at-risk engagements, days
since last activity). A client could be drowning in blocked work and still
score 100 as long as they paid on time and someone sent an email last week.
This module supplies the missing third signal — **delivery** — and folds it in.

Two properties are load-bearing, and both are enforced by tests:

**1. It is arithmetic, never narrative.** No LLM call happens anywhere on this
path (invariant `rollup_health_is_deterministic`). Every number here is
reproducible from the ledger alone, so health can be recomputed on every page
load and in cron without cost, latency, or a model's opinion drifting between
two identical inputs. M3's agents may *explain* these numbers; they never
produce them.

**2. It extends the existing score, it does not replace it.** When a client has
no tasks and no stories, `delivery_signal` reports `hasDeliveryData=False` and
contributes exactly zero — the pre-M2 behaviour is preserved bit for bit. The
delivery contribution is also clamped (`CLIENT_MAX_PENALTY` /
`CLIENT_MAX_BONUS`) so a noisy delivery picture can dent the score but never
drown out overdue money.

The penalty weights are module constants rather than inline magic numbers
specifically so the tests can assert the arithmetic, and so tuning the model is
a one-line, reviewable change.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .. import store

# ── Scoring model ───────────────────────────────────────────────────────────
# Each risk signal costs points, capped so no single category can sink a score
# on its own. Caps matter: 12 blockers on one story is one sick story, not a
# catastrophe twelve times over.
BLOCKER_PENALTY = 8
BLOCKER_CAP = 30
NOT_GOING_WELL_PENALTY = 3
NOT_GOING_WELL_CAP = 12
OVERDUE_PENALTY = 10
OVERDUE_CAP = 30
STALL_PENALTY = 5
STALL_CAP = 15

# A story counts as stalled once it has sat open at 0% for this long.
STALL_DAYS = 14

# Momentum is the only upward force: 100% average progress is worth +10.
MOMENTUM_BONUS_MAX = 10

# Momentum is earned *up to* 100, not added on top of it. Scoring from a 90
# baseline is what stops a healthy-looking bonus silently cancelling a real
# penalty — at 100 - penalty + bonus, work that was 100% done with a live
# blocker clamped back to a perfect 100 and hid the blocker entirely.
BASELINE = 100 - MOMENTUM_BONUS_MAX

# How much the whole delivery picture may move a *client's* health. Delivery is
# one voice in the room, not the whole room.
CLIENT_MAX_PENALTY = 30
CLIENT_MAX_BONUS = 5

OPEN_STORY_STATUSES = ("todo", "in_progress", "blocked")
OPEN_TASK_STATUSES = ("todo", "in_progress", "blocked")
CLOSED_STATUSES = ("done", "cancelled")


def health_label(score: int) -> str:
    """The 0-100 → label mapping used at every level of the hierarchy."""
    return "on_track" if score >= 75 else "at_risk" if score >= 55 else "needs_attention" if score >= 35 else "critical"


def _days_since(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - dt).days)
    except (ValueError, TypeError):
        return None


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _is_overdue(task) -> bool:
    due = getattr(task, "due_date", None)
    if not due or getattr(task, "status", "") in CLOSED_STATUSES:
        return False
    return str(due)[:10] < _today()


def _is_stalled(story) -> bool:
    """Open, untouched, and nothing to show for it."""
    if story.status not in OPEN_STORY_STATUSES or story.progress_pct > 0:
        return False
    age = _days_since(story.updated_at or story.created_at)
    return age is not None and age >= STALL_DAYS


def _count(observations, kind: str) -> int:
    return sum(1 for o in observations if o.kind == kind)


# ── Level 1: story → task ───────────────────────────────────────────────────
def task_rollup(task, stories: list) -> dict:
    """Aggregate one task's stories. `stories` must already be filtered to it.

    A task with no stories still reports progress — from its own status — so the
    hierarchy degrades gracefully for work that was never broken down.
    """
    counted = [s for s in stories if s.status != "cancelled"]
    if counted:
        progress = round(sum(s.progress_pct for s in counted) / len(counted))
    else:
        progress = 100 if task.status == "done" else 0

    blockers = sum(_count(s.observations, "blocker") for s in stories)
    not_well = sum(_count(s.observations, "not_going_well") for s in stories)
    going_well = sum(_count(s.observations, "going_well") for s in stories)
    stalled = sum(1 for s in stories if _is_stalled(s))

    return {
        "taskId": task.id,
        "title": task.title,
        "status": task.status,
        "clientId": task.client_id,
        "engagementId": task.engagement_id,
        "progressPct": progress,
        "storyCount": len(stories),
        "openStoryCount": sum(1 for s in stories if s.status in OPEN_STORY_STATUSES),
        "doneStoryCount": sum(1 for s in stories if s.status == "done"),
        # A task flagged `blocked` counts as a blocker even with no story saying so.
        "blockerCount": blockers + (1 if task.status == "blocked" else 0),
        "notGoingWellCount": not_well,
        "goingWellCount": going_well,
        "stalledCount": stalled,
        "isOverdue": _is_overdue(task),
    }


# ── Level 2+3: the shared scoring core ──────────────────────────────────────
def _score_from(rollups: list[dict]) -> dict:
    """Turn a set of task roll-ups into one score + the reasons behind it.

    Used unchanged at project and client level — the arithmetic does not care
    whether the tasks came from one engagement or the whole account, which is
    why the hierarchy stays consistent as you zoom out.
    """
    if not rollups:
        # Nothing tracked yet is not a problem — it is an absence of evidence.
        return {
            "score": 100,
            "label": "on_track",
            "progressPct": 0,
            "taskCount": 0,
            "storyCount": 0,
            "blockerCount": 0,
            "notGoingWellCount": 0,
            "goingWellCount": 0,
            "overdueCount": 0,
            "stalledCount": 0,
            "penalty": 0,
            "bonus": 0,
            "risks": [],
            "positives": [],
            "hasData": False,
        }

    blockers = sum(r["blockerCount"] for r in rollups)
    not_well = sum(r["notGoingWellCount"] for r in rollups)
    going_well = sum(r["goingWellCount"] for r in rollups)
    stalled = sum(r["stalledCount"] for r in rollups)
    overdue = sum(1 for r in rollups if r["isOverdue"])
    stories = sum(r["storyCount"] for r in rollups)

    # Progress across everything not cancelled. Tasks are equal citizens here:
    # weighting by story count would let one heavily-split task dominate.
    active = [r for r in rollups if r["status"] != "cancelled"]
    progress = round(sum(r["progressPct"] for r in active) / len(active)) if active else 0

    penalty = (
        min(BLOCKER_CAP, blockers * BLOCKER_PENALTY)
        + min(NOT_GOING_WELL_CAP, not_well * NOT_GOING_WELL_PENALTY)
        + min(OVERDUE_CAP, overdue * OVERDUE_PENALTY)
        + min(STALL_CAP, stalled * STALL_PENALTY)
    )
    bonus = round(MOMENTUM_BONUS_MAX * progress / 100)
    score = max(0, min(100, BASELINE + bonus - penalty))

    risks: list[str] = []
    if blockers:
        risks.append(f"{blockers} active blocker(s) on delivery")
    if overdue:
        risks.append(f"{overdue} overdue task(s)")
    if stalled:
        risks.append(f"{stalled} story(ies) stalled at 0% for over {STALL_DAYS} days")
    if not_well:
        risks.append(f"{not_well} thing(s) flagged as not going well")

    positives: list[str] = []
    if progress >= 70:
        positives.append(f"Delivery {progress}% complete")
    if going_well:
        positives.append(f"{going_well} thing(s) flagged as going well")
    if active and not blockers and not overdue:
        positives.append("No blockers or overdue work")

    return {
        "score": score,
        "label": health_label(score),
        "progressPct": progress,
        "taskCount": len(rollups),
        "storyCount": stories,
        "blockerCount": blockers,
        "notGoingWellCount": not_well,
        "goingWellCount": going_well,
        "overdueCount": overdue,
        "stalledCount": stalled,
        # Exposed so the client-level delta can be built from the components
        # rather than from `score`, which is clamped at both ends.
        "penalty": penalty,
        "bonus": bonus,
        "risks": risks,
        "positives": positives,
        "hasData": True,
    }


def _rollups_for(user_id: str, tasks: list) -> list[dict]:
    """Build task roll-ups, fetching each task's stories in one grouped pass."""
    by_task: dict[str, list] = {}
    for t in tasks:
        by_task.setdefault(t.id, [])
    # One query for the whole set, then group in Python — avoids N+1 round trips
    # against Supabase when a client has many tasks.
    for s in store.list_stories(user_id):
        if s.task_id in by_task:
            by_task[s.task_id].append(s)
    return [task_rollup(t, by_task[t.id]) for t in tasks]


def project_rollup(user_id: str, engagement_id: str) -> dict:
    """Delivery health for one engagement (the 'project' level)."""
    tasks = store.list_tasks(user_id, engagement_id=engagement_id)
    out = _score_from(_rollups_for(user_id, tasks))
    out["engagementId"] = engagement_id
    return out


def client_rollup(user_id: str, client_id: str) -> dict:
    """Delivery health for one client — every task of theirs, project or not."""
    tasks = store.list_tasks(user_id, client_id=client_id)
    rollups = _rollups_for(user_id, tasks)
    out = _score_from(rollups)
    out["clientId"] = client_id
    out["tasks"] = rollups
    return out


def client_tree(user_id: str, client_id: str) -> dict:
    """The full Client → Project → Task shape the M4 workspace UI renders.

    Tasks with no engagement are surfaced under `unassignedTasks` rather than
    silently dropped — unfiled work is exactly the work that goes missing.
    """
    tasks = store.list_tasks(user_id, client_id=client_id)
    rollups = _rollups_for(user_id, tasks)
    by_id = {r["taskId"]: r for r in rollups}

    projects = []
    for e in store.list_engagements(user_id, client_id):
        members = [by_id[t.id] for t in tasks if t.engagement_id == e.id]
        node = _score_from(members)
        node.update({"engagementId": e.id, "title": e.title, "status": e.status, "tasks": members})
        projects.append(node)

    unassigned = [by_id[t.id] for t in tasks if not t.engagement_id]
    overall = _score_from(rollups)
    overall.update({"clientId": client_id, "projects": projects, "unassignedTasks": unassigned})
    return overall


# ── The bridge into the existing client health score ────────────────────────
def delivery_signal(user_id: str, client_id: str) -> dict:
    """Delivery's contribution to `butler.compute_client_health`.

    `healthDelta` is what the caller adds to its running score. It is built from
    the raw `bonus - penalty` rather than from `deliveryScore`, because that
    score is clamped at both ends: deriving the delta from it would charge a
    client 10 points merely for having new work sitting at 0%, which is not a
    problem — it is a Tuesday.

    It is clamped so delivery can dent a client's health but never dominate the
    money and silence signals that were there before, and it is exactly 0, with
    `hasDeliveryData=False`, when there is no delivery data to speak of. That
    zero is what makes this a strict extension rather than a behaviour change.
    """
    roll = client_rollup(user_id, client_id)
    if not roll["hasData"]:
        return {
            "healthDelta": 0,
            "hasDeliveryData": False,
            "risks": [],
            "positives": [],
            "deliveryScore": 100,
            "deliveryLabel": "on_track",
            "progressPct": 0,
            "blockerCount": 0,
            "overdueCount": 0,
        }

    delta = max(-CLIENT_MAX_PENALTY, min(CLIENT_MAX_BONUS, roll["bonus"] - roll["penalty"]))
    return {
        "healthDelta": delta,
        "hasDeliveryData": True,
        "deliveryScore": roll["score"],
        "deliveryLabel": roll["label"],
        "progressPct": roll["progressPct"],
        "blockerCount": roll["blockerCount"],
        "overdueCount": roll["overdueCount"],
        "risks": roll["risks"],
        "positives": roll["positives"],
    }
