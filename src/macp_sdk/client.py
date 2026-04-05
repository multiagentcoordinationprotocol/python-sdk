from __future__ import annotations

import queue
import threading
from collections.abc import Iterator, Sequence

import grpc

from macp.v1 import core_pb2, core_pb2_grpc, envelope_pb2

from ._logging import logger
from .auth import AuthConfig
from .envelope import (
    build_envelope,
    build_progress_payload,
    build_signal_payload,
    serialize_message,
)
from .errors import AckFailure, MacpAckError, MacpSdkError, MacpTransportError


def _default_capabilities() -> core_pb2.Capabilities:
    return core_pb2.Capabilities(
        sessions=core_pb2.SessionsCapability(stream=True),
        cancellation=core_pb2.CancellationCapability(cancel_session=True),
        progress=core_pb2.ProgressCapability(progress=True),
        manifest=core_pb2.ManifestCapability(get_manifest=True),
        mode_registry=core_pb2.ModeRegistryCapability(list_modes=True, list_changed=True),
        roots=core_pb2.RootsCapability(list_roots=True, list_changed=True),
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
                self._responses.put(response.envelope)
        except grpc.RpcError as exc:
            self._responses.put(exc)
        finally:
            self._responses.put(self._END)

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
    def __init__(
        self,
        *,
        target: str,
        secure: bool = False,
        auth: AuthConfig | None = None,
        root_certificates: bytes | None = None,
        default_timeout: float | None = None,
        client_name: str = "macp-sdk-python",
        client_version: str = "0.1.0",
    ) -> None:
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
        response = self.stub.Send(
            core_pb2.SendRequest(envelope=envelope),
            metadata=self._metadata(auth_cfg),
            timeout=timeout or self.default_timeout,
        )
        ack = response.ack
        if raise_on_nack and not ack.ok:
            error = ack.error
            failure = AckFailure(
                code=(error.code if error else "UNKNOWN"),
                message=(error.message if error else "runtime returned nack"),
                session_id=ack.session_id,
                message_id=ack.message_id,
            )
            raise MacpAckError(failure)
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
        auth: AuthConfig | None = None,
        timeout: float | None = None,
        raise_on_nack: bool = True,
    ) -> envelope_pb2.Ack:
        auth_cfg = self._require_auth(auth)
        response = self.stub.CancelSession(
            core_pb2.CancelSessionRequest(session_id=session_id, reason=reason),
            metadata=self._metadata(auth_cfg),
            timeout=timeout or self.default_timeout,
        )
        ack = response.ack
        if raise_on_nack and not ack.ok:
            error = ack.error
            failure = AckFailure(
                code=(error.code if error else "UNKNOWN"),
                message=(error.message if error else "runtime returned nack"),
                session_id=ack.session_id,
                message_id=ack.message_id,
            )
            raise MacpAckError(failure)
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
            core_pb2.RegisterExtModeRequest(descriptor=descriptor),
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
            sender=sender or auth_cfg.sender or "",
        )
        return self.send(envelope, auth=auth_cfg, timeout=timeout)

    def send_progress(
        self,
        *,
        session_id: str,
        mode: str,
        progress_token: str,
        progress: float,
        total: float,
        message: str = "",
        target_message_id: str = "",
        sender: str = "",
        auth: AuthConfig | None = None,
        timeout: float | None = None,
    ) -> envelope_pb2.Ack:
        """Send a non-binding progress update within a session."""
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
            sender=sender or auth_cfg.sender or "",
        )
        return self.send(envelope, auth=auth_cfg, timeout=timeout)
