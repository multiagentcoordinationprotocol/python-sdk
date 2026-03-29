"""Shared test fixtures for the MACP SDK test suite."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from macp.v1 import envelope_pb2
from macp_sdk.auth import AuthConfig
from macp_sdk.envelope import new_message_id, now_unix_ms, serialize_message


@pytest.fixture
def dev_auth() -> AuthConfig:
    return AuthConfig.for_dev_agent("test-agent")


@pytest.fixture
def coordinator_auth() -> AuthConfig:
    return AuthConfig.for_dev_agent("coordinator")


def make_ack(
    ok: bool = True,
    session_id: str = "",
    message_id: str = "",
    duplicate: bool = False,
) -> envelope_pb2.Ack:
    """Build a canned Ack response."""
    ack = envelope_pb2.Ack(
        ok=ok,
        session_id=session_id,
        message_id=message_id,
        duplicate=duplicate,
    )
    if not ok:
        ack.error.CopyFrom(envelope_pb2.MACPError(code="TEST_ERROR", message="test error"))
    return ack


def make_envelope(
    mode: str,
    message_type: str,
    payload_message: object,
    *,
    session_id: str = "test-session",
    sender: str = "test-agent",
) -> envelope_pb2.Envelope:
    """Build an Envelope for testing projections."""
    return envelope_pb2.Envelope(
        macp_version="1.0",
        mode=mode,
        message_type=message_type,
        message_id=new_message_id(),
        session_id=session_id,
        sender=sender,
        timestamp_unix_ms=now_unix_ms(),
        payload=serialize_message(payload_message),
    )


@pytest.fixture
def mock_client(dev_auth: AuthConfig) -> MagicMock:
    """A MagicMock that mimics MacpClient, returning ok Acks."""
    client = MagicMock()
    client.auth = dev_auth

    def send_side_effect(envelope, *, auth=None, timeout=None, raise_on_nack=True):
        return make_ack(ok=True, session_id=envelope.session_id, message_id=envelope.message_id)

    client.send.side_effect = send_side_effect
    return client
