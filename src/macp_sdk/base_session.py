from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from typing import Any, ClassVar

from ._logging import logger
from .auth import AuthConfig
from .base_projection import BaseProjection
from .client import MacpClient, MacpStream
from .constants import (
    DEFAULT_CONFIGURATION_VERSION,
    DEFAULT_MODE_VERSION,
    DEFAULT_POLICY_VERSION,
)
from .envelope import (
    build_commitment_payload,
    build_envelope,
    build_session_start_payload,
    new_session_id,
    serialize_message,
)
from .validation import validate_participant_count, validate_session_id


class BaseSession(ABC):
    """Abstract base for mode session helpers.

    Provides shared logic for session lifecycle (start, commit, cancel,
    metadata, streaming) so that mode-specific subclasses only need to
    implement their own action methods.
    """

    MODE: ClassVar[str]

    def __init__(
        self,
        client: MacpClient,
        *,
        session_id: str | None = None,
        mode_version: str = DEFAULT_MODE_VERSION,
        configuration_version: str = DEFAULT_CONFIGURATION_VERSION,
        policy_version: str = DEFAULT_POLICY_VERSION,
        auth: AuthConfig | None = None,
    ) -> None:
        self.client = client
        self.session_id = session_id or new_session_id()
        if session_id:
            validate_session_id(session_id)
        self.mode_version = mode_version
        self.configuration_version = configuration_version
        self.policy_version = policy_version
        self.auth = auth
        self.projection = self._create_projection()

    @abstractmethod
    def _create_projection(self) -> BaseProjection:
        """Return a new projection instance for this mode."""

    def _sender_for(self, sender: str | None) -> str:
        if sender:
            return sender
        auth_cfg = self.auth or self.client.auth
        return auth_cfg.sender or "" if auth_cfg else ""

    def _send_and_track(
        self,
        envelope: Any,
        *,
        auth: AuthConfig | None = None,
    ) -> Any:
        logger.debug(
            "send session=%s type=%s sender=%s",
            envelope.session_id,
            envelope.message_type,
            envelope.sender,
        )
        ack = self.client.send(envelope, auth=auth or self.auth)
        if ack.ok:
            self.projection.apply_envelope(envelope)
        else:
            logger.warning(
                "nack session=%s type=%s code=%s",
                envelope.session_id,
                envelope.message_type,
                getattr(ack, "error", None),
            )
        return ack

    def start(
        self,
        *,
        intent: str,
        participants: list[str],
        ttl_ms: int,
        context: bytes | str | Mapping[str, object] | None = None,
        roots: Iterable[Any] | None = None,
        sender: str | None = None,
    ) -> Any:
        """Send SessionStart and begin tracking via the projection."""
        validate_participant_count(len(participants))
        payload = build_session_start_payload(
            intent=intent,
            participants=participants,
            ttl_ms=ttl_ms,
            mode_version=self.mode_version,
            configuration_version=self.configuration_version,
            policy_version=self.policy_version,
            context=context,
            roots=roots,
        )
        envelope = build_envelope(
            mode=self.MODE,
            message_type="SessionStart",
            session_id=self.session_id,
            sender=self._sender_for(sender),
            payload=serialize_message(payload),
        )
        return self._send_and_track(envelope, auth=self.auth)

    def commit(
        self,
        *,
        action: str,
        authority_scope: str,
        reason: str,
        commitment_id: str | None = None,
        outcome_positive: bool | None = None,
        sender: str | None = None,
        auth: AuthConfig | None = None,
    ) -> Any:
        """Send Commitment to resolve the session."""
        payload = build_commitment_payload(
            action=action,
            authority_scope=authority_scope,
            reason=reason,
            commitment_id=commitment_id,
            mode_version=self.mode_version,
            configuration_version=self.configuration_version,
            policy_version=self.policy_version,
            outcome_positive=outcome_positive,
        )
        envelope = build_envelope(
            mode=self.MODE,
            message_type="Commitment",
            session_id=self.session_id,
            sender=self._sender_for(sender),
            payload=serialize_message(payload),
        )
        return self._send_and_track(envelope, auth=auth)

    def metadata(self, *, auth: AuthConfig | None = None) -> Any:
        """Query session metadata from the runtime."""
        return self.client.get_session(self.session_id, auth=auth or self.auth)

    def cancel(self, *, reason: str = "", auth: AuthConfig | None = None) -> Any:
        """Cancel the session."""
        return self.client.cancel_session(self.session_id, reason=reason, auth=auth or self.auth)

    def open_stream(self, *, auth: AuthConfig | None = None) -> MacpStream:
        """Open a bidirectional stream for this session."""
        return self.client.open_stream(auth=auth or self.auth)
