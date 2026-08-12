"""Vertex AI transport: selection, shape compatibility, and offline safety.

The agents call `ai_backend.active()`, which returns either `llm` (OpenAI
Chat Completions against a gateway) or `vertex_llm` (Gemini). Both must expose
the same functions and return the same dataclasses, because `supervisor.py`'s
tool loop reads `tc.function.arguments` as a JSON *string* and appends messages
in OpenAI shape regardless of which one served the turn.

Nothing here touches the network: the Vertex SDK is faked at the module boundary.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.services import ai_backend, cost, llm, vertex_llm


@pytest.fixture(autouse=True)
def _reset_caches(monkeypatch):
    """`is_configured` and the vertexai.init guard are process-cached."""
    monkeypatch.setattr(vertex_llm, "_configured", None, raising=False)
    monkeypatch.setattr(vertex_llm, "_project_cache", None, raising=False)
    monkeypatch.setattr(vertex_llm, "_initialised", True, raising=False)  # never call vertexai.init


# ── backend selection ───────────────────────────────────────────────────────


class TestSelection:
    @pytest.mark.parametrize(
        "backend,vertex_ok,expected",
        [
            ("vertex", True, "vertex"),
            ("vertex", False, "vertex"),  # forced: fails loudly rather than silently using the gateway
            ("openai", True, "gateway"),
            ("mock", True, "gateway"),  # real-vs-mock is get_ai()'s call, not the router's
            ("auto", True, "vertex"),
            ("auto", False, "gateway"),
        ],
    )
    def test_router_picks_the_right_transport(self, monkeypatch, settings, backend, vertex_ok, expected):
        monkeypatch.setattr(settings, "KORA_AI_BACKEND", backend)
        monkeypatch.setattr(vertex_llm, "is_configured", lambda: vertex_ok)
        assert ai_backend.active() is (vertex_llm if expected == "vertex" else llm)

    def test_get_ai_falls_back_to_mock_when_nothing_is_configured(self, monkeypatch, settings):
        from app.services import vertex_ai

        monkeypatch.setattr(settings, "KORA_AI_BACKEND", "vertex")
        monkeypatch.setattr(vertex_llm, "is_configured", lambda: False)
        monkeypatch.setattr(vertex_ai, "_instance", None)
        assert vertex_ai.get_ai().__class__.__name__ == "MockGemini"


class TestModelName:
    def test_uses_a_gemini_model_name_as_given(self, monkeypatch, settings):
        monkeypatch.setattr(settings, "MODEL_NAME", "gemini-2.5-pro")
        assert vertex_llm.model_name() == "gemini-2.5-pro"

    @pytest.mark.parametrize("stale", ["azure.gpt-4.1", "azure.gpt-4o-mini", ""])
    def test_a_leftover_gateway_model_does_not_reach_vertex(self, monkeypatch, settings, stale):
        """Switching KORA_AI_BACKEND without switching MODEL_NAME would otherwise
        404 every agent call."""
        monkeypatch.setattr(settings, "MODEL_NAME", stale)
        assert vertex_llm.model_name() == "gemini-2.5-flash"


# ── offline safety ──────────────────────────────────────────────────────────


def test_the_suite_cannot_reach_vertex():
    """Regression guard for a hazard the Vertex switch introduced.

    Hermeticity used to rest on blank MODEL_API_KEY/BASE_URL. Vertex
    authenticates with Application Default Credentials instead, so on any
    developer machine that has run `gcloud auth application-default login`,
    KORA_AI_BACKEND=auto would resolve to Vertex and the suite would make live,
    billable calls. conftest.py pins 'mock'; this asserts it stayed pinned.
    """
    from app.config import settings as live

    assert live.KORA_AI_BACKEND == "mock", "conftest must pin the mock backend — see the ADC note there"
    assert ai_backend.active() is llm
    assert not ai_backend.is_configured()


# ── schema translation ──────────────────────────────────────────────────────


class TestToolSchema:
    def test_drops_keys_vertex_rejects(self):
        cleaned = vertex_llm._clean_schema(
            {
                "type": "object",
                "additionalProperties": False,
                "$schema": "http://json-schema.org/draft-07/schema#",
                "properties": {"limit": {"type": "integer", "additionalProperties": False}},
                "required": ["limit"],
            }
        )
        assert cleaned == {"type": "object", "properties": {"limit": {"type": "integer"}}, "required": ["limit"]}

    def test_object_without_properties_gets_an_empty_one(self):
        """Vertex rejects an object schema with no properties key."""
        assert vertex_llm._clean_schema({"type": "object"}) == {"type": "object", "properties": {}}

    def test_nested_items_are_cleaned(self):
        cleaned = vertex_llm._clean_schema({"type": "array", "items": {"type": "object", "additionalProperties": True}})
        assert cleaned == {"type": "array", "items": {"type": "object", "properties": {}}}


# ── OpenAI ⇄ Vertex message translation ─────────────────────────────────────


class FakePart:
    def __init__(self, text="", function_call=None):
        self.text = text
        self.function_call = function_call


def fake_response(parts, prompt_tokens=10, out_tokens=5, thoughts=0):
    return SimpleNamespace(
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=parts))],
        usage_metadata=SimpleNamespace(prompt_token_count=prompt_tokens, candidates_token_count=out_tokens, thoughts_token_count=thoughts),
    )


class TestResponseReading:
    def test_reads_text_without_touching_response_dot_text(self):
        """`response.text` raises when a candidate holds no text part — which is
        the normal shape of a pure function-call turn."""
        assert vertex_llm._text_of(fake_response([FakePart(text="hello "), FakePart(text="world")])) == "hello world"

    def test_no_candidates_is_empty_not_an_exception(self):
        assert vertex_llm._text_of(SimpleNamespace(candidates=[])) == ""

    def test_thinking_tokens_count_as_output(self):
        """Gemini 2.5 bills thinking as output; omitting it understates spend."""
        assert vertex_llm._usage(fake_response([], out_tokens=20, thoughts=100)) == (10, 120)


class TestToolTurnShape:
    def test_exposes_the_openai_shape_the_supervisor_reads(self):
        call = SimpleNamespace(name="list_overdue_invoices", args={"limit": 5})
        turn = vertex_llm._to_turn(fake_response([FakePart(function_call=call)]))

        assert len(turn.tool_calls) == 1
        tc = turn.tool_calls[0]
        assert tc.function.name == "list_overdue_invoices"
        # A JSON *string*, because supervisor.py does json.loads on it.
        assert json.loads(tc.function.arguments) == {"limit": 5}
        assert tc.id and isinstance(tc.id, str)

    def test_text_only_turn_has_no_tool_calls(self):
        turn = vertex_llm._to_turn(fake_response([FakePart(text="All settled.")]))
        assert turn.tool_calls == []
        assert turn.content == "All settled."

    def test_call_ids_are_unique_within_a_turn(self):
        """Two parallel calls to the same function must not collide — the
        supervisor keys its tool results by id."""
        call = SimpleNamespace(name="get_cashflow", args={})
        turn = vertex_llm._to_turn(fake_response([FakePart(function_call=call), FakePart(function_call=call)]))
        assert len({tc.id for tc in turn.tool_calls}) == 2


class TestHistoryTranslation:
    def test_system_messages_become_the_system_instruction(self):
        system, history = vertex_llm._to_history([{"role": "system", "content": "You are Kora."}, {"role": "user", "content": "hi"}])
        assert system == "You are Kora."
        assert len(history) == 1 and history[0].role == "user"

    def test_a_tool_result_is_paired_to_its_call_by_name(self):
        """Gemini matches a result to its call by function name, OpenAI by id —
        the id->name map built from the assistant turn is what bridges them."""
        messages = [
            {"role": "user", "content": "overdue?"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_0_list_overdue_invoices", "type": "function", "function": {"name": "list_overdue_invoices", "arguments": "{}"}}
                ],
            },
            {"role": "tool", "tool_call_id": "call_0_list_overdue_invoices", "content": json.dumps({"invoices": []})},
        ]
        _, history = vertex_llm._to_history(messages)
        assert [c.role for c in history] == ["user", "model", "user"]
        rendered = str(history[2])
        assert "list_overdue_invoices" in rendered

    def test_a_non_dict_tool_result_is_still_accepted(self):
        """Vertex requires a dict response; handlers may return a bare list."""
        messages = [
            {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "function": {"name": "f", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "[1, 2, 3]"},
        ]
        _, history = vertex_llm._to_history(messages)  # must not raise
        assert len(history) == 2

    def test_malformed_arguments_do_not_raise(self):
        messages = [{"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "function": {"name": "f", "arguments": "not json"}}]}]
        _, history = vertex_llm._to_history(messages)
        assert len(history) == 1


# ── thinking-token headroom ─────────────────────────────────────────────────


class FakeModel:
    """Records the budget each attempt asked for; can fake a truncated first try."""

    def __init__(self, truncate_first: bool = False):
        self.budgets: list[int] = []
        self.truncate_first = truncate_first

    def generate_content(self, contents, generation_config=None):
        # GenerationConfig keeps its fields on the wrapped proto, not as
        # attributes — to_dict() is the stable public read.
        self.budgets.append(generation_config.to_dict()["max_output_tokens"])
        cut = self.truncate_first and len(self.budgets) == 1
        return SimpleNamespace(
            candidates=[
                SimpleNamespace(content=SimpleNamespace(parts=[FakePart(text="{}")]), finish_reason=SimpleNamespace(name="MAX_TOKENS" if cut else "STOP"))
            ],
            usage_metadata=SimpleNamespace(prompt_token_count=1, candidates_token_count=1, thoughts_token_count=0),
        )


class TestThinkingHeadroom:
    def test_budget_is_raised_above_what_the_caller_asked_for(self):
        """Gemini 2.5 spends output tokens on thinking, so a gateway-tuned
        budget can be consumed before any answer is written."""
        model = FakeModel()
        vertex_llm._generate(model, "hi", 0.2, 1200, False)
        assert model.budgets == [1200 * vertex_llm._TOKEN_HEADROOM]

    def test_a_truncated_answer_is_retried_at_the_ceiling(self):
        """The observed failure: a half-written JSON object that no parser can
        recover, appearing only on some runs."""
        model = FakeModel(truncate_first=True)
        vertex_llm._generate(model, "hi", 0.2, 1200, False)
        assert model.budgets == [3600, vertex_llm._MAX_OUTPUT_CEILING]

    def test_no_second_call_when_the_answer_completed(self):
        model = FakeModel()
        vertex_llm._generate(model, "hi", 0.2, 1200, False)
        assert len(model.budgets) == 1

    def test_headroom_never_exceeds_the_ceiling(self):
        model = FakeModel()
        vertex_llm._generate(model, "hi", 0.2, 5000, False)
        assert model.budgets == [vertex_llm._MAX_OUTPUT_CEILING]

    @pytest.mark.parametrize(
        "reason,expected",
        [
            (SimpleNamespace(name="MAX_TOKENS"), True),
            (SimpleNamespace(name="STOP"), False),
            (2, True),  # raw wire value, when the enum isn't importable
            (1, False),
            (None, False),
        ],
    )
    def test_truncation_detection(self, reason, expected):
        response = SimpleNamespace(candidates=[SimpleNamespace(finish_reason=reason)])
        assert vertex_llm._truncated(response) is expected


# ── cost attribution ────────────────────────────────────────────────────────


class TestCost:
    def test_gemini_flash_is_not_priced_as_gemini_pro(self):
        """The rates were hardcoded to 1.5 Pro; on Flash that overstated spend
        by ~10x and the owner reads this number on the dashboard."""
        flash = cost.estimate_cost_usd(1_000_000, 1_000_000, "gemini-2.5-flash")
        pro = cost.estimate_cost_usd(1_000_000, 1_000_000, "gemini-1.5-pro")
        assert flash < pro
        assert flash == pytest.approx(0.30 + 2.50)

    def test_longest_prefix_wins(self):
        """'gemini-2.5-flash-lite' must not be priced as 'gemini-2.5-flash'."""
        assert cost.rates_for("gemini-2.5-flash-lite") == (0.10, 0.40)
        assert cost.rates_for("gemini-2.5-flash") == (0.30, 2.50)

    def test_unknown_models_fall_back_pessimistically(self):
        """Overstating is the safer error for a number used to make decisions."""
        assert cost.rates_for("some-new-model") == (3.50, 10.50)

    def test_gateway_models_still_priced(self):
        assert cost.rates_for("azure.gpt-4o-mini") == (0.15, 0.60)
