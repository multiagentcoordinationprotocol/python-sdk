"""Unit tests for agent transport adapters."""

from __future__ import annotations

from unittest.mock import MagicMock

from macp.v1 import envelope_pb2

from macp_sdk.agent.transports import (
    GrpcTransportAdapter,
    HttpTransportAdapter,
    _envelope_to_message,
)
from macp_sdk.constants import MODE_DECISION
from macp_sdk.envelope import new_message_id, now_unix_ms


def _make_envelope(
    message_type: str = "Proposal",
    session_id: str = "test-session",
    sender: str = "agent-a",
    payload: bytes | None = None,
) -> envelope_pb2.Envelope:
    if payload is None:
        import json

        payload = json.dumps({"proposal_id": "p1", "option": "opt-a"}).encode()
    return envelope_pb2.Envelope(
        macp_version="1.0",
        mode=MODE_DECISION,
        message_type=message_type,
        message_id=new_message_id(),
        session_id=session_id,
        sender=sender,
        timestamp_unix_ms=now_unix_ms(),
        payload=payload,
    )


class TestEnvelopeToMessage:
    def test_basic_conversion(self):
        env = _make_envelope()
        msg = _envelope_to_message(env)
        assert msg.message_type == "Proposal"
        assert msg.sender == "agent-a"
        assert msg.raw is env
        assert "proposal_id" in msg.payload
        assert msg.proposal_id == "p1"

    def test_binary_payload(self):
        env = envelope_pb2.Envelope(
            macp_version="1.0",
            mode=MODE_DECISION,
            message_type="Custom",
            message_id=new_message_id(),
            session_id="s1",
            sender="agent-b",
            timestamp_unix_ms=now_unix_ms(),
            payload=b"\x00\x01\x02",
        )
        msg = _envelope_to_message(env)
        assert msg.message_type == "Custom"
        assert "_raw_bytes" in msg.payload

    def test_empty_payload(self):
        env = envelope_pb2.Envelope(
            macp_version="1.0",
            mode=MODE_DECISION,
            message_type="Ping",
            message_id=new_message_id(),
            session_id="s1",
            sender="agent-c",
            timestamp_unix_ms=now_unix_ms(),
            payload=b"",
        )
        msg = _envelope_to_message(env)
        assert msg.payload == {}
        assert msg.proposal_id is None


class TestGrpcTransportAdapter:
    def test_yields_messages_for_target_session(self):
        mock_client = MagicMock()
        mock_stream = MagicMock()

        env1 = _make_envelope(session_id="target-session")
        env2 = _make_envelope(session_id="other-session")
        env3 = _make_envelope(session_id="target-session", message_type="Vote")
        mock_stream.responses.return_value = iter([env1, env2, env3])
        mock_client.open_stream.return_value = mock_stream

        adapter = GrpcTransportAdapter(mock_client, "target-session")
        messages = list(adapter.start())

        assert len(messages) == 2
        assert messages[0].message_type == "Proposal"
        assert messages[1].message_type == "Vote"
        mock_stream.close.assert_called_once()

    def test_stop_closes_stream(self):
        mock_client = MagicMock()
        mock_stream = MagicMock()
        mock_stream.responses.return_value = iter([])
        mock_client.open_stream.return_value = mock_stream

        adapter = GrpcTransportAdapter(mock_client, "s1")
        list(adapter.start())
        adapter.stop()

        assert adapter._stopped is True


class TestHttpTransportAdapter:
    def test_stop_sets_flag(self):
        adapter = HttpTransportAdapter(
            base_url="http://localhost:8080",
            session_id="s1",
            participant_id="agent-a",
            poll_interval_ms=100,
        )
        assert adapter._stopped is False
        adapter.stop()
        assert adapter._stopped is True

    def test_config_values(self):
        adapter = HttpTransportAdapter(
            base_url="http://localhost:8080/",
            session_id="s1",
            participant_id="agent-a",
            poll_interval_ms=2000,
            auth_token="tok-123",
        )
        assert adapter._base_url == "http://localhost:8080"
        assert adapter._session_id == "s1"
        assert adapter._participant_id == "agent-a"
        assert adapter._poll_interval == 2.0
        assert adapter._auth_token == "tok-123"
