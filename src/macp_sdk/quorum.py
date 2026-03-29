from __future__ import annotations

from dataclasses import dataclass

from macp.modes.quorum.v1 import quorum_pb2
from macp.v1 import envelope_pb2

from .auth import AuthConfig
from .base_projection import BaseProjection
from .base_session import BaseSession
from .constants import MODE_QUORUM
from .envelope import build_envelope, serialize_message

# ---------------------------------------------------------------------------
# Projection records
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ApprovalRequestRecord:
    request_id: str
    action: str
    summary: str
    required_approvals: int
    requester: str


@dataclass(slots=True)
class BallotRecord:
    request_id: str
    choice: str  # "approve" | "reject" | "abstain"
    reason: str
    sender: str


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------


class QuorumProjection(BaseProjection):
    """In-process state tracking for Quorum mode sessions."""

    MODE = MODE_QUORUM

    def __init__(self) -> None:
        super().__init__()
        self.phase = "Pending"
        self.request: ApprovalRequestRecord | None = None
        self.ballots: dict[str, BallotRecord] = {}  # sender -> ballot

    def _apply_mode_message(self, envelope: envelope_pb2.Envelope) -> None:
        mt = envelope.message_type

        if mt == "ApprovalRequest":
            p = quorum_pb2.ApprovalRequestPayload()
            p.ParseFromString(envelope.payload)
            self.request = ApprovalRequestRecord(
                request_id=p.request_id,
                action=p.action,
                summary=p.summary,
                required_approvals=p.required_approvals,
                requester=envelope.sender,
            )
            self.phase = "Voting"
            return

        if mt == "Approve":
            p = quorum_pb2.ApprovePayload()
            p.ParseFromString(envelope.payload)
            self.ballots[envelope.sender] = BallotRecord(
                request_id=p.request_id,
                choice="approve",
                reason=p.reason,
                sender=envelope.sender,
            )
            return

        if mt == "Reject":
            p = quorum_pb2.RejectPayload()
            p.ParseFromString(envelope.payload)
            self.ballots[envelope.sender] = BallotRecord(
                request_id=p.request_id,
                choice="reject",
                reason=p.reason,
                sender=envelope.sender,
            )
            return

        if mt == "Abstain":
            p = quorum_pb2.AbstainPayload()
            p.ParseFromString(envelope.payload)
            self.ballots[envelope.sender] = BallotRecord(
                request_id=p.request_id,
                choice="abstain",
                reason=p.reason,
                sender=envelope.sender,
            )

    # -- State query helpers --

    def approval_count(self) -> int:
        return sum(1 for b in self.ballots.values() if b.choice == "approve")

    def rejection_count(self) -> int:
        return sum(1 for b in self.ballots.values() if b.choice == "reject")

    def abstention_count(self) -> int:
        return sum(1 for b in self.ballots.values() if b.choice == "abstain")

    def is_threshold_reached(self) -> bool:
        if self.request is None:
            return False
        return self.approval_count() >= self.request.required_approvals

    def is_threshold_unreachable(self, total_eligible: int) -> bool:
        """True if remaining possible approvals cannot reach the threshold."""
        if self.request is None:
            return False
        remaining = total_eligible - len(self.ballots)
        return self.approval_count() + remaining < self.request.required_approvals

    def commitment_ready(self, total_eligible: int) -> bool:
        """True if the threshold is reached or mathematically unreachable."""
        return self.is_threshold_reached() or self.is_threshold_unreachable(total_eligible)


# ---------------------------------------------------------------------------
# Session helper
# ---------------------------------------------------------------------------


class QuorumSession(BaseSession):
    """High-level helper for Quorum mode sessions."""

    MODE = MODE_QUORUM

    def _create_projection(self) -> BaseProjection:
        return QuorumProjection()

    @property
    def quorum_projection(self) -> QuorumProjection:
        assert isinstance(self.projection, QuorumProjection)
        return self.projection

    def request_approval(
        self,
        request_id: str,
        action: str,
        *,
        summary: str = "",
        details: bytes = b"",
        required_approvals: int,
        sender: str | None = None,
        auth: AuthConfig | None = None,
    ):  # noqa: ANN201
        payload = quorum_pb2.ApprovalRequestPayload(
            request_id=request_id,
            action=action,
            summary=summary,
            details=details,
            required_approvals=required_approvals,
        )
        envelope = build_envelope(
            mode=self.MODE,
            message_type="ApprovalRequest",
            session_id=self.session_id,
            sender=self._sender_for(sender),
            payload=serialize_message(payload),
        )
        return self._send_and_track(envelope, auth=auth)

    def approve(
        self,
        request_id: str,
        *,
        reason: str = "",
        sender: str | None = None,
        auth: AuthConfig | None = None,
    ):  # noqa: ANN201
        payload = quorum_pb2.ApprovePayload(
            request_id=request_id,
            reason=reason,
        )
        envelope = build_envelope(
            mode=self.MODE,
            message_type="Approve",
            session_id=self.session_id,
            sender=self._sender_for(sender),
            payload=serialize_message(payload),
        )
        return self._send_and_track(envelope, auth=auth)

    def reject(
        self,
        request_id: str,
        *,
        reason: str = "",
        sender: str | None = None,
        auth: AuthConfig | None = None,
    ):  # noqa: ANN201
        payload = quorum_pb2.RejectPayload(
            request_id=request_id,
            reason=reason,
        )
        envelope = build_envelope(
            mode=self.MODE,
            message_type="Reject",
            session_id=self.session_id,
            sender=self._sender_for(sender),
            payload=serialize_message(payload),
        )
        return self._send_and_track(envelope, auth=auth)

    def abstain(
        self,
        request_id: str,
        *,
        reason: str = "",
        sender: str | None = None,
        auth: AuthConfig | None = None,
    ):  # noqa: ANN201
        payload = quorum_pb2.AbstainPayload(
            request_id=request_id,
            reason=reason,
        )
        envelope = build_envelope(
            mode=self.MODE,
            message_type="Abstain",
            session_id=self.session_id,
            sender=self._sender_for(sender),
            payload=serialize_message(payload),
        )
        return self._send_and_track(envelope, auth=auth)
