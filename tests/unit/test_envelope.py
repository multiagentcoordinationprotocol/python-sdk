from __future__ import annotations

from macp_sdk.envelope import (
    build_commitment_payload,
    build_envelope,
    build_root,
    build_session_start_payload,
    encode_context,
    new_commitment_id,
    new_message_id,
    new_session_id,
    serialize_message,
)


class TestIdGenerators:
    def test_session_id_is_uuid(self):
        sid = new_session_id()
        assert len(sid) == 36 and sid.count("-") == 4

    def test_message_id_unique(self):
        assert new_message_id() != new_message_id()

    def test_commitment_id_unique(self):
        assert new_commitment_id() != new_commitment_id()


class TestEncodeContext:
    def test_none(self):
        assert encode_context(None) == b""

    def test_bytes(self):
        assert encode_context(b"raw") == b"raw"

    def test_str(self):
        assert encode_context("hello") == b"hello"

    def test_dict(self):
        result = encode_context({"key": "val"})
        assert b'"key"' in result


class TestBuildRoot:
    def test_build(self):
        root = build_root("file:///tmp", "tmp")
        assert root.uri == "file:///tmp"
        assert root.name == "tmp"


class TestBuildSessionStartPayload:
    def test_basic(self):
        payload = build_session_start_payload(
            intent="test",
            participants=["a", "b"],
            ttl_ms=60000,
        )
        assert payload.intent == "test"
        assert list(payload.participants) == ["a", "b"]
        assert payload.ttl_ms == 60000
        assert payload.mode_version == "1.0.0"


class TestBuildCommitmentPayload:
    def test_basic(self):
        payload = build_commitment_payload(
            action="deploy",
            authority_scope="release",
            reason="tests passed",
        )
        assert payload.action == "deploy"
        assert payload.commitment_id  # auto-generated


class TestBuildEnvelope:
    def test_basic(self):
        payload = build_session_start_payload(intent="x", participants=["a"], ttl_ms=1000)
        env = build_envelope(
            mode="macp.mode.decision.v1",
            message_type="SessionStart",
            session_id="sid-1",
            payload=serialize_message(payload),
            sender="alice",
        )
        assert env.mode == "macp.mode.decision.v1"
        assert env.message_type == "SessionStart"
        assert env.session_id == "sid-1"
        assert env.sender == "alice"
        assert env.message_id  # auto-generated
        assert env.timestamp_unix_ms > 0


class TestSerializeMessage:
    def test_protobuf(self):
        payload = build_root("file:///x")
        data = serialize_message(payload)
        assert isinstance(data, bytes)

    def test_non_protobuf_raises(self):
        import pytest

        with pytest.raises(TypeError):
            serialize_message("not a protobuf")  # type: ignore[arg-type]
