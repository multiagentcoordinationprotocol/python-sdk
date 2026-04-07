"""Tests for session ID format validation."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from macp_sdk.decision import DecisionSession
from macp_sdk.errors import MacpSessionError


@pytest.fixture
def mock_client():
    mock = MagicMock()
    mock.auth = MagicMock()
    mock.auth.sender = "test"
    mock.auth.metadata.return_value = []
    ack = MagicMock()
    ack.ok = True
    mock.send.return_value = ack
    return mock


class TestSessionIdValidation:
    def test_uuid_v4_accepted(self, mock_client):
        DecisionSession(mock_client, session_id="550e8400-e29b-41d4-a716-446655440000")

    def test_uuid_lowercase_required(self, mock_client):
        # UUID with lowercase hex chars
        DecisionSession(mock_client, session_id="abcdef01-2345-4678-9abc-def012345678")

    def test_base64url_22_chars_accepted(self, mock_client):
        DecisionSession(mock_client, session_id="abcdefghijklmnopqrstuv")

    def test_base64url_long_accepted(self, mock_client):
        DecisionSession(mock_client, session_id="abcdefghijklmnopqrstuvwxyz0123456789_-")

    def test_short_id_rejected(self, mock_client):
        with pytest.raises(MacpSessionError, match="session_id must be"):
            DecisionSession(mock_client, session_id="s1")

    def test_empty_string_auto_generates(self, mock_client):
        # Empty string is falsy, so auto-generation kicks in
        s = DecisionSession(mock_client, session_id="")
        assert len(s.session_id) == 36  # UUID v4

    def test_too_short_base64_rejected(self, mock_client):
        with pytest.raises(MacpSessionError, match="session_id must be"):
            DecisionSession(mock_client, session_id="abc123")

    def test_auto_generated_always_valid(self, mock_client):
        # When no session_id is provided, a UUID v4 is generated
        s = DecisionSession(mock_client)
        assert len(s.session_id) == 36  # UUID format
