from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterable, Mapping, Sequence

from macp.v1 import core_pb2, envelope_pb2

from .constants import (
    DEFAULT_CONFIGURATION_VERSION,
    DEFAULT_MODE_VERSION,
    DEFAULT_POLICY_VERSION,
    MACP_VERSION,
)


def new_session_id() -> str:
    return str(uuid.uuid4())


def new_message_id() -> str:
    return str(uuid.uuid4())


def new_commitment_id() -> str:
    return str(uuid.uuid4())


def now_unix_ms() -> int:
    return int(time.time() * 1000)


def encode_context(context: bytes | str | Mapping[str, object] | None) -> bytes:
    if context is None:
        return b""
    if isinstance(context, bytes):
        return context
    if isinstance(context, str):
        return context.encode("utf-8")
    return json.dumps(context).encode("utf-8")


def build_root(uri: str, name: str = "") -> core_pb2.Root:
    return core_pb2.Root(uri=uri, name=name)


def build_session_start_payload(
    *,
    intent: str,
    participants: Sequence[str],
    ttl_ms: int,
    mode_version: str = DEFAULT_MODE_VERSION,
    configuration_version: str = DEFAULT_CONFIGURATION_VERSION,
    policy_version: str = DEFAULT_POLICY_VERSION,
    context: bytes | str | Mapping[str, object] | None = None,
    roots: Iterable[core_pb2.Root] | None = None,
) -> core_pb2.SessionStartPayload:
    return core_pb2.SessionStartPayload(
        intent=intent,
        participants=list(participants),
        mode_version=mode_version,
        configuration_version=configuration_version,
        policy_version=policy_version,
        ttl_ms=ttl_ms,
        context=encode_context(context),
        roots=list(roots or []),
    )


def build_commitment_payload(
    *,
    action: str,
    authority_scope: str,
    reason: str,
    commitment_id: str | None = None,
    mode_version: str = DEFAULT_MODE_VERSION,
    configuration_version: str = DEFAULT_CONFIGURATION_VERSION,
    policy_version: str = DEFAULT_POLICY_VERSION,
) -> core_pb2.CommitmentPayload:
    return core_pb2.CommitmentPayload(
        commitment_id=commitment_id or new_commitment_id(),
        action=action,
        authority_scope=authority_scope,
        reason=reason,
        mode_version=mode_version,
        configuration_version=configuration_version,
        policy_version=policy_version,
    )


def serialize_message(message: object) -> bytes:
    serializer = getattr(message, "SerializeToString", None)
    if serializer is None:
        raise TypeError(f"object {type(message)!r} is not a protobuf message")
    return serializer()


def build_envelope(
    *,
    mode: str,
    message_type: str,
    session_id: str,
    payload: bytes,
    sender: str = "",
    message_id: str | None = None,
    macp_version: str = MACP_VERSION,
    timestamp_unix_ms: int | None = None,
) -> envelope_pb2.Envelope:
    return envelope_pb2.Envelope(
        macp_version=macp_version,
        mode=mode,
        message_type=message_type,
        message_id=message_id or new_message_id(),
        session_id=session_id,
        sender=sender,
        timestamp_unix_ms=timestamp_unix_ms or now_unix_ms(),
        payload=payload,
    )
