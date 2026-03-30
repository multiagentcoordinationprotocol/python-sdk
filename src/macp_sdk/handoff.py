from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from macp.modes.handoff.v1 import handoff_pb2
from macp.v1 import envelope_pb2

from .auth import AuthConfig
from .base_projection import BaseProjection
from .base_session import BaseSession
from .constants import MODE_HANDOFF
from .envelope import build_envelope, serialize_message

# ---------------------------------------------------------------------------
# Projection records
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class HandoffOfferRecord:
    handoff_id: str
    target_participant: str
    scope: str
    reason: str
    offered_by: str
    disposition: str  # "offered" | "accepted" | "declined"


@dataclass(slots=True)
class HandoffContextRecord:
    handoff_id: str
    content_type: str
    context: bytes
    sender: str


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------


class HandoffProjection(BaseProjection):
    """In-process state tracking for Handoff mode sessions."""

    MODE = MODE_HANDOFF

    def __init__(self) -> None:
        super().__init__()
        self.phase = "Pending"
        self.offers: dict[str, HandoffOfferRecord] = {}
        self.contexts: dict[str, list[HandoffContextRecord]] = {}

    def _apply_mode_message(self, envelope: envelope_pb2.Envelope) -> None:
        mt = envelope.message_type

        if mt == "HandoffOffer":
            p = handoff_pb2.HandoffOfferPayload()
            p.ParseFromString(envelope.payload)
            self.offers[p.handoff_id] = HandoffOfferRecord(
                handoff_id=p.handoff_id,
                target_participant=p.target_participant,
                scope=p.scope,
                reason=p.reason,
                offered_by=envelope.sender,
                disposition="offered",
            )
            self.phase = "OfferPending"
            return

        if mt == "HandoffContext":
            p = handoff_pb2.HandoffContextPayload()
            p.ParseFromString(envelope.payload)
            self.contexts.setdefault(p.handoff_id, []).append(
                HandoffContextRecord(
                    handoff_id=p.handoff_id,
                    content_type=p.content_type,
                    context=p.context,
                    sender=envelope.sender,
                )
            )
            return

        if mt == "HandoffAccept":
            p = handoff_pb2.HandoffAcceptPayload()
            p.ParseFromString(envelope.payload)
            if p.handoff_id in self.offers:
                self.offers[p.handoff_id].disposition = "accepted"
            self.phase = "Accepted"
            return

        if mt == "HandoffDecline":
            p = handoff_pb2.HandoffDeclinePayload()
            p.ParseFromString(envelope.payload)
            if p.handoff_id in self.offers:
                self.offers[p.handoff_id].disposition = "declined"
            self.phase = "Declined"

    # -- State query helpers --

    def active_offer(self) -> HandoffOfferRecord | None:
        """Return the most recent offer with disposition='offered', or None."""
        for offer in reversed(list(self.offers.values())):
            if offer.disposition == "offered":
                return offer
        return None

    def is_accepted(self, handoff_id: str) -> bool:
        offer = self.offers.get(handoff_id)
        return offer is not None and offer.disposition == "accepted"

    def is_declined(self, handoff_id: str) -> bool:
        offer = self.offers.get(handoff_id)
        return offer is not None and offer.disposition == "declined"


# ---------------------------------------------------------------------------
# Session helper
# ---------------------------------------------------------------------------


class HandoffSession(BaseSession):
    """High-level helper for Handoff mode sessions."""

    MODE = MODE_HANDOFF

    def _create_projection(self) -> BaseProjection:
        return HandoffProjection()

    @property
    def handoff_projection(self) -> HandoffProjection:
        assert isinstance(self.projection, HandoffProjection)
        return self.projection

    def offer(
        self,
        handoff_id: str,
        target_participant: str,
        *,
        scope: str = "",
        reason: str = "",
        sender: str | None = None,
        auth: AuthConfig | None = None,
    ) -> Any:
        payload = handoff_pb2.HandoffOfferPayload(
            handoff_id=handoff_id,
            target_participant=target_participant,
            scope=scope,
            reason=reason,
        )
        envelope = build_envelope(
            mode=self.MODE,
            message_type="HandoffOffer",
            session_id=self.session_id,
            sender=self._sender_for(sender),
            payload=serialize_message(payload),
        )
        return self._send_and_track(envelope, auth=auth)

    def add_context(
        self,
        handoff_id: str,
        *,
        content_type: str = "application/octet-stream",
        context: bytes = b"",
        sender: str | None = None,
        auth: AuthConfig | None = None,
    ) -> Any:
        payload = handoff_pb2.HandoffContextPayload(
            handoff_id=handoff_id,
            content_type=content_type,
            context=context,
        )
        envelope = build_envelope(
            mode=self.MODE,
            message_type="HandoffContext",
            session_id=self.session_id,
            sender=self._sender_for(sender),
            payload=serialize_message(payload),
        )
        return self._send_and_track(envelope, auth=auth)

    def accept_handoff(
        self,
        handoff_id: str,
        *,
        accepted_by: str = "",
        reason: str = "",
        sender: str | None = None,
        auth: AuthConfig | None = None,
    ) -> Any:
        payload = handoff_pb2.HandoffAcceptPayload(
            handoff_id=handoff_id,
            accepted_by=accepted_by or self._sender_for(sender),
            reason=reason,
        )
        envelope = build_envelope(
            mode=self.MODE,
            message_type="HandoffAccept",
            session_id=self.session_id,
            sender=self._sender_for(sender),
            payload=serialize_message(payload),
        )
        return self._send_and_track(envelope, auth=auth)

    def decline(
        self,
        handoff_id: str,
        *,
        declined_by: str = "",
        reason: str = "",
        sender: str | None = None,
        auth: AuthConfig | None = None,
    ) -> Any:
        payload = handoff_pb2.HandoffDeclinePayload(
            handoff_id=handoff_id,
            declined_by=declined_by or self._sender_for(sender),
            reason=reason,
        )
        envelope = build_envelope(
            mode=self.MODE,
            message_type="HandoffDecline",
            session_id=self.session_id,
            sender=self._sender_for(sender),
            payload=serialize_message(payload),
        )
        return self._send_and_track(envelope, auth=auth)
