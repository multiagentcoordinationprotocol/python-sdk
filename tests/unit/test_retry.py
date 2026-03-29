from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from macp.v1 import envelope_pb2
from macp_sdk.errors import AckFailure, MacpAckError, MacpRetryError, MacpTransportError
from macp_sdk.retry import RetryPolicy, retry_send


def _make_envelope() -> envelope_pb2.Envelope:
    return envelope_pb2.Envelope(
        macp_version="1.0",
        mode="macp.mode.decision.v1",
        message_type="Vote",
        message_id="m1",
        session_id="s1",
        sender="alice",
    )


class TestRetryPolicy:
    def test_defaults(self):
        p = RetryPolicy()
        assert p.max_retries == 3
        assert "RATE_LIMITED" in p.retryable_codes


class TestRetrySend:
    @patch("macp_sdk.retry.time.sleep")
    def test_succeeds_first_try(self, mock_sleep):
        client = MagicMock()
        ack = envelope_pb2.Ack(ok=True)
        client.send.return_value = ack

        result = retry_send(client, _make_envelope())
        assert result is ack
        mock_sleep.assert_not_called()

    @patch("macp_sdk.retry.time.sleep")
    def test_retries_on_transport_error(self, mock_sleep):
        client = MagicMock()
        ack = envelope_pb2.Ack(ok=True)
        client.send.side_effect = [MacpTransportError("boom"), ack]

        result = retry_send(client, _make_envelope())
        assert result is ack
        assert mock_sleep.call_count == 1

    @patch("macp_sdk.retry.time.sleep")
    def test_retries_on_retryable_nack(self, mock_sleep):
        client = MagicMock()
        ack = envelope_pb2.Ack(ok=True)
        failure = AckFailure(code="RATE_LIMITED", message="slow down")
        client.send.side_effect = [MacpAckError(failure), ack]

        result = retry_send(client, _make_envelope())
        assert result is ack

    @patch("macp_sdk.retry.time.sleep")
    def test_does_not_retry_non_retryable_nack(self, mock_sleep):
        client = MagicMock()
        failure = AckFailure(code="FORBIDDEN", message="denied")
        client.send.side_effect = MacpAckError(failure)

        with pytest.raises(MacpAckError):
            retry_send(client, _make_envelope())
        mock_sleep.assert_not_called()

    @patch("macp_sdk.retry.time.sleep")
    def test_exhausts_retries(self, mock_sleep):
        client = MagicMock()
        client.send.side_effect = MacpTransportError("boom")

        policy = RetryPolicy(max_retries=2)
        with pytest.raises(MacpRetryError, match="retries exhausted"):
            retry_send(client, _make_envelope(), policy=policy)
        assert client.send.call_count == 3  # 1 initial + 2 retries
