"""M7c — Gmail Pub/Sub push JWT verification."""
from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.services.pubsub_auth import verify_pubsub_push_token

client = TestClient(app)


def test_skip_verification_when_audience_unset(monkeypatch):
    monkeypatch.setattr("app.services.pubsub_auth.settings.GMAIL_PUBSUB_AUDIENCE", "")
    assert verify_pubsub_push_token(None) is True


def test_rejects_missing_bearer_when_audience_set(monkeypatch):
    monkeypatch.setattr("app.services.pubsub_auth.settings.GMAIL_PUBSUB_AUDIENCE", "https://api.example.com/api/gmail/push")
    assert verify_pubsub_push_token(None) is False
    assert verify_pubsub_push_token("Basic xyz") is False


def test_accepts_valid_token(monkeypatch):
    monkeypatch.setattr("app.services.pubsub_auth.settings.GMAIL_PUBSUB_AUDIENCE", "https://api.example.com/api/gmail/push")
    with patch("app.services.pubsub_auth.id_token.verify_oauth2_token", return_value={"sub": "pubsub"}):
        assert verify_pubsub_push_token("Bearer valid.jwt.token") is True


def test_push_endpoint_401_when_audience_set_and_no_token(monkeypatch):
    monkeypatch.setattr("app.services.pubsub_auth.settings.GMAIL_PUBSUB_AUDIENCE", "https://api.example.com/api/gmail/push")
    r = client.post("/api/gmail/push", json={"message": {"data": "dGVzdA=="}})
    assert r.status_code == 401


def test_push_endpoint_ok_when_audience_unset(monkeypatch):
    monkeypatch.setattr("app.services.pubsub_auth.settings.GMAIL_PUBSUB_AUDIENCE", "")
    r = client.post("/api/gmail/push", json={"message": {}})
    assert r.status_code == 200
