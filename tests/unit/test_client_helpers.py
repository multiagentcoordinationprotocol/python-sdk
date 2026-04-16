"""Tests for the pure / easily-faked helpers on MacpClient.

These don't need a real gRPC server — the methods under test either
operate on proto objects directly or drive a mocked stub.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from macp.v1 import envelope_pb2

from macp_sdk.auth import AuthConfig
from macp_sdk.client import (
    MacpClient,
    _parse_ack_reasons,
    _parse_grpc_metadata_reasons,
)
from macp_sdk.errors import (
    MacpAckError,
    MacpIdentityMismatchError,
    MacpSdkError,
)


class TestParseAckReasons:
    def test_none_when_error_missing(self):
        ack = envelope_pb2.Ack(ok=True)
        assert _parse_ack_reasons(ack) == []

    def test_returns_parsed_list(self):
        ack = envelope_pb2.Ack(ok=False)
        ack.error.code = "POLICY_DENIED"
        ack.error.message = "nope"
        ack.error.details = json.dumps({"reasons": ["a", "b"]}).encode()
        assert _parse_ack_reasons(ack) == ["a", "b"]

    def test_malformed_details_returns_empty(self):
        ack = envelope_pb2.Ack(ok=False)
        ack.error.code = "x"
        ack.error.details = b"{not-json"
        assert _parse_ack_reasons(ack) == []

    def test_non_list_reasons_yields_empty(self):
        ack = envelope_pb2.Ack(ok=False)
        ack.error.code = "x"
        ack.error.details = json.dumps({"reasons": "single"}).encode()
        assert _parse_ack_reasons(ack) == []


class TestParseGrpcMetadataReasons:
    def _rpc_error_with_metadata(self, metadata: list) -> MagicMock:
        exc = MagicMock()
        exc.trailing_metadata.return_value = metadata

        class _MDItem:
            def __init__(self, k, v):
                self.key = k
                self.value = v

        exc.trailing_metadata.return_value = [_MDItem(k, v) for k, v in metadata]
        return exc

    def test_reads_bin_metadata_json(self):
        exc = self._rpc_error_with_metadata(
            [("macp-error-details-bin", json.dumps({"reasons": ["x"]}).encode())]
        )
        assert _parse_grpc_metadata_reasons(exc) == ["x"]

    def test_missing_bin_key_returns_empty(self):
        exc = self._rpc_error_with_metadata([("some-other-key", b"whatever")])
        assert _parse_grpc_metadata_reasons(exc) == []

    def test_no_metadata_returns_empty(self):
        exc = MagicMock()
        exc.trailing_metadata.return_value = None
        assert _parse_grpc_metadata_reasons(exc) == []


class TestRequireAuth:
    def test_no_auth_raises(self):
        client = MacpClient(target="localhost:0", allow_insecure=True)
        with pytest.raises(MacpSdkError, match="requires auth"):
            client._require_auth()

    def test_method_level_override_wins(self):
        client_auth = AuthConfig.for_bearer("c")
        method_auth = AuthConfig.for_bearer("m")
        client = MacpClient(target="localhost:0", allow_insecure=True, auth=client_auth)
        assert client._require_auth(method_auth) is method_auth

    def test_falls_back_to_client_auth(self):
        client_auth = AuthConfig.for_bearer("c")
        client = MacpClient(target="localhost:0", allow_insecure=True, auth=client_auth)
        assert client._require_auth() is client_auth


class TestResolveSender:
    def test_explicit_match_returns_explicit(self):
        auth = AuthConfig.for_bearer("tok", expected_sender="alice")
        assert MacpClient._resolve_sender(auth, "alice") == "alice"

    def test_explicit_mismatch_raises(self):
        auth = AuthConfig.for_bearer("tok", expected_sender="alice")
        with pytest.raises(MacpIdentityMismatchError):
            MacpClient._resolve_sender(auth, "mallory")

    def test_missing_sender_uses_hint(self):
        auth = AuthConfig.for_bearer("tok", expected_sender="alice")
        assert MacpClient._resolve_sender(auth, "") == "alice"

    def test_no_expected_sender_skips_check(self):
        auth = AuthConfig.for_bearer("tok")
        assert MacpClient._resolve_sender(auth, "whoever") == "whoever"


class TestMetadataPassThrough:
    def test_no_auth_returns_empty(self):
        client = MacpClient(target="localhost:0", allow_insecure=True)
        assert client._metadata() == []

    def test_bearer_metadata(self):
        auth = AuthConfig.for_bearer("tok-1", expected_sender="alice")
        client = MacpClient(target="localhost:0", allow_insecure=True, auth=auth)
        assert ("authorization", "Bearer tok-1") in client._metadata()

    def test_dev_agent_metadata(self):
        auth = AuthConfig.for_dev_agent("alice")
        client = MacpClient(target="localhost:0", allow_insecure=True, auth=auth)
        assert ("x-macp-agent-id", "alice") in client._metadata()


class TestSendDuplicateIsIdempotentSuccess:
    def test_duplicate_ack_returns_without_raise(self):
        """Runtime replay returns duplicate=true — that's success, not a NACK."""
        auth = AuthConfig.for_bearer("tok")
        client = MacpClient(target="localhost:0", allow_insecure=True, auth=auth)
        client.stub = MagicMock()
        client.stub.Send.return_value = MagicMock(ack=envelope_pb2.Ack(ok=False, duplicate=True))
        env = envelope_pb2.Envelope(message_type="Vote", session_id="x")
        ack = client.send(env)
        assert ack.duplicate is True


class TestSendRaisesStructuredAckError:
    def test_nack_with_reasons_parsed_into_failure(self):
        auth = AuthConfig.for_bearer("tok")
        client = MacpClient(target="localhost:0", allow_insecure=True, auth=auth)
        client.stub = MagicMock()
        bad_ack = envelope_pb2.Ack(ok=False, session_id="s-1", message_id="m-1", duplicate=False)
        bad_ack.error.code = "POLICY_DENIED"
        bad_ack.error.message = "nope"
        bad_ack.error.details = json.dumps({"reasons": ["rule-1", "rule-2"]}).encode()
        client.stub.Send.return_value = MagicMock(ack=bad_ack)
        env = envelope_pb2.Envelope(message_type="Vote", session_id="s-1")
        with pytest.raises(MacpAckError) as exc:
            client.send(env)
        assert exc.value.failure.code == "POLICY_DENIED"
        assert exc.value.failure.reasons == ["rule-1", "rule-2"]


class TestCancelSessionReasonParsing:
    """Q-1: cancel_session must surface structured denial reasons too."""

    def test_nack_reasons_propagate_through_cancel(self):
        auth = AuthConfig.for_bearer("tok")
        client = MacpClient(target="localhost:0", allow_insecure=True, auth=auth)
        client.stub = MagicMock()
        bad_ack = envelope_pb2.Ack(ok=False, session_id="s-1", message_id="", duplicate=False)
        bad_ack.error.code = "POLICY_DENIED"
        bad_ack.error.message = "not cancellable by this sender"
        bad_ack.error.details = json.dumps({"reasons": ["cancellation_not_delegated"]}).encode()
        client.stub.CancelSession.return_value = MagicMock(ack=bad_ack)

        with pytest.raises(MacpAckError) as exc:
            client.cancel_session("s-1", reason="timeout")
        assert exc.value.failure.code == "POLICY_DENIED"
        assert exc.value.failure.session_id == "s-1"
        assert exc.value.failure.reasons == ["cancellation_not_delegated"]
