"""A Drive transcript must be read properly and processed once.

Two defects in `_handle_transcript`:

1. It decoded `get_media` bytes directly, which is the *encoded* file — for a
   .docx or .pdf named "transcript" that is binary noise, and it went straight
   into `meetings.raw_transcript` and on to the meeting agent. The same bug was
   already fixed one function over in `_save_as_client_note`; this call site was
   missed.
2. It inserted a meeting unconditionally, while `_filter_unprocessed` re-queues
   any file whose `modifiedTime` changed. Editing a transcript therefore created
   a second meeting and a second set of action items. Contracts already deduped
   via `drive_source_id`; transcripts did not.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import drive_intel
from app.services.drive_intel import _handle_transcript

UID = "user-1"
FILE = {"id": "drive-file-1", "name": "Acme sync - Transcript", "mimeType": "application/pdf"}


class FakeQuery:
    """One PostgREST-style chain. Records what it was asked to do."""

    def __init__(self, table: str, log: list, rows: list):
        self.table = table
        self.log = log
        self.rows = rows

    def select(self, *a, **kw):
        return self

    def eq(self, *a, **kw):
        return self

    def insert(self, row):
        self.log.append(("insert", self.table, row))
        self.rows = [{"id": "meeting-new"}]
        return self

    def update(self, row):
        self.log.append(("update", self.table, row))
        self.rows = []
        return self

    def execute(self):
        return SimpleNamespace(data=self.rows)


class FakeDB:
    def __init__(self, cache_rows: list | None = None):
        self.log: list = []
        self.cache_rows = cache_rows if cache_rows is not None else [{"meeting_id": None}]

    def table(self, name: str):
        rows = self.cache_rows if name == "drive_doc_cache" else []
        return FakeQuery(name, self.log, list(rows))

    def inserted(self, table: str) -> list:
        return [row for op, t, row in self.log if op == "insert" and t == table]


@pytest.fixture
def wiring(monkeypatch):
    """Neutralise everything outside the function under test."""
    processed: list = []
    monkeypatch.setattr("app.store.list_clients", lambda uid: [])
    monkeypatch.setattr(
        "app.services.meeting_agent.process_transcript",
        lambda uid, mid, text, source: processed.append((mid, text, source)),
    )
    return SimpleNamespace(processed=processed)


class TestTextExtraction:
    def test_uses_the_extractor_not_raw_bytes(self, monkeypatch, wiring):
        """The regression: a PDF transcript must not go in as encoded bytes."""
        calls = []

        def fake_download(user_id, file_id, mime_type=""):
            calls.append((file_id, mime_type))
            return "Alex: welcome everyone."

        monkeypatch.setattr(drive_intel, "download_drive_file_text", fake_download)
        db = FakeDB()
        _handle_transcript(UID, FILE, service=object(), db=db)

        assert calls == [("drive-file-1", "application/pdf")]
        meeting = db.inserted("meetings")[0]
        assert meeting["raw_transcript"] == "Alex: welcome everyone."

    def test_extracted_text_reaches_the_meeting_agent(self, monkeypatch, wiring):
        monkeypatch.setattr(drive_intel, "download_drive_file_text", lambda *a, **kw: "Alex: welcome everyone.")
        _handle_transcript(UID, FILE, service=object(), db=FakeDB())
        assert wiring.processed == [("meeting-new", "Alex: welcome everyone.", "drive_transcript")]

    def test_a_download_failure_does_not_create_a_meeting(self, monkeypatch, wiring):
        def boom(*a, **kw):
            raise RuntimeError("drive 404")

        monkeypatch.setattr(drive_intel, "download_drive_file_text", boom)
        db = FakeDB()
        _handle_transcript(UID, FILE, service=object(), db=db)
        assert db.inserted("meetings") == []


class TestProcessedOnce:
    def test_a_second_run_does_not_create_a_second_meeting(self, monkeypatch, wiring):
        """The file was edited in Drive, so `_filter_unprocessed` re-queued it."""
        monkeypatch.setattr(drive_intel, "download_drive_file_text", lambda *a, **kw: "Alex: hello.")
        db = FakeDB(cache_rows=[{"meeting_id": "meeting-existing"}])
        _handle_transcript(UID, FILE, service=object(), db=db)

        assert db.inserted("meetings") == []
        assert wiring.processed == []

    def test_it_does_not_even_download_when_already_processed(self, monkeypatch, wiring):
        """Skip before the network call — a re-sync should be nearly free."""
        downloads = []
        monkeypatch.setattr(drive_intel, "download_drive_file_text", lambda *a, **kw: downloads.append(1) or "x")
        db = FakeDB(cache_rows=[{"meeting_id": "meeting-existing"}])
        _handle_transcript(UID, FILE, service=object(), db=db)
        assert downloads == []

    def test_a_null_meeting_id_is_not_treated_as_processed(self, monkeypatch, wiring):
        """The cache row is written before routing, so meeting_id starts NULL."""
        monkeypatch.setattr(drive_intel, "download_drive_file_text", lambda *a, **kw: "Alex: hello.")
        db = FakeDB(cache_rows=[{"meeting_id": None}])
        _handle_transcript(UID, FILE, service=object(), db=db)
        assert len(db.inserted("meetings")) == 1

    def test_no_cache_row_at_all_still_processes(self, monkeypatch, wiring):
        monkeypatch.setattr(drive_intel, "download_drive_file_text", lambda *a, **kw: "Alex: hello.")
        db = FakeDB(cache_rows=[])
        _handle_transcript(UID, FILE, service=object(), db=db)
        assert len(db.inserted("meetings")) == 1

    def test_a_cache_lookup_failure_falls_through_to_processing(self, monkeypatch, wiring):
        """Losing the dedupe read must not lose the transcript."""
        monkeypatch.setattr(drive_intel, "download_drive_file_text", lambda *a, **kw: "Alex: hello.")

        class BrokenDB(FakeDB):
            def table(self, name):
                if name == "drive_doc_cache":
                    raise RuntimeError("supabase down")
                return super().table(name)

        db = BrokenDB()
        _handle_transcript(UID, FILE, service=object(), db=db)
        assert len(db.inserted("meetings")) == 1
