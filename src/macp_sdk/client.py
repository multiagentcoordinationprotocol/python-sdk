from __future__ import annotations

import queue
import threading
from collections.abc import Callable, Iterator, Sequence
from typing import Any

import grpc
from macp.v1 import core_pb2, core_pb2_grpc, envelope_pb2, policy_pb2

from ._logging import logger
from .auth import AuthConfig
from .envelope import (
    build_envelope,
    build_progress_payload,
    build_signal_payload,
    serialize_message,
)
from .errors import (
    AckFailure,
    MacpAckError,
    MacpIdentityMismatchError,
    MacpSdkError,
    MacpTransportError,
)


def _parse_ack_reasons(ack: object) -> list[str]:
    """Extract structured denial reasons from an ACK error's details."""
    import json as _json

    error = getattr(ack, "error", None)
    if not error:
        return []
    details_bytes = getattr(error, "details", None) or b""
    if not details_bytes:
        return []
    try:
        parsed = _json.loads(details_bytes)
        reasons = parsed.get("reasons", [])
        return list(reasons) if isinstance(reasons, list) else []
    except Exception:
        return []


def _parse_grpc_metadata_reasons(rpc_error: grpc.RpcError) -> list[str]:
    """Extract structured reasons from gRPC trailing metadata."""
    import json as _json

    try:
        metadata = rpc_error.trailing_metadata()
        if not metadata:
            return []
        for item in metadata:
            key, value = item.key, item.value
            if key == "macp-error-details-bin":
                data = value if isinstance(value, bytes) else value.encode("utf-8")
                parsed = _json.loads(data)
                reasons = parsed.get("reasons", [])
                return list(reasons) if isinstance(reasons, list) else []
    except Exception:
        pass
    return []


def _default_capabilities() -> core_pb2.Capabilities:
    return core_pb2.Capabilities(
        sessions=core_pb2.SessionsCapability(stream=True),
        cancellation=core_pb2.CancellationCapability(cancel_session=True),
        progress=core_pb2.ProgressCapability(progress=True),
        manifest=core_pb2.ManifestCapability(get_manifest=True),
        mode_registry=core_pb2.ModeRegistryCapability(list_modes=True, list_changed=True),
        roots=core_pb2.RootsCapability(list_roots=True, list_changed=True),
        policy_registry=policy_pb2.PolicyRegistryCapability(
            register_policy=True, list_policies=True, list_changed=True
        ),
        experimental=core_pb2.ExperimentalCapabilities(features={}),
    )


class MacpStream:
    _END = object()

    def __init__(
        self,
        stub: core_pb2_grpc.MACPRuntimeServiceStub,
        *,
        metadata: Sequence[tuple[str, str]],
        timeout: float | None = None,
    ) -> None:
        self._requests: queue.Queue[object] = queue.Queue()
        self._responses: queue.Queue[object] = queue.Queue()
        self._closed = False
        self._inline_error_callbacks: list[Callable[[Any], None]] = []
        self._call = stub.StreamSession(self._request_iter(), metadata=metadata, timeout=timeout)
        self._thread = threading.Thread(target=self._pump_responses, daemon=True)
        self._thread.start()

    def _request_iter(self) -> Iterator[core_pb2.StreamSessionRequest]:
        while True:
            item = self._requests.get()
            if item is self._END:
                return
            assert isinstance(item, envelope_pb2.Envelope)
            yield core_pb2.StreamSessionRequest(envelope=item)

    def _pump_responses(self) -> None:
        try:
            for response in self._call:
                # Support both formats:
                #   New: StreamSessionResponse { response: { envelope | error } }
                #   Old: StreamSessionResponse { envelope }
                inner = getattr(response, "response", None)
                if inner is not None and hasattr(inner, "ByteSize") and inner.ByteSize() > 0:
                    envelope = getattr(inner, "envelope", None)
                    error = getattr(inner, "error", None)
                    if envelope is not None and envelope.ByteSize() > 0:
                        self._responses.put(envelope)
                    elif error is not None:
                        # Inline application-level error — notify callbacks, keep stream open
                        for cb in self._inline_error_callbacks:
                            cb(error)
                        logger.warning("inline stream error: %s", error)
                        continue
                else:
                    # Flat format: response.envelope
                    self._responses.put(response.envelope)
        except grpc.RpcError as exc:
            self._responses.put(exc)
        finally:
            self._responses.put(self._END)

    def on_inline_error(self, callback: Callable[[Any], None]) -> None:
        """Register a callback for inline application-level stream errors."""
        self._inline_error_callbacks.append(callback)

    def send(self, envelope: envelope_pb2.Envelope) -> None:
        if self._closed:
            raise MacpSdkError("stream is already closed")
        self._requests.put(envelope)

    def read(self, timeout: float | None = None) -> envelope_pb2.Envelope | None:
        item = self._responses.get(timeout=timeout)
        if item is self._END:
            return None
        if isinstance(item, grpc.RpcError):
            raise MacpTransportError(item.details() or str(item))
        assert isinstance(item, envelope_pb2.Envelope)
        return item

    def responses(self, timeout: float | None = None) -> Iterator[envelope_pb2.Envelope]:
        while True:
            envelope = self.read(timeout=timeout)
            if envelope is None:
                return
            yield envelope

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._requests.put(self._END)


class MacpClient:
    """gRPC client for the MACP runtime.

    Transport security follows RFC-MACP-0006 §3: TLS 1.2+ is REQUIRED in
    production, so ``secure`` defaults to ``True``. Plaintext gRPC is only
    available via the explicit ``allow_insecure=True`` opt-in, which is
    intended for local development against a runtime started with
    ``MACP_ALLOW_INSECURE=1``.
    """

    def __init__(
        self,
        *,
        target: str,
        secure: bool | None = None,
        allow_insecure: bool = False,
        auth: AuthConfig | None = None,
        root_certificates: bytes | None = None,
        default_timeout: float | None = None,
        client_name: str = "macp-sdk-python",
        client_version: str = "0.2.1",
    ) -> None:
        if secure is None:
            secure = not allow_insecure
        if not secure and not allow_insecure:
            raise MacpSdkError(
                "secure=False requires allow_insecure=True; "
                "TLS is required by RFC-MACP-0006 §3 in production. "
                "For local dev only, pass allow_insecure=True."
            )
        self.target = target
        self.secure = secure
        self.auth = auth
        self.default_timeout = default_timeout
        self.client_name = client_name
        self.client_version = client_version
        if secure:
            creds = grpc.ssl_channel_credentials(root_certificates=root_certificates)
            self.channel = grpc.secure_channel(target, creds)
        else:
            logger.warning("MacpClient insecure channel to %s — allowed only for local dev", target)
            self.channel = grpc.insecure_channel(target)
        self.stub = core_pb2_grpc.MACPRuntimeServiceStub(self.channel)

    def close(self) -> None:
        self.channel.close()

    def __enter__(self) -> MacpClient:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def _metadata(self, auth: AuthConfig | None = None) -> Sequence[tuple[str, str]]:
        selected = auth or self.auth
        return selected.metadata() if selected else []

    def _require_auth(self, auth: AuthConfig | None = None) -> AuthConfig:
        selected = auth or self.auth
        if selected is None:
            raise MacpSdkError("this operation requires auth; pass auth= or configure client.auth")
        return selected

    @staticmethod
    def _resolve_sender(auth_cfg: AuthConfig, sender: str) -> str:
        """Resolve and validate the envelope sender against auth.expected_sender.

        Raises :class:`MacpIdentityMismatchError` when an explicit ``sender``
        contradicts ``auth_cfg.expected_sender``. Returns the effective sender
        string to place on the envelope (possibly the fallback from ``auth_cfg``).
        """
        expected = auth_cfg.expected_sender
        if sender:
            if expected is not None and sender != expected:
                raise MacpIdentityMismatchError(expected=expected, actual=sender)
            return sender
        return auth_cfg.sender or ""

    @staticmethod
    def _failure_from_ack(ack: envelope_pb2.Ack) -> AckFailure:
        """Build an :class:`AckFailure` from a NACK envelope, including reasons.

        Used by every RPC that returns an ``Ack`` (``send``, ``cancel_session``)
        so structured denial reasons (``POLICY_DENIED`` rule IDs, etc.) surface
        uniformly in ``MacpAckError.reasons`` no matter which call produced
        them.
        """
        error = ack.error
        return AckFailure(
            code=(error.code if error else "UNKNOWN"),
            message=(error.message if error else "runtime returned nack"),
            session_id=ack.session_id,
            message_id=ack.message_id,
            reasons=_parse_ack_reasons(ack),
        )

    def initialize(self, *, timeout: float | None = None) -> core_pb2.InitializeResponse:
        request = core_pb2.InitializeRequest(
            supported_protocol_versions=["1.0"],
            client_info=core_pb2.ClientInfo(
                name=self.client_name,
                title=self.client_name,
                version=self.client_version,
                description="Python SDK for the MACP runtime",
                website_url="",
            ),
            capabilities=_default_capabilities(),
        )
        return self.stub.Initialize(request, timeout=timeout or self.default_timeout)

    def send(
        self,
        envelope: envelope_pb2.Envelope,
        *,
        auth: AuthConfig | None = None,
        timeout: float | None = None,
        raise_on_nack: bool = True,
    ) -> envelope_pb2.Ack:
        auth_cfg = self._require_auth(auth)
        try:
            response = self.stub.Send(
                core_pb2.SendRequest(envelope=envelope),
                metadata=self._metadata(auth_cfg),
                timeout=timeout or self.default_timeout,
            )
        except grpc.RpcError as rpc_err:
            code = rpc_err.code()
            if code == grpc.StatusCode.ALREADY_EXISTS:
                failure = AckFailure(
                    code="SESSION_ALREADY_EXISTS",
                    message=rpc_err.details() or "session already exists",
                )
                raise MacpAckError(failure) from rpc_err
            if code == grpc.StatusCode.FAILED_PRECONDITION:
                reasons = _parse_grpc_metadata_reasons(rpc_err)
                failure = AckFailure(
                    code="POLICY_DENIED",
                    message=rpc_err.details() or "policy denied",
                    reasons=reasons,
                )
                raise MacpAckError(failure) from rpc_err
            if code == grpc.StatusCode.INVALID_ARGUMENT:
                raise MacpTransportError(rpc_err.details() or "invalid argument") from rpc_err
            raise MacpTransportError(rpc_err.details() or str(rpc_err)) from rpc_err
        ack = response.ack
        # Duplicate acks are idempotent success — the message was already accepted.
        # This matches TypeScript SDK behaviour and is correct for retry scenarios.
        if ack.duplicate:
            return ack
        if raise_on_nack and not ack.ok:
            raise MacpAckError(self._failure_from_ack(ack))
        return ack

    def get_session(
        self,
        session_id: str,
        *,
        auth: AuthConfig | None = None,
        timeout: float | None = None,
    ) -> core_pb2.GetSessionResponse:
        auth_cfg = self._require_auth(auth)
        return self.stub.GetSession(
            core_pb2.GetSessionRequest(session_id=session_id),
            metadata=self._metadata(auth_cfg),
            timeout=timeout or self.default_timeout,
        )

    def cancel_session(
        self,
        session_id: str,
        *,
        reason: str,
        cancelled_by: str = "",
        auth: AuthConfig | None = None,
        timeout: float | None = None,
        raise_on_nack: bool = True,
    ) -> envelope_pb2.Ack:
        auth_cfg = self._require_auth(auth)
        request_kwargs: dict[str, object] = {
            "session_id": session_id,
            "reason": reason,
        }
        # Forward-compatible: add cancelled_by if proto supports it
        if cancelled_by:
            has_field = any(
                f.name == "cancelled_by" for f in core_pb2.CancelSessionRequest.DESCRIPTOR.fields
            )
            if has_field:
                request_kwargs["cancelled_by"] = cancelled_by
        try:
            response = self.stub.CancelSession(
                core_pb2.CancelSessionRequest(**request_kwargs),
                metadata=self._metadata(auth_cfg),
                timeout=timeout or self.default_timeout,
            )
        except grpc.RpcError as rpc_err:
            raise MacpTransportError(rpc_err.details() or str(rpc_err)) from rpc_err
        ack = response.ack
        if raise_on_nack and not ack.ok:
            raise MacpAckError(self._failure_from_ack(ack))
        return ack

    def get_manifest(
        self, agent_id: str = "", *, timeout: float | None = None
    ) -> core_pb2.GetManifestResponse:
        return self.stub.GetManifest(
            core_pb2.GetManifestRequest(agent_id=agent_id),
            timeout=timeout or self.default_timeout,
        )

    def list_modes(self, *, timeout: float | None = None) -> core_pb2.ListModesResponse:
        return self.stub.ListModes(
            core_pb2.ListModesRequest(),
            timeout=timeout or self.default_timeout,
        )

    def list_ext_modes(self, *, timeout: float | None = None) -> core_pb2.ListExtModesResponse:
        return self.stub.ListExtModes(
            core_pb2.ListExtModesRequest(),
            timeout=timeout or self.default_timeout,
        )

    def list_roots(self, *, timeout: float | None = None) -> core_pb2.ListRootsResponse:
        return self.stub.ListRoots(
            core_pb2.ListRootsRequest(),
            timeout=timeout or self.default_timeout,
        )

    def register_ext_mode(
        self,
        descriptor: core_pb2.ModeDescriptor,
        *,
        auth: AuthConfig | None = None,
        timeout: float | None = None,
    ) -> core_pb2.RegisterExtModeResponse:
        auth_cfg = self._require_auth(auth)
        return self.stub.RegisterExtMode(
            core_pb2.RegisterExtModeRequest(mode_descriptor=descriptor),
            metadata=self._metadata(auth_cfg),
            timeout=timeout or self.default_timeout,
        )

    def unregister_ext_mode(
        self,
        mode: str,
        *,
        auth: AuthConfig | None = None,
        timeout: float | None = None,
    ) -> core_pb2.UnregisterExtModeResponse:
        auth_cfg = self._require_auth(auth)
        return self.stub.UnregisterExtMode(
            core_pb2.UnregisterExtModeRequest(mode=mode),
            metadata=self._metadata(auth_cfg),
            timeout=timeout or self.default_timeout,
        )

    def promote_mode(
        self,
        mode: str,
        promoted_mode_name: str = "",
        *,
        auth: AuthConfig | None = None,
        timeout: float | None = None,
    ) -> core_pb2.PromoteModeResponse:
        auth_cfg = self._require_auth(auth)
        return self.stub.PromoteMode(
            core_pb2.PromoteModeRequest(mode=mode, promoted_mode_name=promoted_mode_name),
            metadata=self._metadata(auth_cfg),
            timeout=timeout or self.default_timeout,
        )

    # ── Governance policy lifecycle ───────────────────────────────────

    def register_policy(
        self,
        descriptor: policy_pb2.PolicyDescriptor,
        *,
        auth: AuthConfig | None = None,
        timeout: float | None = None,
    ) -> policy_pb2.RegisterPolicyResponse:
        """Register a governance policy with the runtime."""
        auth_cfg = self._require_auth(auth)
        return self.stub.RegisterPolicy(
            policy_pb2.RegisterPolicyRequest(policy_descriptor=descriptor),
            metadata=self._metadata(auth_cfg),
            timeout=timeout or self.default_timeout,
        )

    def unregister_policy(
        self,
        policy_id: str,
        *,
        auth: AuthConfig | None = None,
        timeout: float | None = None,
    ) -> policy_pb2.UnregisterPolicyResponse:
        """Unregister a governance policy from the runtime."""
        auth_cfg = self._require_auth(auth)
        return self.stub.UnregisterPolicy(
            policy_pb2.UnregisterPolicyRequest(policy_id=policy_id),
            metadata=self._metadata(auth_cfg),
            timeout=timeout or self.default_timeout,
        )

    def get_policy(
        self,
        policy_id: str,
        *,
        auth: AuthConfig | None = None,
        timeout: float | None = None,
    ) -> policy_pb2.GetPolicyResponse:
        """Retrieve a single governance policy by ID."""
        auth_cfg = self._require_auth(auth)
        return self.stub.GetPolicy(
            policy_pb2.GetPolicyRequest(policy_id=policy_id),
            metadata=self._metadata(auth_cfg),
            timeout=timeout or self.default_timeout,
        )

    def list_policies(
        self,
        mode: str | None = None,
        *,
        auth: AuthConfig | None = None,
        timeout: float | None = None,
    ) -> policy_pb2.ListPoliciesResponse:
        """List registered governance policies, optionally filtered by mode."""
        auth_cfg = self._require_auth(auth)
        return self.stub.ListPolicies(
            policy_pb2.ListPoliciesRequest(mode=mode or ""),
            metadata=self._metadata(auth_cfg),
            timeout=timeout or self.default_timeout,
        )

    def watch_policies(
        self, *, timeout: float | None = None
    ) -> Iterator[policy_pb2.WatchPoliciesResponse]:
        """Server-streaming RPC: yields governance policy change events."""
        logger.debug("watch_policies starting")
        call = self.stub.WatchPolicies(
            policy_pb2.WatchPoliciesRequest(),
            timeout=timeout or self.default_timeout,
        )
        try:
            yield from call
        except grpc.RpcError as exc:
            raise MacpTransportError(str(exc)) from exc

    def open_stream(
        self, *, auth: AuthConfig | None = None, timeout: float | None = None
    ) -> MacpStream:
        auth_cfg = self._require_auth(auth)
        return MacpStream(
            self.stub,
            metadata=self._metadata(auth_cfg),
            timeout=timeout or self.default_timeout,
        )

    def watch_mode_registry(
        self, *, timeout: float | None = None
    ) -> Iterator[core_pb2.WatchModeRegistryResponse]:
        """Server-streaming RPC: yields mode registry change events."""
        logger.debug("watch_mode_registry starting")
        call = self.stub.WatchModeRegistry(
            core_pb2.WatchModeRegistryRequest(),
            timeout=timeout or self.default_timeout,
        )
        try:
            yield from call
        except grpc.RpcError as exc:
            raise MacpTransportError(str(exc)) from exc

    def watch_roots(self, *, timeout: float | None = None) -> Iterator[core_pb2.WatchRootsResponse]:
        """Server-streaming RPC: yields root change events."""
        logger.debug("watch_roots starting")
        call = self.stub.WatchRoots(
            core_pb2.WatchRootsRequest(),
            timeout=timeout or self.default_timeout,
        )
        try:
            yield from call
        except grpc.RpcError as exc:
            raise MacpTransportError(str(exc)) from exc

    def watch_signals(
        self, *, timeout: float | None = None
    ) -> Iterator[core_pb2.WatchSignalsResponse]:
        """Server-streaming RPC: yields ambient signal envelopes."""
        logger.debug("watch_signals starting")
        call = self.stub.WatchSignals(
            core_pb2.WatchSignalsRequest(),
            timeout=timeout or self.default_timeout,
        )
        try:
            yield from call
        except grpc.RpcError as exc:
            raise MacpTransportError(str(exc)) from exc

    def send_signal(
        self,
        *,
        signal_type: str,
        data: bytes = b"",
        confidence: float = 0.0,
        correlation_session_id: str = "",
        sender: str = "",
        auth: AuthConfig | None = None,
        timeout: float | None = None,
    ) -> envelope_pb2.Ack:
        """Send an ambient (non-session) signal to the runtime."""
        auth_cfg = self._require_auth(auth)
        payload = build_signal_payload(
            signal_type=signal_type,
            data=data,
            confidence=confidence,
            correlation_session_id=correlation_session_id,
        )
        envelope = build_envelope(
            mode="",
            message_type="Signal",
            session_id="",
            payload=serialize_message(payload),
            sender=self._resolve_sender(auth_cfg, sender),
        )
        return self.send(envelope, auth=auth_cfg, timeout=timeout)

    def send_progress(
        self,
        *,
        session_id: str = "",
        mode: str = "",
        progress_token: str,
        progress: float,
        total: float,
        message: str = "",
        target_message_id: str = "",
        sender: str = "",
        auth: AuthConfig | None = None,
        timeout: float | None = None,
    ) -> envelope_pb2.Ack:
        """Send a progress update.

        When ``session_id`` and ``mode`` are empty, the progress is treated
        as an *ambient* progress message routed through the signal broadcast
        path.
        """
        auth_cfg = self._require_auth(auth)
        payload = build_progress_payload(
            progress_token=progress_token,
            progress=progress,
            total=total,
            message=message,
            target_message_id=target_message_id,
        )
        envelope = build_envelope(
            mode=mode,
            message_type="Progress",
            session_id=session_id,
            payload=serialize_message(payload),
            sender=self._resolve_sender(auth_cfg, sender),
        )
        return self.send(envelope, auth=auth_cfg, timeout=timeout)
