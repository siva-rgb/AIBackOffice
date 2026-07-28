"""M7b — OAuth state tokens are random and session-bound."""
from __future__ import annotations

import time
from unittest.mock import patch

from app.services.oauth_state import issue_oauth_state, verify_oauth_state


def test_issue_and_verify_round_trip():
    state = issue_oauth_state("user-abc")
    assert verify_oauth_state(state) == "user-abc"


def test_raw_user_id_is_rejected():
    assert verify_oauth_state("user-abc") is None


def test_tampered_signature_rejected():
    state = issue_oauth_state("user-abc")
    tampered = state[:-4] + "ffff"
    assert verify_oauth_state(tampered) is None


def test_expired_state_rejected():
    state = issue_oauth_state("user-abc")
    with patch("app.services.oauth_state.time") as mock_time:
        mock_time.time.return_value = time.time() + 700
        assert verify_oauth_state(state) is None


def test_empty_state_rejected():
    assert verify_oauth_state(None) is None
    assert verify_oauth_state("") is None
