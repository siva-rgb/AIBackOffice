"""Drive files must be classified by what's inside them, not just their name.

Regression guard for the staging UAT finding. `_classify_doc_type` only looked at
the filename, so any document not happening to contain a keyword became "other" —
and `_route_file` takes no action for "other". A real file,
`DQ_Implimentation_Usecase.docx`, was ingested from the user's Drive and produced
a metadata row and nothing else.

Second half of the same finding: `brief`/`scope`/`proposal` were only processed
when the file was a native Google Doc, so a .docx brief was classified and then
silently dropped.
"""

from __future__ import annotations

import pytest

from app.services.drive_intel import _classify_doc_type


class TestFilenameStillWins:
    """The filename is free and usually right — it must stay the first signal."""

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("meeting transcript 2026-08.txt", "transcript"),
            ("acme msa agreement.pdf", "contract"),
            ("INV-2026-017.pdf", "invoice"),
            ("receipt starbucks.jpg", "receipt"),
            ("project brief v2.docx", "brief"),
        ],
    )
    def test_classifies_from_name(self, name, expected):
        assert _classify_doc_type(name.lower(), "docx", "", "") == expected

    def test_name_beats_body(self):
        """A file named 'invoice' holding contract text is still an invoice."""
        body = "MASTER SERVICES AGREEMENT between the parties..."
        assert _classify_doc_type("invoice-88.pdf", "pdf", "", body) == "invoice"


class TestContentIsReadWhenTheNameSaysNothing:
    @pytest.mark.parametrize(
        "body,expected",
        [
            ("MASTER SERVICES AGREEMENT\n\nThis agreement is entered into...", "contract"),
            ("INVOICE #2026-114\nBill to: Acme Corp\nAmount due: $4,200", "invoice"),
            ("Meeting transcript\n[00:01] Alex: let's begin", "transcript"),
            ("Project brief\nObjective: redesign the marketing site", "brief"),
            ("Payment receipt\nThank you for your payment", "receipt"),
        ],
    )
    def test_classifies_from_body(self, body, expected):
        # An opaque filename — exactly the case that used to yield "other".
        assert _classify_doc_type("dq_implimentation_usecase.docx", "docx", "", body) == expected

    def test_the_original_failing_file_is_unchanged_without_matching_content(self):
        """Honesty check: a genuinely unclassifiable document is still 'other'.

        The fix must not turn everything into a false positive.
        """
        body = "Data quality implementation use case. Step 1: profile the source tables."
        assert _classify_doc_type("dq_implimentation_usecase.docx", "docx", "", body) == "other"

    def test_only_the_opening_is_scanned(self):
        """Keeps long files cheap — a keyword past ~2000 chars doesn't count."""
        body = ("x" * 3000) + " master services agreement"
        assert _classify_doc_type("notes.docx", "docx", "", body) == "other"

    def test_missing_text_falls_back_to_name_only_behaviour(self):
        """Extraction is best-effort; no text must not raise."""
        assert _classify_doc_type("notes.docx", "docx", "", "") == "other"
        assert _classify_doc_type("notes.docx", "docx", "", None) == "other"  # type: ignore[arg-type]
