"""Signed-URL generation must work on Cloud Run, not just on a laptop.

Regression guard for the staging UAT finding: `blob.generate_signed_url()` needs a
private key to sign. Locally the ambient credentials come from a service-account
JSON and have one; on Cloud Run they are `compute_engine.Credentials` — a bare
access token — so every invoice/report PDF download returned 500.

The code path is byte-for-byte identical in both places; only the credential type
differs, which is exactly why no hermetic test caught it. These tests pin the
branch by faking each credential type.
"""

from __future__ import annotations

import sys
import types

import pytest

from app.services import storage


class _FakeSigner:
    """Stands in for the private key a service-account credential carries."""


class _ServiceAccountCreds:
    signer = _FakeSigner()
    valid = True
    service_account_email = "sa@example.iam.gserviceaccount.com"
    token = "sa-token"


class _ComputeCreds:
    """Cloud Run's identity: a token, no signer."""

    signer = None
    valid = True
    service_account_email = "1234-compute@developer.gserviceaccount.com"
    token = "metadata-token"


def _patch_google_auth(monkeypatch, creds):
    """Install a fake `google.auth` default() returning `creds`."""
    google_auth = types.ModuleType("google.auth")
    google_auth.default = lambda *a, **k: (creds, "test-project")

    transport = types.ModuleType("google.auth.transport")
    requests_mod = types.ModuleType("google.auth.transport.requests")
    requests_mod.Request = lambda *a, **k: object()

    monkeypatch.setitem(sys.modules, "google.auth", google_auth)
    monkeypatch.setitem(sys.modules, "google.auth.transport", transport)
    monkeypatch.setitem(sys.modules, "google.auth.transport.requests", requests_mod)


def test_service_account_credentials_sign_directly(monkeypatch):
    """With a private key present, add nothing — preserve local behaviour."""
    _patch_google_auth(monkeypatch, _ServiceAccountCreds())
    assert storage._signing_kwargs() == {}


def test_compute_credentials_delegate_to_iam_signblob(monkeypatch):
    """Without a private key, hand over the SA email + token so IAM signs."""
    _patch_google_auth(monkeypatch, _ComputeCreds())
    kwargs = storage._signing_kwargs()
    assert kwargs == {
        "service_account_email": "1234-compute@developer.gserviceaccount.com",
        "access_token": "metadata-token",
    }


def test_signing_kwargs_never_raises(monkeypatch):
    """A credential-discovery failure must not turn into a 500 on the request."""
    broken = types.ModuleType("google.auth")

    def _boom(*a, **k):
        raise RuntimeError("no metadata server")

    broken.default = _boom
    monkeypatch.setitem(sys.modules, "google.auth", broken)
    assert storage._signing_kwargs() == {}


def test_get_signed_url_passes_signing_kwargs_through(monkeypatch):
    """The kwargs must actually reach generate_signed_url, not just be computed."""
    captured: dict = {}

    class _Blob:
        def exists(self):
            return True

        def generate_signed_url(self, **kwargs):
            captured.update(kwargs)
            return "https://signed.example/url"

    class _Bucket:
        def blob(self, path):
            return _Blob()

    monkeypatch.setattr(storage, "_bucket", lambda: _Bucket())
    monkeypatch.setattr(storage, "_assert_owner", lambda user_id, path: None)
    monkeypatch.setattr(storage, "_signing_kwargs", lambda: {"service_account_email": "x@y.z", "access_token": "tok"})

    url = storage.get_signed_url("user-1", "users/user-1/invoices/a.pdf")

    assert url == "https://signed.example/url"
    assert captured["service_account_email"] == "x@y.z"
    assert captured["access_token"] == "tok"
    assert captured["version"] == "v4"
