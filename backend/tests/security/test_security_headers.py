"""M7d — Security headers: strict CSP, COOP, COEP, Expect-CT."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_api_response_has_strict_csp():
    r = client.get("/health")
    csp = r.headers.get("Content-Security-Policy", "")
    assert "unsafe-eval" not in csp
    assert "unsafe-inline" not in csp
    assert "default-src 'none'" in csp


def test_api_response_has_coop_coep_expect_ct():
    r = client.get("/health")
    assert r.headers.get("Cross-Origin-Opener-Policy") == "same-origin"
    assert r.headers.get("Cross-Origin-Embedder-Policy") == "credentialless"
    assert r.headers.get("Expect-CT", "").startswith("max-age=")


def test_docs_csp_uses_nonce_not_unsafe_inline():
    r = client.get("/docs")
    csp = r.headers.get("Content-Security-Policy", "")
    assert "unsafe-inline" not in csp
    assert "nonce-" in csp
