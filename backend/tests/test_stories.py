"""Story layer — hierarchy, provenance, and the human-outranks-agent rule.

Maps to M1's success criteria in `.genesis/PLAN.md` and the invariants in
ADR-0001. The two tests that matter most are the provenance guard and
`apply_agent_observations` preserving user edits — those are what stop this
layer becoming untrustworthy prose.
"""
from __future__ import annotations

import pytest

from app import store
from app.services import story_ledger as SL
from app.services import task_ledger as TL


@pytest.fixture
def task(user_id):
    """A parent task carrying client + project scope, so inheritance is testable."""
    return TL.create_task(user_id, {
        "title": "Redesign the marketing site",
        "client_id": "client-acme",
        "engagement_id": "engagement-1",
    })


# ── Criterion 1 · CRUD under a parent, and the cascade rule ────────────────

def test_story_inherits_client_and_project_scope_from_its_task(user_id, task):
    story = SL.create_story(user_id, {"task_id": task.id, "title": "Build the hero section"})

    assert story.task_id == task.id
    # Denormalized so the roll-up and per-client views need no join.
    assert story.client_id == "client-acme"
    assert story.engagement_id == "engagement-1"
    assert story.status == "todo"
    assert story.progress_pct == 0
    assert story.observations == []


def test_a_story_cannot_be_orphaned_at_creation(user_id):
    with pytest.raises(ValueError, match="Parent task not found"):
        SL.create_story(user_id, {"task_id": "does-not-exist", "title": "Orphan"})


def test_deleting_a_task_cascades_to_its_stories(user_id, task):
    """Explicit cascade rule: a story is meaningless without its task.

    Postgres enforces this via ON DELETE CASCADE; the mock backend must match or
    the two backends diverge and orphan stories in mock mode only.
    """
    SL.create_story(user_id, {"task_id": task.id, "title": "Story A"})
    SL.create_story(user_id, {"task_id": task.id, "title": "Story B"})
    assert len(store.list_stories(user_id, task_id=task.id)) == 2

    store.delete_task(user_id, task.id)

    assert store.list_stories(user_id, task_id=task.id) == []


def test_stories_are_scopable_by_task_and_client(user_id, task):
    other = TL.create_task(user_id, {"title": "Other work", "client_id": "client-beta"})
    SL.create_story(user_id, {"task_id": task.id, "title": "Acme story"})
    SL.create_story(user_id, {"task_id": other.id, "title": "Beta story"})

    assert len(store.list_stories(user_id, task_id=task.id)) == 1
    assert len(store.list_stories(user_id, client_id="client-beta")) == 1
    assert len(store.list_stories(user_id)) == 2


# ── Criterion 2 · progress_pct is bounded ─────────────────────────────────

@pytest.mark.parametrize("given,expected", [(-10, 0), (0, 0), (55, 55), (100, 100), (250, 100)])
def test_progress_is_clamped_to_0_100(user_id, task, given, expected):
    story = SL.create_story(user_id, {"task_id": task.id, "title": "S", "progress_pct": given})
    assert story.progress_pct == expected

    updated = SL.update_story(user_id, story.id, {"progress_pct": given})
    assert updated.progress_pct == expected


def test_completing_a_story_sets_progress_and_completed_at(user_id, task):
    story = SL.create_story(user_id, {"task_id": task.id, "title": "S", "progress_pct": 40})

    done = SL.update_story(user_id, story.id, {"status": "done"})
    assert done.completed_at is not None
    assert done.progress_pct == 100, "finishing work left a stale progress figure"

    reopened = SL.update_story(user_id, story.id, {"status": "in_progress"})
    assert reopened.completed_at is None


# ── Criterion 3 · provenance is mandatory ─────────────────────────────────

def test_an_observation_without_evidence_is_refused(user_id, task):
    """ADR-0001 `qualitative_fields_carry_provenance`.

    An untraceable judgement is worse than none — nobody can verify or refresh it.
    """
    story = SL.create_story(user_id, {"task_id": task.id, "title": "S"})

    with pytest.raises(ValueError, match="source_ref is required"):
        SL.add_observation(user_id, story.id, kind="going_well",
                           text="Feels good", source="agent", source_ref="")

    assert store.get_story(user_id, story.id).observations == []


def test_an_observation_with_evidence_is_stored_with_its_pointer(user_id, task):
    story = SL.create_story(user_id, {"task_id": task.id, "title": "S"})

    updated = SL.add_observation(
        user_id, story.id, kind="blocker",
        text="Waiting on brand assets from the client",
        source="email", source_ref="gmail-msg-abc123",
    )

    obs = updated.observations[0]
    assert obs.kind == "blocker"
    assert obs.source == "email"
    assert obs.source_ref == "gmail-msg-abc123"
    assert obs.observed_at
    assert obs.user_edited is False


def test_blank_text_and_unknown_kind_are_refused(user_id, task):
    story = SL.create_story(user_id, {"task_id": task.id, "title": "S"})

    with pytest.raises(ValueError, match="text is required"):
        SL.add_observation(user_id, story.id, kind="blocker", text="  ",
                           source="email", source_ref="ref")

    with pytest.raises(ValueError, match="Unknown observation kind"):
        SL.add_observation(user_id, story.id, kind="vibes", text="x",
                           source="email", source_ref="ref")


# ── Criterion 4 · a human's judgement outranks the agent's ────────────────

def test_agent_refresh_preserves_user_edited_observations(user_id, task):
    """ADR-0001 `user_override_survives_agent_refresh`.

    Refreshes run nightly. Without this rule the agent would quietly revert the
    user's correction every single night.
    """
    story = SL.create_story(user_id, {"task_id": task.id, "title": "S"})

    SL.add_observation(user_id, story.id, kind="going_well", text="Agent's original take",
                       source="agent", source_ref="run-1")
    SL.add_observation(user_id, story.id, kind="going_well", text="Human's correction",
                       source="user", source_ref="manual", user_edited=True)

    refreshed = SL.apply_agent_observations(user_id, story.id, "going_well", [
        {"text": "Agent's new take", "source": "meeting", "source_ref": "meeting-9"},
    ])

    texts = [o.text for o in refreshed.observations]
    assert "Human's correction" in texts, "agent refresh destroyed a human judgement"
    assert "Agent's original take" not in texts, "stale agent observation survived the refresh"
    assert "Agent's new take" in texts


def test_agent_refresh_only_touches_the_kind_it_was_given(user_id, task):
    story = SL.create_story(user_id, {"task_id": task.id, "title": "S"})
    SL.add_observation(user_id, story.id, kind="blocker", text="Blocked on assets",
                       source="email", source_ref="msg-1")
    SL.add_observation(user_id, story.id, kind="going_well", text="Design approved",
                       source="meeting", source_ref="meeting-1")

    refreshed = SL.apply_agent_observations(user_id, story.id, "going_well", [])

    kinds = [o.kind for o in refreshed.observations]
    assert "blocker" in kinds, "refreshing going_well wiped an unrelated blocker"
    assert "going_well" not in kinds


def test_agent_refresh_drops_unprovenanced_entries_without_failing(user_id, task):
    """A partial analyst response should yield fewer observations, not an exception."""
    story = SL.create_story(user_id, {"task_id": task.id, "title": "S"})

    refreshed = SL.apply_agent_observations(user_id, story.id, "not_going_well", [
        {"text": "Traceable finding", "source": "email", "source_ref": "msg-7"},
        {"text": "Untraceable finding", "source": "agent"},          # no source_ref
        {"text": "", "source": "agent", "source_ref": "msg-8"},      # no text
    ])

    assert len(refreshed.observations) == 1
    assert refreshed.observations[0].text == "Traceable finding"


def test_editing_an_observation_marks_it_user_owned(user_id, task):
    story = SL.create_story(user_id, {"task_id": task.id, "title": "S"})
    story = SL.add_observation(user_id, story.id, kind="going_well", text="Agent take",
                               source="agent", source_ref="run-1")
    obs_id = story.observations[0].id

    edited = SL.edit_observation(user_id, story.id, obs_id, "Actually, here's the truth")

    assert edited.observations[0].text == "Actually, here's the truth"
    assert edited.observations[0].user_edited is True
    assert edited.observations[0].source == "user"

    # ...and it now survives a refresh.
    refreshed = SL.apply_agent_observations(user_id, story.id, "going_well", [])
    assert refreshed.observations[0].text == "Actually, here's the truth"


def test_removing_an_observation(user_id, task):
    story = SL.create_story(user_id, {"task_id": task.id, "title": "S"})
    story = SL.add_observation(user_id, story.id, kind="blocker", text="Gone soon",
                               source="email", source_ref="m1")

    updated = SL.remove_observation(user_id, story.id, story.observations[0].id)
    assert updated.observations == []


# ── Summary shape the M2 roll-up will consume ─────────────────────────────

def test_stats_report_progress_and_blockers(user_id, task):
    a = SL.create_story(user_id, {"task_id": task.id, "title": "A", "progress_pct": 100})
    SL.update_story(user_id, a.id, {"status": "done"})
    b = SL.create_story(user_id, {"task_id": task.id, "title": "B", "progress_pct": 20})
    SL.update_story(user_id, b.id, {"status": "blocked"})
    SL.add_observation(user_id, b.id, kind="blocker", text="Waiting on assets",
                       source="email", source_ref="m1")

    stats = SL.stats(user_id, task_id=task.id)

    assert stats["total"] == 2
    assert stats["done"] == 1
    assert stats["blocked"] == 1
    assert stats["blockerCount"] == 1
    assert stats["avgProgress"] == 60      # (100 + 20) / 2


def test_stats_on_an_empty_task_are_zeroed_not_crashing(user_id, task):
    assert SL.stats(user_id, task_id=task.id)["total"] == 0
    assert SL.stats(user_id, task_id=task.id)["avgProgress"] == 0


def test_story_summary_counts_each_kind(user_id, task):
    story = SL.create_story(user_id, {"task_id": task.id, "title": "S", "progress_pct": 30})
    SL.add_observation(user_id, story.id, kind="blocker", text="b", source="email", source_ref="1")
    SL.add_observation(user_id, story.id, kind="going_well", text="g", source="email", source_ref="2")
    SL.add_observation(user_id, story.id, kind="going_well", text="g2", source="email", source_ref="3")

    summary = SL.story_summary(store.get_story(user_id, story.id))

    assert summary["progressPct"] == 30
    assert summary["blockers"] == 1
    assert summary["goingWell"] == 2
    assert summary["notGoingWell"] == 0
