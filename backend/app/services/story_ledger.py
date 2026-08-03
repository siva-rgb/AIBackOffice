"""Story ledger — the unit of work that carries progress and qualitative status.

This is the layer that makes the Client → Project → Task → Story hierarchy
*self-filling* rather than a set of empty boxes. Two rules from ADR-0001 do the
load-bearing work, and both are enforced here rather than left to callers:

**1. Provenance is mandatory.** Every observation ("this is going well", "this is
blocked") must cite the email / meeting / document that produced it. An
observation nobody can trace is refused, not silently stored. Without this the
layer decays into unfalsifiable prose that nobody trusts or updates.

**2. A human's judgement outranks the agent's.** Once someone edits an
observation it is flagged `user_edited`, and `apply_agent_observations` will
never overwrite or delete it — the agent may add alongside it, never silently
replace it. Refreshes run nightly, so without this rule the agent would quietly
undo the user's corrections every night.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from .. import store
from ..models import Story, StoryObservation

OPEN_STATUSES = ["todo", "in_progress", "blocked"]
KINDS = ("blocker", "going_well", "not_going_well")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp_pct(value) -> int:
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return 0


# ── CRUD ────────────────────────────────────────────────────────────────────
def create_story(user_id: str, data: dict) -> Story:
    """Create a story under a task, inheriting the task's client/project scope.

    The parent must exist — a story with a dangling `task_id` could never be
    reached through the hierarchy, and Postgres would reject it anyway.
    """
    task_id = data.get("task_id")
    task = store.get_task(user_id, task_id) if task_id else None
    if not task:
        raise ValueError("Parent task not found")

    story = Story(
        id=store.uid("story"),
        user_id=user_id,
        task_id=task_id,
        # Denormalized from the parent so the roll-up and per-client views can
        # scope without a join.
        client_id=task.client_id,
        engagement_id=task.engagement_id,
        title=str(data.get("title", "")).strip()[:300] or "Untitled story",
        description_md=data.get("description_md"),
        status=data.get("status", "todo"),
        progress_pct=_clamp_pct(data.get("progress_pct", 0)),
        observations=[],
        created_at=_now(),
        updated_at=_now(),
    )
    store.insert_story(story)
    return story


def update_story(user_id: str, story_id: str, patch: dict) -> Story | None:
    """Patch a story. Keeps `completed_at` and `progress_pct` internally consistent."""
    patch = {k: v for k, v in patch.items() if v is not None}
    if not patch:
        return store.get_story(user_id, story_id)

    if "progress_pct" in patch:
        patch["progress_pct"] = _clamp_pct(patch["progress_pct"])

    if patch.get("status") == "done":
        patch.setdefault("completed_at", _now())
        # Finishing the work means it is complete — don't leave a stale 40%.
        patch.setdefault("progress_pct", 100)
    elif "status" in patch:
        patch["completed_at"] = None

    patch["updated_at"] = _now()
    return store.update_story(user_id, story_id, patch)


def list_stories(user_id: str, **filters) -> list[Story]:
    return store.list_stories(user_id, **filters)


def delete_story(user_id: str, story_id: str) -> bool:
    return store.delete_story(user_id, story_id)


# ── Observations (the qualitative layer) ────────────────────────────────────
def add_observation(user_id: str, story_id: str, *, kind: str, text: str, source: str, source_ref: str, user_edited: bool = False) -> Story | None:
    """Attach one evidence-backed observation to a story.

    Raises `ValueError` when `source_ref` is missing — enforcing ADR-0001's
    `qualitative_fields_carry_provenance` at the service layer as well as in the
    Pydantic model, so an internal caller can't bypass what the API rejects.
    """
    if kind not in KINDS:
        raise ValueError(f"Unknown observation kind '{kind}'")
    if not (text or "").strip():
        raise ValueError("Observation text is required")
    if not (source_ref or "").strip():
        raise ValueError("source_ref is required — an observation must cite the email, meeting " "or document it came from")

    story = store.get_story(user_id, story_id)
    if not story:
        return None

    entry = StoryObservation(
        id=str(uuid.uuid4()),
        kind=kind,
        text=text.strip()[:1000],
        source=source,
        source_ref=source_ref.strip()[:300],
        observed_at=_now(),
        user_edited=user_edited,
    )
    return store.update_story(
        user_id,
        story_id,
        {
            "observations": list(story.observations) + [entry],
            "updated_at": _now(),
        },
    )


def edit_observation(user_id: str, story_id: str, observation_id: str, text: str) -> Story | None:
    """A human corrects an observation — flags it so agent refreshes leave it alone."""
    story = store.get_story(user_id, story_id)
    if not story:
        return None
    updated = []
    for o in story.observations:
        if o.id == observation_id:
            o = o.model_copy(
                update={
                    "text": (text or "").strip()[:1000] or o.text,
                    "user_edited": True,
                    "source": "user",
                    "observed_at": _now(),
                }
            )
        updated.append(o)
    return store.update_story(user_id, story_id, {"observations": updated, "updated_at": _now()})


def remove_observation(user_id: str, story_id: str, observation_id: str) -> Story | None:
    story = store.get_story(user_id, story_id)
    if not story:
        return None
    kept = [o for o in story.observations if o.id != observation_id]
    return store.update_story(user_id, story_id, {"observations": kept, "updated_at": _now()})


def apply_agent_observations(user_id: str, story_id: str, kind: str, entries: list[dict]) -> Story | None:
    """Replace the *agent-authored* observations of one kind, preserving human ones.

    This is what the nightly fan-out (M3) calls. The merge rule is the whole
    point: entries a human touched (`user_edited`) survive untouched, so the
    agent can refresh its own view of the world every night without ever quietly
    reverting a correction someone made.

    Entries missing `source_ref` are skipped rather than raising — a partial
    analyst response should degrade to fewer observations, not fail the refresh.
    """
    if kind not in KINDS:
        raise ValueError(f"Unknown observation kind '{kind}'")
    story = store.get_story(user_id, story_id)
    if not story:
        return None

    # Keep: everything of another kind, plus this kind's human-owned entries.
    kept = [o for o in story.observations if o.kind != kind or o.user_edited]

    fresh: list[StoryObservation] = []
    for e in entries or []:
        text = str(e.get("text", "")).strip()
        source_ref = str(e.get("source_ref", "")).strip()
        if not text or not source_ref:
            continue  # unprovenanced → dropped, never invented
        fresh.append(
            StoryObservation(
                id=str(uuid.uuid4()),
                kind=kind,
                text=text[:1000],
                source=e.get("source", "agent"),
                source_ref=source_ref[:300],
                observed_at=_now(),
                user_edited=False,
            )
        )

    return store.update_story(
        user_id,
        story_id,
        {
            "observations": kept + fresh,
            "updated_at": _now(),
        },
    )


# ── Read helpers ────────────────────────────────────────────────────────────
def observations_of(story: Story, kind: str) -> list[StoryObservation]:
    return [o for o in story.observations if o.kind == kind]


def story_summary(story: Story) -> dict:
    """Compact per-story shape for the UI and the M2 roll-up."""
    return {
        "id": story.id,
        "title": story.title,
        "status": story.status,
        "progressPct": story.progress_pct,
        "blockers": len(observations_of(story, "blocker")),
        "goingWell": len(observations_of(story, "going_well")),
        "notGoingWell": len(observations_of(story, "not_going_well")),
    }


def stats(user_id: str, *, task_id: str | None = None, client_id: str | None = None) -> dict:
    stories = store.list_stories(user_id, task_id=task_id, client_id=client_id)
    if not stories:
        return {"total": 0, "open": 0, "done": 0, "blocked": 0, "avgProgress": 0, "blockerCount": 0}
    open_stories = [s for s in stories if s.status in OPEN_STATUSES]
    return {
        "total": len(stories),
        "open": len(open_stories),
        "done": sum(1 for s in stories if s.status == "done"),
        "blocked": sum(1 for s in stories if s.status == "blocked"),
        # Mean progress across every non-cancelled story — M2 refines this into
        # a weighted roll-up; here it is just a readable headline number.
        "avgProgress": round(
            sum(s.progress_pct for s in stories if s.status != "cancelled") / max(1, len([s for s in stories if s.status != "cancelled"]))
        ),
        "blockerCount": sum(len(observations_of(s, "blocker")) for s in stories),
    }
