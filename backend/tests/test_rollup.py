"""Deterministic delivery roll-up: story → task → project → client.

Maps to M2's success criteria in `.genesis/PLAN.md`. The two tests that carry
the milestone are `test_rollup_makes_no_llm_calls` (the invariant
`rollup_health_is_deterministic`) and the strict-extension pin — everything
else is arithmetic and degenerate-input coverage.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import store
from app.models import Client, Engagement
from app.services import butler, rollup
from app.services import story_ledger as SL
from app.services import task_ledger as TL


def _iso_days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
def client(user_id):
    c = Client(id=store.uid("client"), user_id=user_id, name="Acme Corp",
               status="active", last_activity_at=_now(), created_at=_now())
    store.insert_client(c)
    return c


@pytest.fixture
def engagement(user_id, client):
    e = Engagement(id=store.uid("eng"), user_id=user_id, client_id=client.id,
                   title="Website rebuild", status="active", created_at=_now())
    store.insert_engagement(e)
    return e


@pytest.fixture
def task(user_id, client, engagement):
    return TL.create_task(user_id, {"title": "Build the site", "client_id": client.id,
                                    "engagement_id": engagement.id})


def _story(user_id, task, **kw):
    return SL.create_story(user_id, {"task_id": task.id, "title": kw.pop("title", "S"), **kw})


# ── Criterion 2 · the invariant: zero LLM calls ────────────────────────────

def test_rollup_makes_no_llm_calls(user_id, client, engagement, task, monkeypatch):
    """Invariant `rollup_health_is_deterministic`.

    Health is recomputed on every client page load and in cron. If it ever
    reached for a model it would cost money per view, add latency, and — worst —
    return two different numbers for identical inputs. `vertex_ai.get_ai` is the
    single dispatcher every LLM path in the app goes through, so tripping it
    catches any provider.
    """
    from app.services import llm, vertex_ai

    def boom(*a, **k):
        raise AssertionError("roll-up reached for an LLM; it must be pure arithmetic")

    monkeypatch.setattr(vertex_ai, "get_ai", boom)
    monkeypatch.setattr(llm, "chat", boom)
    monkeypatch.setattr(llm, "chat_messages", boom)
    monkeypatch.setattr(llm, "_get_client", boom)

    s = _story(user_id, task, progress_pct=50)
    SL.add_observation(user_id, s.id, kind="blocker", text="Waiting on assets",
                       source="email", source_ref="msg-1")

    rollup.client_rollup(user_id, client.id)
    rollup.project_rollup(user_id, engagement.id)
    rollup.client_tree(user_id, client.id)
    rollup.delivery_signal(user_id, client.id)
    butler.compute_client_health(user_id, client, persist=False)


def test_identical_input_gives_an_identical_score(user_id, client, task):
    """Determinism is not just 'no LLM' — the same ledger must give the same number."""
    _story(user_id, task, progress_pct=40)
    first = rollup.client_rollup(user_id, client.id)
    second = rollup.client_rollup(user_id, client.id)
    assert first == second


# ── Criterion 1 · changes propagate arithmetically up the hierarchy ────────

def test_progress_moves_task_project_and_client_together(user_id, client, engagement, task):
    a = _story(user_id, task, title="A", progress_pct=0)
    _story(user_id, task, title="B", progress_pct=0)

    base_task = rollup.task_rollup(task, store.list_stories(user_id, task_id=task.id))
    base_project = rollup.project_rollup(user_id, engagement.id)
    base_client = rollup.client_rollup(user_id, client.id)
    assert base_task["progressPct"] == 0

    SL.update_story(user_id, a.id, {"progress_pct": 100})

    new_task = rollup.task_rollup(task, store.list_stories(user_id, task_id=task.id))
    new_project = rollup.project_rollup(user_id, engagement.id)
    new_client = rollup.client_rollup(user_id, client.id)

    # Task: mean of (100, 0). Predictable, not merely "higher".
    assert new_task["progressPct"] == 50
    assert new_project["progressPct"] == 50
    assert new_client["progressPct"] == 50
    # Momentum is worth MOMENTUM_BONUS_MAX at 100%, so 50% is worth half of it.
    assert new_project["score"] - base_project["score"] == round(
        rollup.MOMENTUM_BONUS_MAX * 50 / 100)
    assert new_client["score"] > base_client["score"]


def test_adding_a_blocker_costs_exactly_one_blocker_penalty(user_id, client, engagement, task):
    s = _story(user_id, task, progress_pct=0)
    before = rollup.project_rollup(user_id, engagement.id)["score"]

    SL.add_observation(user_id, s.id, kind="blocker", text="Client hasn't sent assets",
                       source="email", source_ref="msg-1")

    after = rollup.project_rollup(user_id, engagement.id)
    assert before - after["score"] == rollup.BLOCKER_PENALTY
    assert after["blockerCount"] == 1
    assert any("blocker" in r for r in after["risks"])


def test_a_blocked_task_with_no_stories_still_counts_as_blocked(user_id, task):
    """The signal must not depend on the user having broken work into stories."""
    TL.update_task(user_id, task.id, {"status": "blocked"})
    refreshed = store.get_task(user_id, task.id)

    roll = rollup.task_rollup(refreshed, [])
    assert roll["blockerCount"] == 1


def test_penalties_are_capped_so_one_category_cannot_sink_a_score(user_id, client, task):
    s = _story(user_id, task, progress_pct=0)
    for i in range(20):
        SL.add_observation(user_id, s.id, kind="blocker", text=f"blocker {i}",
                           source="email", source_ref=f"msg-{i}")

    roll = rollup.client_rollup(user_id, client.id)
    assert roll["blockerCount"] == 20
    # 20 * 8 = 160 uncapped, which would floor the score at 0 and lose all nuance.
    assert roll["score"] == rollup.BASELINE - rollup.BLOCKER_CAP


def test_overdue_tasks_are_penalised(user_id, client, task):
    TL.update_task(user_id, task.id, {"due_date": _iso_days_ago(3)[:10]})
    roll = rollup.client_rollup(user_id, client.id)

    assert roll["overdueCount"] == 1
    assert roll["score"] == rollup.BASELINE - rollup.OVERDUE_PENALTY
    assert any("overdue" in r for r in roll["risks"])


def test_a_story_open_at_zero_for_two_weeks_is_stalled(user_id, client, task):
    s = _story(user_id, task, progress_pct=0)
    store.update_story(user_id, s.id, {"updated_at": _iso_days_ago(rollup.STALL_DAYS + 1)})

    roll = rollup.client_rollup(user_id, client.id)
    assert roll["stalledCount"] == 1
    assert roll["score"] == rollup.BASELINE - rollup.STALL_PENALTY


def test_a_recently_touched_story_is_not_stalled(user_id, client, task):
    _story(user_id, task, progress_pct=0)
    assert rollup.client_rollup(user_id, client.id)["stalledCount"] == 0


# ── Criterion 3 · strict extension of the existing health score ────────────

def test_client_with_no_delivery_data_scores_exactly_as_before(user_id, client):
    """The pin. A client with no tasks and no stories must be untouched by M2.

    This is what makes the delivery signal an extension rather than a rewrite:
    every previously-correct score is still that score.
    """
    signal = rollup.delivery_signal(user_id, client.id)
    assert signal["hasDeliveryData"] is False
    assert signal["healthDelta"] == 0
    assert signal["risks"] == [] and signal["positives"] == []

    health = butler.compute_client_health(user_id, client, persist=False)
    # Active client, no invoices, no engagements, activity today → the pre-M2
    # path subtracts nothing.
    assert health["healthScore"] == 100
    assert health["healthLabel"] == "on_track"


def test_money_and_silence_signals_still_apply_alongside_delivery(user_id, client, task):
    """Delivery is added to the old signals, never substituted for them."""
    store.update_client(user_id, client.id, {"last_activity_at": _iso_days_ago(60)})
    silent_client = store.get_client(user_id, client.id)

    s = _story(user_id, task, progress_pct=0)
    SL.add_observation(user_id, s.id, kind="blocker", text="Blocked",
                       source="email", source_ref="m1")

    health = butler.compute_client_health(user_id, silent_client, persist=False)

    # Both voices are audible in the result.
    assert any("No activity logged" in r for r in health["risks"]), "silence signal was lost"
    assert any("blocker" in r for r in health["risks"]), "delivery signal missing"
    assert health["healthScore"] == 100 - 15 - rollup.BLOCKER_PENALTY


def test_delivery_contribution_is_clamped(user_id, client, task):
    """A catastrophic delivery picture dents health; it does not own it."""
    s = _story(user_id, task, progress_pct=0)
    for i in range(20):
        SL.add_observation(user_id, s.id, kind="blocker", text=f"b{i}",
                           source="email", source_ref=f"m{i}")
    for i in range(20):
        SL.add_observation(user_id, s.id, kind="not_going_well", text=f"n{i}",
                           source="email", source_ref=f"n{i}")

    signal = rollup.delivery_signal(user_id, client.id)
    assert signal["deliveryScore"] == rollup.BASELINE - rollup.BLOCKER_CAP - rollup.NOT_GOING_WELL_CAP
    assert signal["healthDelta"] == -rollup.CLIENT_MAX_PENALTY


def test_delivery_bonus_is_clamped(user_id, client, task):
    _story(user_id, task, progress_pct=100)
    signal = rollup.delivery_signal(user_id, client.id)

    assert signal["deliveryScore"] == 100                        # BASELINE + full momentum
    # Flawless delivery is worth a nudge, not a rescue.
    assert signal["healthDelta"] == rollup.CLIENT_MAX_BONUS


# ── Criterion 4 · degenerate inputs are defined, not crashes ───────────────

def test_project_with_no_tasks_is_neutral(user_id, engagement):
    roll = rollup.project_rollup(user_id, engagement.id)
    assert roll["hasData"] is False
    assert roll["score"] == 100
    assert roll["progressPct"] == 0
    assert roll["risks"] == []


def test_task_with_no_stories_derives_progress_from_its_status(user_id, task):
    assert rollup.task_rollup(task, [])["progressPct"] == 0

    TL.update_task(user_id, task.id, {"status": "done"})
    assert rollup.task_rollup(store.get_task(user_id, task.id), [])["progressPct"] == 100


def test_fully_complete_work_with_an_open_blocker_is_not_healthy(user_id, client, task):
    """The nastiest degenerate case: 100% done on paper, still stuck in reality."""
    s = _story(user_id, task, progress_pct=100)
    SL.update_story(user_id, s.id, {"status": "done"})
    SL.add_observation(user_id, s.id, kind="blocker", text="Client won't sign off",
                       source="email", source_ref="m1")

    roll = rollup.client_rollup(user_id, client.id)
    assert roll["progressPct"] == 100
    assert roll["blockerCount"] == 1
    assert roll["score"] < 100, "100% progress masked a live blocker"
    assert roll["score"] == rollup.BASELINE + rollup.MOMENTUM_BONUS_MAX - rollup.BLOCKER_PENALTY


def test_cancelled_stories_are_excluded_from_progress(user_id, task):
    a = _story(user_id, task, title="A", progress_pct=100)
    b = _story(user_id, task, title="B", progress_pct=0)
    SL.update_story(user_id, b.id, {"status": "cancelled"})

    stories = store.list_stories(user_id, task_id=task.id)
    # Mean of the live story only — a cancelled story must not drag delivery to 50%.
    assert rollup.task_rollup(task, stories)["progressPct"] == 100
    assert a.progress_pct == 100


def test_client_with_no_tasks_at_all_does_not_crash(user_id, client):
    roll = rollup.client_rollup(user_id, client.id)
    assert roll["hasData"] is False and roll["taskCount"] == 0
    tree = rollup.client_tree(user_id, client.id)
    assert tree["projects"] == [] and tree["unassignedTasks"] == []


# ── The tree the M4 UI will render ─────────────────────────────────────────

def test_client_tree_nests_projects_and_surfaces_unfiled_work(user_id, client, engagement, task):
    """Unfiled work is exactly the work that goes missing, so it must be visible."""
    _story(user_id, task, progress_pct=60)
    loose = TL.create_task(user_id, {"title": "Ad-hoc favour", "client_id": client.id})

    tree = rollup.client_tree(user_id, client.id)

    assert len(tree["projects"]) == 1
    project = tree["projects"][0]
    assert project["engagementId"] == engagement.id
    assert project["title"] == "Website rebuild"
    assert [t["taskId"] for t in project["tasks"]] == [task.id]
    assert project["progressPct"] == 60

    assert [t["taskId"] for t in tree["unassignedTasks"]] == [loose.id]
    assert tree["taskCount"] == 2


def test_stories_of_another_client_never_leak_into_a_rollup(user_id, client, task):
    other_client = Client(id=store.uid("client"), user_id=user_id, name="Beta Inc",
                          status="active", created_at=_now())
    store.insert_client(other_client)
    other_task = TL.create_task(user_id, {"title": "Beta work", "client_id": other_client.id})
    other = _story(user_id, other_task, progress_pct=0)
    SL.add_observation(user_id, other.id, kind="blocker", text="Beta is blocked",
                       source="email", source_ref="beta-1")
    _story(user_id, task, progress_pct=100)

    roll = rollup.client_rollup(user_id, client.id)
    assert roll["blockerCount"] == 0, "another client's blocker bled into this score"
    assert roll["taskCount"] == 1
