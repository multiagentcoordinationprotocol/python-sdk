from __future__ import annotations

import pytest

from macp_sdk.auth import AuthConfig


class TestAuthConfig:
    def test_for_dev_agent(self):
        auth = AuthConfig.for_dev_agent("alice")
        assert auth.agent_id == "alice"
        assert auth.sender_hint == "alice"
        assert auth.bearer_token is None
        assert auth.sender == "alice"
        # Dev-agent auth defaults expected_sender to the agent_id so client-side
        # mismatch checks still work in tests and examples.
        assert auth.expected_sender == "alice"

    def test_for_dev_agent_explicit_expected_sender(self):
        auth = AuthConfig.for_dev_agent("alice", expected_sender="alice-v2")
        assert auth.expected_sender == "alice-v2"

    def test_for_bearer(self):
        auth = AuthConfig.for_bearer("tok-123", sender_hint="bob")
        assert auth.bearer_token == "tok-123"
        assert auth.sender_hint == "bob"
        assert auth.agent_id is None
        assert auth.sender == "bob"
        assert auth.expected_sender is None

    def test_for_bearer_no_hint(self):
        auth = AuthConfig.for_bearer("tok-123")
        assert auth.sender is None
        assert auth.expected_sender is None

    def test_for_bearer_expected_sender(self):
        """expected_sender sets both the guardrail and the default sender_hint."""
        auth = AuthConfig.for_bearer("tok-123", expected_sender="alice")
        assert auth.expected_sender == "alice"
        # sender_hint defaults to expected_sender when not provided explicitly
        assert auth.sender_hint == "alice"
        assert auth.sender == "alice"

    def test_for_bearer_expected_and_explicit_hint(self):
        auth = AuthConfig.for_bearer(
            "tok-123", sender_hint="alice-envelope", expected_sender="alice"
        )
        assert auth.sender_hint == "alice-envelope"
        assert auth.expected_sender == "alice"

    def test_both_raises(self):
        with pytest.raises(ValueError, match="either"):
            AuthConfig(bearer_token="tok", agent_id="id")

    def test_neither_raises(self):
        with pytest.raises(ValueError, match="either"):
            AuthConfig()

    def test_metadata_dev_agent(self):
        auth = AuthConfig.for_dev_agent("alice")
        headers = auth.metadata()
        assert ("x-macp-agent-id", "alice") in headers

    def test_metadata_bearer(self):
        auth = AuthConfig.for_bearer("tok-123")
        headers = auth.metadata()
        assert ("authorization", "Bearer tok-123") in headers

    def test_metadata_bearer_is_stable(self):
        """Repeated metadata() calls return the same bearer header (no drift)."""
        auth = AuthConfig.for_bearer("tok-abc", expected_sender="alice")
        assert auth.metadata() == [("authorization", "Bearer tok-abc")]

    def test_frozen(self):
        auth = AuthConfig.for_dev_agent("alice")
        with pytest.raises(AttributeError):
            auth.agent_id = "bob"  # type: ignore[misc]
