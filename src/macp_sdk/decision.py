from __future__ import annotations

from macp.modes.decision.v1 import decision_pb2

from .auth import AuthConfig
from .base_projection import BaseProjection
from .base_session import BaseSession
from .constants import MODE_DECISION
from .envelope import build_envelope, serialize_message
from .projections import DecisionProjection


class DecisionSession(BaseSession):
    """High-level helper for Decision mode sessions.

    Inherits ``start``, ``commit``, ``cancel``, ``metadata``, and ``open_stream``
    from :class:`BaseSession`.  Adds decision-specific actions: ``propose``,
    ``evaluate``, ``raise_objection``, and ``vote``.
    """

    MODE = MODE_DECISION

    def _create_projection(self) -> BaseProjection:
        return DecisionProjection()

    # Narrow the type for callers that want decision-specific queries.
    @property
    def decision_projection(self) -> DecisionProjection:
        assert isinstance(self.projection, DecisionProjection)
        return self.projection

    def propose(
        self,
        proposal_id: str,
        option: str,
        *,
        rationale: str = "",
        supporting_data: bytes = b"",
        sender: str | None = None,
        auth: AuthConfig | None = None,
    ):  # noqa: ANN201
        payload = decision_pb2.ProposalPayload(
            proposal_id=proposal_id,
            option=option,
            rationale=rationale,
            supporting_data=supporting_data,
        )
        envelope = build_envelope(
            mode=self.MODE,
            message_type="Proposal",
            session_id=self.session_id,
            sender=self._sender_for(sender),
            payload=serialize_message(payload),
        )
        return self._send_and_track(envelope, auth=auth)

    def evaluate(
        self,
        proposal_id: str,
        recommendation: str,
        *,
        confidence: float,
        reason: str = "",
        sender: str | None = None,
        auth: AuthConfig | None = None,
    ):  # noqa: ANN201
        payload = decision_pb2.EvaluationPayload(
            proposal_id=proposal_id,
            recommendation=recommendation,
            confidence=confidence,
            reason=reason,
        )
        envelope = build_envelope(
            mode=self.MODE,
            message_type="Evaluation",
            session_id=self.session_id,
            sender=self._sender_for(sender),
            payload=serialize_message(payload),
        )
        return self._send_and_track(envelope, auth=auth)

    def raise_objection(
        self,
        proposal_id: str,
        *,
        reason: str,
        severity: str = "medium",
        sender: str | None = None,
        auth: AuthConfig | None = None,
    ):  # noqa: ANN201
        payload = decision_pb2.ObjectionPayload(
            proposal_id=proposal_id,
            reason=reason,
            severity=severity,
        )
        envelope = build_envelope(
            mode=self.MODE,
            message_type="Objection",
            session_id=self.session_id,
            sender=self._sender_for(sender),
            payload=serialize_message(payload),
        )
        return self._send_and_track(envelope, auth=auth)

    def vote(
        self,
        proposal_id: str,
        vote: str,
        *,
        reason: str = "",
        sender: str | None = None,
        auth: AuthConfig | None = None,
    ):  # noqa: ANN201
        payload = decision_pb2.VotePayload(
            proposal_id=proposal_id,
            vote=vote,
            reason=reason,
        )
        envelope = build_envelope(
            mode=self.MODE,
            message_type="Vote",
            session_id=self.session_id,
            sender=self._sender_for(sender),
            payload=serialize_message(payload),
        )
        return self._send_and_track(envelope, auth=auth)
