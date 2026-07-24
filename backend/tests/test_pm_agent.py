"""PM agent fan-out — parallelism, isolation, number safety, caching, budget.

Maps to M3's success criteria in `.genesis/PLAN.md` and the invariant
`client_view_refresh_is_cached`. The load-bearing tests are:
 * `test_analysts_run_in_parallel` — a barrier that deadlocks if they're serial
 * `test_one_analyst_failing_degrades_only_its_section` — the reliability property
 * `test_fabricated_figures_are_stripped` — no number originates from a model
 * `test_get_view_makes_no_llm_calls` — the caching invariant

`chat` is injected everywhere so these run with no gateway; the fakes return
`llm.LLMResult`s with known token counts.
"""
from __future__ import annotations

import threading

import pytest

from app import store
from app.models import Client, Engagement
from app.services import llm, pm_agent
from app.services import story_ledger as SL
from app.services import task_ledger as TL


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
def client(user_id):
    c = Client(id=store.uid("client"), user_id=user_id, name="Acme Corp",
               status="active", last_activity_at=_now(), created_at=_now())
    store.insert_client(c)
    return c


@pytest.fixture
def loaded_client(user_id, client):
    """A client with real delivery + money signals so analysts have facts."""
    e = Engagement(id=store.uid("eng"), user_id=user_id, client_id=client.id,
                   title="Website", status="active", created_at=_now())
    store.insert_engagement(e)
    task = TL.create_task(user_id, {"title": "Build site", "client_id": client.id,
                                    "engagement_id": e.id})
    s = SL.create_story(user_id, {"task_id": task.id, "title": "Hero", "progress_pct": 40})
    SL.add_observation(user_id, s.id, kind="blocker", text="Waiting on brand assets",
                       source="email", source_ref="msg-1")
    return client


def _fake_chat(text='{"summary": "ok", "highlights": [], "concerns": []}',
               *, in_tok=100, out_tok=50):
    """A stand-in for llm.chat returning a canned JSON body + fixed token counts."""
    def chat(system, user, **kw):
        return llm.LLMResult(text=text, input_tokens=in_tok, output_tokens=out_tok,
                             latency_ms=1, model="fake")
    return chat


@pytest.fixture(autouse=True)
def _force_configured(monkeypatch):
    """Analysts short-circuit to a fallback when the gateway is unconfigured; in
    tests we inject a fake `chat`, so pretend it's configured to exercise the
    real LLM path. Keep embeddings OFF, though — recall must stay lexical so no
    test reaches for the (blank) gateway."""
    monkeypatch.setattr(llm, "is_configured", lambda: True)
    from app.services import embeddings
    monkeypatch.setattr(embeddings, "is_enabled", lambda: False)


# ── Criterion 1 · four analysts run in parallel ────────────────────────────

def test_analysts_run_in_parallel(user_id, loaded_client):
    """A barrier of 4 only releases if all four are in-flight at once. If the
    fan-out were a sequential loop this would deadlock and time out."""
    barrier = threading.Barrier(len(pm_agent.ANALYST_KEYS), timeout=5)

    def chat(system, user, **kw):
        barrier.wait()  # blocks until all four analysts reach here together
        return llm.LLMResult('{"summary":"parallel","highlights":[],"concerns":[]}',
                             80, 40, 1, "fake")

    view = pm_agent.compose_client_view(user_id, loaded_client.id, chat=chat)
    assert view is not None
    assert view["degradedSections"] == []          # nobody timed out on the barrier
    for k in pm_agent.ANALYST_KEYS:
        assert view["sections"][k]["summary"] == "parallel"


def test_all_four_sections_are_present(user_id, loaded_client):
    view = pm_agent.compose_client_view(user_id, loaded_client.id, chat=_fake_chat())
    assert set(view["sections"].keys()) == set(pm_agent.ANALYST_KEYS)


# ── Criterion 2 · one analyst failing degrades only its section ────────────

def test_one_analyst_failing_degrades_only_its_section(user_id, loaded_client):
    """The reliability property: a blown analyst must not take the view down."""
    def flaky_chat(system, user, **kw):
        if system.startswith("You are the Money"):
            raise RuntimeError("gateway exploded for Money only")
        return llm.LLMResult('{"summary":"fine","highlights":[],"concerns":[]}',
                             90, 45, 1, "fake")

    view = pm_agent.compose_client_view(user_id, loaded_client.id, chat=flaky_chat)

    assert view["degradedSections"] == ["money"]
    assert view["sections"]["money"]["degraded"] is True
    # The failed section still carries deterministic, number-safe fallback prose…
    assert view["sections"]["money"]["summary"]
    assert view["sections"]["money"]["metrics"]        # …and its real metrics.
    # …and the other three are healthy.
    for k in ("delivery", "relationship", "risk"):
        assert view["sections"][k]["degraded"] is False
        assert view["sections"][k]["summary"] == "fine"


def test_compose_never_raises_even_if_every_analyst_dies(user_id, loaded_client):
    def dead(system, user, **kw):
        raise RuntimeError("total outage")

    view = pm_agent.compose_client_view(user_id, loaded_client.id, chat=dead)
    assert sorted(view["degradedSections"]) == sorted(pm_agent.ANALYST_KEYS)
    # Headline numbers still come from the ledger, so the page is never blank.
    assert view["headline"]["healthScore"] is not None
    assert view["tokenCost"]["totalTokens"] == 0


# ── Criterion 3 · no figure originates from an LLM ─────────────────────────

def test_fabricated_figures_are_stripped(user_id, loaded_client):
    """An analyst inventing a dollar amount must never reach the user as fact."""
    liar = _fake_chat(
        '{"summary": "Client owes $99,999 and is 87% done, per my estimate.",'
        ' "highlights": ["Revenue could hit $1,200,000"], "concerns": []}'
    )
    view = pm_agent.compose_client_view(user_id, loaded_client.id, chat=liar)

    money = view["sections"]["money"]["summary"]
    assert "$99,999" not in money
    assert "87%" not in money
    assert "[unverified]" in money
    assert "$1,200,000" not in view["sections"]["money"]["highlights"][0]


def test_strip_keeps_a_correct_figure_that_matches_the_ledger():
    allowed = {"$3,000", "40%", "5"}
    text = "They owe $3,000 and delivery is 40% complete across 5 tasks."
    out = pm_agent._strip_unverified_figures(text, allowed)
    assert out == text            # every figure is real → untouched


def test_strip_redacts_only_the_unverified_figure():
    allowed = {"$3,000"}
    text = "Owed $3,000 but forecast is $50,000."
    out = pm_agent._strip_unverified_figures(text, allowed)
    assert "$3,000" in out and "$50,000" not in out and "[unverified]" in out


def test_a_kept_currency_figure_is_not_cannibalised_by_a_later_pattern():
    """Single-pass guard: keeping "$3,000" must not leave "3,000" to be
    re-scanned and wrongly redacted when only the $-form is allow-listed."""
    out = pm_agent._strip_unverified_figures("Owed $3,000.", {"$3,000"})
    assert out == "Owed $3,000."


@pytest.mark.parametrize("bad", [
    "USD 99,999", "99,999.00", "1,200,000", "500000", "87 percent", "$99,999",
])
def test_fabricated_figures_are_stripped_in_any_money_or_percent_form(bad):
    """A hallucination is off-brief and can use any format, not just $X / X%."""
    out = pm_agent._strip_unverified_figures(f"forecast is {bad} next quarter", set())
    assert bad not in out and "[unverified]" in out


@pytest.mark.parametrize("kept", [
    "since 2024", "across 5 tasks", "3 blockers", "closed 12 tickets",
])
def test_years_and_small_counts_are_not_redacted(kept):
    """Guard against over-redaction: 4-digit years and small counts survive."""
    out = pm_agent._strip_unverified_figures(f"Progress {kept} this month.", set())
    assert out == f"Progress {kept} this month."


def test_headline_numbers_come_from_the_ledger_not_the_model(user_id, loaded_client):
    """Even a model screaming a wrong score cannot move the headline."""
    liar = _fake_chat('{"summary": "health is 100/100!", "highlights": [], "concerns": []}')
    view = pm_agent.compose_client_view(user_id, loaded_client.id, chat=liar)
    # Real health: one blocked story on an otherwise-healthy client, well under 100.
    assert view["headline"]["healthScore"] < 100
    assert view["headline"]["openBlockers"] == 1
    assert view["headline"]["progressPct"] == 40


# ── Criterion 4 · GET serves cache with zero LLM; refresh recomposes ───────

def test_get_view_makes_no_llm_calls(user_id, loaded_client, monkeypatch):
    """Invariant `client_view_refresh_is_cached`: reading is free."""
    def boom(*a, **k):
        raise AssertionError("GET reached for an LLM; it must serve cache only")

    monkeypatch.setattr(llm, "chat", boom)
    from app.services import vertex_ai
    monkeypatch.setattr(vertex_ai, "get_ai", boom)

    # Cold cache: a deterministic shell, still no model call.
    shell = pm_agent.get_client_view(user_id, loaded_client.id)
    assert shell["stale"] is True
    assert shell["headline"]["progressPct"] == 40

    # Now populate the cache with a refresh, then read it back — still no LLM.
    pm_agent.compose_client_view(user_id, loaded_client.id, chat=_fake_chat())
    cached = pm_agent.get_client_view(user_id, loaded_client.id)
    assert cached["stale"] is False


def test_refresh_writes_a_cache_that_get_reads_back(user_id, loaded_client):
    composed = pm_agent.compose_client_view(
        user_id, loaded_client.id,
        chat=_fake_chat('{"summary":"cached body","highlights":[],"concerns":[]}'))
    assert composed["sections"]["delivery"]["summary"] == "cached body"

    served = pm_agent.get_client_view(user_id, loaded_client.id)
    assert served["sections"]["delivery"]["summary"] == "cached body"
    assert served["stale"] is False
    assert served["refreshedAt"]


def test_deleting_a_client_cascades_to_its_cached_view(user_id, loaded_client):
    pm_agent.compose_client_view(user_id, loaded_client.id, chat=_fake_chat())
    assert store.get_client_view(user_id, loaded_client.id) is not None

    store.delete_client(user_id, loaded_client.id)
    assert store.get_client_view(user_id, loaded_client.id) is None


def test_get_view_on_a_missing_client_is_none(user_id):
    assert pm_agent.get_client_view(user_id, "does-not-exist") is None


def test_get_view_degrades_to_shell_when_the_cache_read_fails(user_id, loaded_client, monkeypatch):
    """A missing cache table (migration not yet applied) or a transient read
    error must never fault a page load — it falls back to the shell.

    Found live: the cache *write* was guarded but the *read* was not, so GET
    crashed against a project without the table."""
    def boom(*a, **k):
        raise RuntimeError("relation \"client_view_cache\" does not exist")

    monkeypatch.setattr(store, "get_client_view", boom)

    view = pm_agent.get_client_view(user_id, loaded_client.id)
    assert view is not None
    assert view["stale"] is True
    assert view["headline"]["progressPct"] == 40   # real numbers still served


# ── Criterion 5 · token cost is measured and capped ────────────────────────

def test_token_cost_is_summed_across_all_analysts(user_id, loaded_client):
    view = pm_agent.compose_client_view(
        user_id, loaded_client.id, chat=_fake_chat(in_tok=100, out_tok=50))
    tc = view["tokenCost"]
    # Four analysts × (100 in + 50 out).
    assert tc["inputTokens"] == 400
    assert tc["outputTokens"] == 200
    assert tc["totalTokens"] == 600
    assert tc["estUsd"] > 0


def test_a_normal_refresh_is_within_the_budget_cap(user_id, loaded_client):
    view = pm_agent.compose_client_view(
        user_id, loaded_client.id, chat=_fake_chat(in_tok=900, out_tok=600))
    tc = view["tokenCost"]
    assert tc["totalTokens"] == 4 * 1500
    assert tc["totalTokens"] <= pm_agent.TOKEN_CAP_PER_REFRESH
    assert tc["withinCap"] is True


def test_an_over_budget_refresh_is_flagged_not_hidden(user_id, loaded_client):
    """The cap is observable: a blown budget sets withinCap False rather than
    silently passing."""
    view = pm_agent.compose_client_view(
        user_id, loaded_client.id, chat=_fake_chat(in_tok=5000, out_tok=1000))
    tc = view["tokenCost"]
    assert tc["totalTokens"] == 4 * 6000
    assert tc["totalTokens"] > pm_agent.TOKEN_CAP_PER_REFRESH
    assert tc["withinCap"] is False


def test_degraded_analysts_cost_zero_tokens(user_id, loaded_client):
    def dead(system, user, **kw):
        raise RuntimeError("outage")

    view = pm_agent.compose_client_view(user_id, loaded_client.id, chat=dead)
    assert view["tokenCost"]["totalTokens"] == 0


# ── Cron fan-out ───────────────────────────────────────────────────────────

def test_refresh_all_covers_every_client(user_id, loaded_client):
    other = Client(id=store.uid("client"), user_id=user_id, name="Beta Inc",
                   status="active", created_at=_now())
    store.insert_client(other)

    result = pm_agent.refresh_all_views(user_id, chat=_fake_chat())
    assert result["ok"] is True
    assert result["clientsRefreshed"] == 2
    assert result["totalTokens"] == 2 * 600   # 2 clients × 4 analysts × 150
