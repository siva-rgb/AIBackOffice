"""Linking a Drive file to a client must not guess.

`_resolve_client_id` used raw substring matching with first-match-wins ordering,
so a client called "Apex" claimed `apexon-retro.docx`, and any document that
merely *mentioned* another client ("similar to the Northwind build") was filed
under that client. A wrong tag is worse than no tag: the document lands on the
wrong client's page and enters that client's recall scope.

Also covers `_list_folder_files`, which scanned one non-recursive page of 50 —
a `Kora/Contracts/` layout ingested nothing, and file 51 onward was dropped
silently.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import drive_intel
from app.services.drive_intel import _list_folder_files, _resolve_client_id

UID = "user-1"


def client(cid: str, name: str, email: str | None = None, contact_emails: list[str] | None = None):
    return SimpleNamespace(id=cid, user_id=UID, name=name, email=email, contact_emails=contact_emails or [])


@pytest.fixture
def clients(monkeypatch):
    """Patch the store the resolver reads. Tests set `rows[:]` to the roster."""
    rows: list = []
    monkeypatch.setattr("app.store.list_clients", lambda uid: rows)
    return rows


class TestFilenameMatching:
    def test_matches_a_whole_token(self, clients):
        clients.append(client("c1", "Northwind"))
        assert _resolve_client_id(UID, "northwind_brief-v2.docx") == "c1"

    @pytest.mark.parametrize("filename", ["apexon-retro.docx", "myapex.pdf", "apexes.txt"])
    def test_does_not_match_inside_a_longer_word(self, clients, filename):
        """The original bug: a short client name matched any word containing it."""
        clients.append(client("c1", "Apex"))
        assert _resolve_client_id(UID, filename) is None

    def test_multi_word_client_name(self, clients):
        clients.append(client("c1", "Acme Digital"))
        assert _resolve_client_id(UID, "acme-digital-msa-signed.pdf") == "c1"

    def test_most_specific_name_wins(self, clients):
        """ "Acme" and "Acme Digital" both match — the longer one is the answer."""
        clients.extend([client("c1", "Acme"), client("c2", "Acme Digital")])
        assert _resolve_client_id(UID, "acme-digital-msa.pdf") == "c2"

    def test_order_of_clients_does_not_decide_it(self, clients):
        clients.extend([client("c2", "Acme Digital"), client("c1", "Acme")])
        assert _resolve_client_id(UID, "acme-digital-msa.pdf") == "c2"

    def test_filename_beats_body(self, clients):
        clients.extend([client("c1", "Northwind"), client("c2", "Acme Digital")])
        body = "This scope mirrors the Acme Digital engagement."
        assert _resolve_client_id(UID, "northwind-scope.docx", body) == "c1"


class TestEmailInBody:
    def test_single_email_match_resolves(self, clients):
        clients.append(client("c1", "Northwind", email="bob@northwind.example"))
        body = "Please copy bob@northwind.example on the invoice."
        assert _resolve_client_id(UID, "scope.docx", body) == "c1"

    def test_contact_emails_count_too(self, clients):
        clients.append(client("c1", "Northwind", email="a@nw.example", contact_emails=["jill@nw.example"]))
        assert _resolve_client_id(UID, "scope.docx", "cc jill@nw.example thanks") == "c1"

    def test_two_clients_emailed_is_ambiguous(self, clients):
        clients.extend(
            [
                client("c1", "Northwind", email="bob@northwind.example"),
                client("c2", "Acme Digital", email="sue@acme.example"),
            ]
        )
        body = "Intro: bob@northwind.example, meet sue@acme.example."
        assert _resolve_client_id(UID, "intro.docx", body) is None

    def test_email_beats_a_name_mentioned_in_the_body(self, clients):
        clients.extend(
            [
                client("c1", "Northwind", email="bob@northwind.example"),
                client("c2", "Acme Digital"),
            ]
        )
        body = "bob@northwind.example — this is much like the Acme Digital build."
        assert _resolve_client_id(UID, "scope.docx", body) == "c1"


class TestNameInBody:
    def test_single_mention_resolves(self, clients):
        clients.append(client("c1", "Northwind"))
        assert _resolve_client_id(UID, "scope-v3.docx", "Scope of work for Northwind.") == "c1"

    def test_two_clients_named_is_ambiguous(self, clients):
        """The headline case — a comparison must not tag the doc to the comparee."""
        clients.extend([client("c1", "Northwind"), client("c2", "Acme Digital")])
        body = "Scope for Acme Digital. Delivery mirrors the Northwind build."
        assert _resolve_client_id(UID, "scope-v3.docx", body) is None

    def test_short_names_are_not_read_from_the_body(self, clients):
        """ "Bo" or "Ltd" in prose is noise, not a signal."""
        clients.append(client("c1", "Bo"))
        assert _resolve_client_id(UID, "scope.docx", "Bo said the deadline moved.") is None

    def test_short_names_still_work_in_a_filename(self, clients):
        """A filename is deliberate; whole-token matching makes it safe enough."""
        clients.append(client("c1", "Bo"))
        assert _resolve_client_id(UID, "bo-contract.pdf") == "c1"

    def test_only_the_opening_of_the_body_is_read(self, clients):
        clients.append(client("c1", "Northwind"))
        assert _resolve_client_id(UID, "scope.docx", ("x" * 4100) + " Northwind") is None

    def test_no_clients_no_crash(self, clients):
        assert _resolve_client_id(UID, "anything.docx", "any body") is None

    def test_store_failure_returns_none(self, monkeypatch):
        def boom(uid):
            raise RuntimeError("supabase down")

        monkeypatch.setattr("app.store.list_clients", boom)
        assert _resolve_client_id(UID, "northwind.docx") is None


# --- folder listing --------------------------------------------------------


class FakeDrive:
    """Minimal stand-in for the Drive v3 client: folder id -> pages of children."""

    def __init__(self, tree: dict[str, list[list[dict]]]):
        self.tree = tree
        self.queries: list[str] = []

    def files(self):
        return self

    def list(self, q="", fields="", pageSize=100, pageToken=None):
        self.queries.append(q)
        folder_id = q.split("'")[1]
        pages = self.tree.get(folder_id, [[]])
        idx = int(pageToken) if pageToken else 0
        page = pages[idx] if idx < len(pages) else []
        self._result = {"files": page}
        if idx + 1 < len(pages):
            self._result["nextPageToken"] = str(idx + 1)
        return self

    def execute(self):
        return self._result


def doc(fid: str) -> dict:
    return {"id": fid, "name": f"{fid}.pdf", "mimeType": "application/pdf", "modifiedTime": "2026-08-01T00:00:00Z"}


def folder(fid: str) -> dict:
    return {"id": fid, "name": fid, "mimeType": drive_intel._FOLDER_MIME, "modifiedTime": "2026-08-01T00:00:00Z"}


class TestFolderListing:
    def test_reads_every_page(self, monkeypatch):
        """Page 2 used to be dropped on the floor."""
        svc = FakeDrive({"root": [[doc("a"), doc("b")], [doc("c")]]})
        assert [f["id"] for f in _list_folder_files(svc, "root")] == ["a", "b", "c"]

    def test_descends_into_subfolders(self, monkeypatch):
        svc = FakeDrive({"root": [[folder("sub"), doc("a")]], "sub": [[doc("b")]]})
        assert sorted(f["id"] for f in _list_folder_files(svc, "root")) == ["a", "b"]

    def test_folders_are_not_returned_as_files(self, monkeypatch):
        svc = FakeDrive({"root": [[folder("sub")]], "sub": [[]]})
        assert _list_folder_files(svc, "root") == []

    def test_depth_is_capped(self, monkeypatch):
        tree = {"root": [[folder("d1")]], "d1": [[folder("d2")]], "d2": [[folder("d3")]], "d3": [[folder("d4")]], "d4": [[doc("deep")]]}
        ids = [f["id"] for f in _list_folder_files(FakeDrive(tree), "root")]
        assert "deep" not in ids

    def test_total_is_capped(self, monkeypatch):
        monkeypatch.setattr(drive_intel, "_MAX_FOLDER_FILES", 5)
        svc = FakeDrive({"root": [[doc(str(i)) for i in range(20)]]})
        assert len(_list_folder_files(svc, "root")) == 5

    def test_a_folder_cycle_terminates(self, monkeypatch):
        """Drive allows multiple parents; revisiting a folder must not spin."""
        svc = FakeDrive({"root": [[folder("sub")]], "sub": [[folder("root"), doc("a")]]})
        assert [f["id"] for f in _list_folder_files(svc, "root")] == ["a"]
