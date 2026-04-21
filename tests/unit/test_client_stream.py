"""Tests for ``MacpStream`` — the bidirectional session stream helper.

Covers the RFC-MACP-0006-A1 subscribe frame (``send_subscribe``) added
alongside envelope sends, plus the request-iterator multiplex and
closed-stream guards.
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest
from macp.v1 import core_pb2, envelope_pb2

from macp_sdk.client import MacpStream
from macp_sdk.errors import MacpSdkError


def _make_stub() -> tuple[MagicMock, threading.Event, list[core_pb2.StreamSessionRequest]]:
    """Build a stub whose ``StreamSession`` drains and records outgoing requests.

    Returns ``(stub, drained, captured)`` — ``drained`` fires once the
    request iterator reaches its ``_END`` sentinel, so tests can close
    the stream and deterministically wait for the drain.
    """
    drained = threading.Event()
    captured: list[core_pb2.StreamSessionRequest] = []

    def stream_session(request_iter, metadata=None, timeout=None):
        def _drain() -> None:
            try:
                for req in request_iter:
                    captured.append(req)
            finally:
                drained.set()

        threading.Thread(target=_drain, daemon=True).start()

        # Return an empty response iterator so the response pump exits
        # cleanly; tests here only care about the request side.
        return iter([])

    stub = MagicMock()
    stub.StreamSession.side_effect = stream_session
    return stub, drained, captured


class TestSendSubscribe:
    def test_subscribe_frame_has_session_id_and_sequence(self):
        stub, drained, captured = _make_stub()
        stream = MacpStream(stub, metadata=[])
        try:
            stream.send_subscribe("sess-42", after_sequence=7)
        finally:
            stream.close()
        assert drained.wait(timeout=2.0), "request iterator should drain after close"

        assert len(captured) == 1
        req = captured[0]
        assert isinstance(req, core_pb2.StreamSessionRequest)
        assert req.subscribe_session_id == "sess-42"
        assert req.after_sequence == 7
        # envelope must not be set when subscribing
        assert req.envelope.ByteSize() == 0

    def test_subscribe_default_sequence_is_zero(self):
        stub, drained, captured = _make_stub()
        stream = MacpStream(stub, metadata=[])
        try:
            stream.send_subscribe("sess-0")
        finally:
            stream.close()
        assert drained.wait(timeout=2.0)

        assert captured[0].subscribe_session_id == "sess-0"
        assert captured[0].after_sequence == 0

    def test_subscribe_after_close_raises(self):
        stub, _, _ = _make_stub()
        stream = MacpStream(stub, metadata=[])
        stream.close()
        with pytest.raises(MacpSdkError, match="stream is already closed"):
            stream.send_subscribe("sess-1")


class TestRequestIterMultiplex:
    """``_request_iter`` must forward subscribe frames as-is and wrap envelopes."""

    def test_envelope_gets_wrapped_in_request(self):
        stub, drained, captured = _make_stub()
        stream = MacpStream(stub, metadata=[])
        env = envelope_pb2.Envelope(
            macp_version="1.0",
            message_type="Vote",
            session_id="sess-1",
            sender="alice",
        )
        try:
            stream.send(env)
        finally:
            stream.close()
        assert drained.wait(timeout=2.0)

        assert len(captured) == 1
        req = captured[0]
        assert req.envelope.session_id == "sess-1"
        assert req.subscribe_session_id == ""
        assert req.after_sequence == 0

    def test_subscribe_and_envelope_can_be_interleaved(self):
        """Subscribe first, then send — both frames must reach the server
        in order so non-initiators can observe replay before publishing."""
        stub, drained, captured = _make_stub()
        stream = MacpStream(stub, metadata=[])
        env = envelope_pb2.Envelope(
            macp_version="1.0",
            message_type="Vote",
            session_id="sess-mix",
            sender="bob",
        )
        try:
            stream.send_subscribe("sess-mix", after_sequence=3)
            stream.send(env)
        finally:
            stream.close()
        assert drained.wait(timeout=2.0)

        assert len(captured) == 2
        assert captured[0].subscribe_session_id == "sess-mix"
        assert captured[0].after_sequence == 3
        assert captured[1].envelope.message_type == "Vote"


class TestSubscribeFrameProto:
    """Regression guard: the subscribe frame must serialise with the fields
    on the wire the runtime expects (RFC-MACP-0006-A1)."""

    def test_subscribe_frame_roundtrips_through_proto(self):
        req = core_pb2.StreamSessionRequest(
            subscribe_session_id="sess-roundtrip",
            after_sequence=42,
        )
        buf = req.SerializeToString()
        parsed = core_pb2.StreamSessionRequest()
        parsed.ParseFromString(buf)
        assert parsed.subscribe_session_id == "sess-roundtrip"
        assert parsed.after_sequence == 42
        assert parsed.envelope.ByteSize() == 0


class TestSendAfterCloseStillGuarded:
    """Regression guard: the new subscribe path must not regress the
    existing ``send`` closed-stream contract."""

    def test_send_after_close_raises(self):
        stub, _, _ = _make_stub()
        stream = MacpStream(stub, metadata=[])
        stream.close()
        env = envelope_pb2.Envelope(message_type="Vote", session_id="x")
        with pytest.raises(MacpSdkError, match="stream is already closed"):
            stream.send(env)


class TestResubscribe:
    """The runtime accepts multiple subscribe frames on the same stream
    (e.g. a reconnecting consumer first replays from 0, then re-subscribes
    from a higher sequence after applying snapshot)."""

    def test_two_subscribes_are_both_forwarded(self):
        stub, drained, captured = _make_stub()
        stream = MacpStream(stub, metadata=[])
        try:
            stream.send_subscribe("sess-re", after_sequence=0)
            stream.send_subscribe("sess-re", after_sequence=12)
        finally:
            stream.close()
        assert drained.wait(timeout=2.0)

        assert len(captured) == 2
        assert captured[0].after_sequence == 0
        assert captured[1].after_sequence == 12
        assert all(req.subscribe_session_id == "sess-re" for req in captured)


class TestReadAfterCloseReturnsNone:
    """The response pump must drain cleanly when the stream is closed
    immediately after a subscribe frame — no hang, no spurious envelope."""

    def test_read_drains_after_close(self):
        stub, drained, _ = _make_stub()
        stream = MacpStream(stub, metadata=[])
        stream.send_subscribe("sess-drain")
        stream.close()
        assert drained.wait(timeout=2.0)
        # With an empty upstream response iterator the pump posts _END and
        # ``read`` returns ``None`` without blocking.
        assert stream.read(timeout=2.0) is None
