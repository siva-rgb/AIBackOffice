"""House style: Kora's writing must not read as machine-written.

Two mechanisms are under test. `HOUSE_STYLE` is the prompt-level contract every
prose agent inherits, and `strip_dashes` / `humanize` are the deterministic
backstop applied to what comes back. The backstop exists because prompt
compliance is probabilistic, and a single em dash in a chased invoice is
exactly the tell the house style is there to remove: the client reads that
message as coming from the freelancer, not from software.

Codes referenced in the assertions map to docs/skills/SLOP_JUDGE_SKILL.md.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from app.services.vertex_ai import (
    HOUSE_STYLE,
    HOUSE_STYLE_FORMAL,
    MockGemini,
    humanize,
    strip_dashes,
)


class TestStripDashes:
    """Each dash shape gets the punctuation a human would actually type."""

    def test_parenthetical_dash_becomes_a_comma(self):
        assert strip_dashes("Invoice 1042 — $2,500 — is overdue.") == "Invoice 1042, $2,500, is overdue."

    def test_a_range_between_digits_becomes_a_hyphen(self):
        # ", " here would destroy the meaning of the range.
        assert strip_dashes("Negotiate to Net 14–30 terms.") == "Negotiate to Net 14-30 terms."

    def test_a_heading_separator_becomes_a_colon(self):
        assert strip_dashes("## 3. Deliverables — what you receive") == "## 3. Deliverables: what you receive"
        assert strip_dashes("# Proposal — Q3 Landing Pages") == "# Proposal: Q3 Landing Pages"

    def test_a_dash_opening_a_line_is_a_bullet_and_is_dropped(self):
        assert strip_dashes("— Chase the oldest invoice") == "Chase the oldest invoice"

    def test_text_without_dashes_is_returned_unchanged(self):
        clean = "Three invoices totalling $6,800 are due this week."
        assert strip_dashes(clean) is clean

    def test_hyphens_in_compound_words_survive(self):
        assert strip_dashes("A jurisdiction-aware, plainly-worded agreement.") == "A jurisdiction-aware, plainly-worded agreement."

    @pytest.mark.parametrize("empty", ["", None])
    def test_empty_input_is_safe(self, empty):
        assert strip_dashes(empty) == empty


class TestHumanize:
    """The walk reaches every string an agent can return, and nothing else."""

    def test_it_reaches_nested_strings(self):
        payload = {
            "summary": "Cash is tight — chase the retainer.",
            "priorities": ["Collect $3,500 — the fastest win.", "Nothing else."],
            "nested": {"body": "Due Friday — please confirm."},
        }
        out = humanize(payload)
        assert out["summary"] == "Cash is tight, chase the retainer."
        assert out["priorities"][0] == "Collect $3,500, the fastest win."
        assert out["nested"]["body"] == "Due Friday, please confirm."

    def test_it_leaves_non_strings_alone(self):
        payload = {"confidence": 0.78, "count": 3, "ok": True, "missing": None, "items": []}
        assert humanize(payload) == payload

    def test_keys_are_wire_format_and_are_not_rewritten(self):
        assert humanize({"body—odd": "x — y"}) == {"body—odd": "x, y"}


class TestHouseStyleBlock:
    """The prompt contract states the rules that matter most."""

    def test_the_dash_ban_is_stated(self):
        assert "em dash" in HOUSE_STYLE
        assert "em dash" in HOUSE_STYLE_FORMAL

    def test_the_strongest_slop_signals_are_covered(self):
        # IU1 density, SQ2 templatedness, SQ6 word complexity.
        assert "In today's" in HOUSE_STYLE
        assert "It's not just X, it's Y" in HOUSE_STYLE
        for banned in ("leverage", "utilize", "delve", "seamless", "robust"):
            assert banned in HOUSE_STYLE

    def test_the_two_registers_differ_only_in_voice(self):
        assert "contractions where they fall naturally" in HOUSE_STYLE
        assert "no contractions" in HOUSE_STYLE_FORMAL
        assert HOUSE_STYLE != HOUSE_STYLE_FORMAL

    def test_the_block_itself_contains_no_dash(self):
        # A prompt that models the tell teaches the tell.
        for block in (HOUSE_STYLE, HOUSE_STYLE_FORMAL):
            assert "—" not in block and "–" not in block


class TestShippedCopyIsClean:
    """The canned text a judge reads in mock mode carries no dash either."""

    def test_mock_provider_prose_has_no_dashes(self):
        ai = MockGemini()
        payloads = [
            ai.draft_follow_up_email(
                {
                    "attempt": 1,
                    "currency": "USD",
                    "amount": 3500.0,
                    "business_name": "Rivera Studio",
                    "client_name": "Sarah Chen",
                    "invoice_number": "INV-1042",
                    "due_date": "2026-08-01",
                    "days_overdue": 9,
                }
            ),
            ai.compose_manager_briefing({"month_income": 8200, "overdue_count": 2, "overdue_total": 6800}),
            ai.chat_reply({"message": "what is overdue?", "context": {"overdue": [], "currency": "USD"}}),
            ai.compose_butler_briefing({"client_count": 5, "overdue_count": 1, "overdue_total": 3500}),
            ai.generate_cashflow_insights({"projected_balance_14d": -200}),
        ]
        for call in payloads:
            rendered = repr(call.data)
            assert "—" not in rendered and "–" not in rendered, rendered[:200]

    def test_no_user_facing_string_literal_in_the_app_carries_a_dash(self):
        """Guards the whole package, so new copy cannot reintroduce the tell.

        Docstrings and comments are developer prose and are exempt. Two files
        legitimately contain a dash as *data*: the stripper's own guard and the
        slug sanitiser that maps a dash to a hyphen.
        """
        app = pathlib.Path(__file__).resolve().parents[1] / "app"
        exempt = {"services/vertex_ai.py", "routers/contracts.py"}
        offenders = []
        for path in app.rglob("*.py"):
            rel = path.relative_to(app).as_posix()
            if rel in exempt:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            docs = {
                d
                for n in ast.walk(tree)
                if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                for d in [ast.get_docstring(n, clean=False)]
                if d
            }
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value not in docs:
                    if "—" in node.value or "–" in node.value:
                        offenders.append(f"{rel}:{node.lineno}  {node.value.strip()[:70]}")
        assert not offenders, "em/en dash in shipped copy:\n" + "\n".join(offenders)
