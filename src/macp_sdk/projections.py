from __future__ import annotations

from dataclasses import dataclass

from macp.modes.decision.v1 import decision_pb2
from macp.v1 import envelope_pb2

from .base_projection import BaseProjection
from .constants import MODE_DECISION


@dataclass(slots=True)
class DecisionProposalRecord:
    proposal_id: str
    option: str
    rationale: str
    sender: str


@dataclass(slots=True)
class DecisionEvaluationRecord:
    proposal_id: str
    recommendation: str
    confidence: float
    reason: str
    sender: str


@dataclass(slots=True)
class DecisionObjectionRecord:
    proposal_id: str
    reason: str
    severity: str
    sender: str


@dataclass(slots=True)
class DecisionVoteRecord:
    proposal_id: str
    vote: str
    reason: str
    sender: str


class DecisionProjection(BaseProjection):
    """In-process state tracking for Decision mode sessions."""

    MODE = MODE_DECISION

    def __init__(self) -> None:
        super().__init__()
        self.phase = "Proposal"
        self.proposals: dict[str, DecisionProposalRecord] = {}
        self.evaluations: list[DecisionEvaluationRecord] = []
        self.objections: list[DecisionObjectionRecord] = []
        self.votes: dict[str, dict[str, DecisionVoteRecord]] = {}

    def _apply_mode_message(self, envelope: envelope_pb2.Envelope) -> None:
        message_type = envelope.message_type

        if message_type == "Proposal":
            payload = decision_pb2.ProposalPayload()
            payload.ParseFromString(envelope.payload)
            self.proposals[payload.proposal_id] = DecisionProposalRecord(
                proposal_id=payload.proposal_id,
                option=payload.option,
                rationale=payload.rationale,
                sender=envelope.sender,
            )
            self.phase = "Evaluation"
            return

        if message_type == "Evaluation":
            payload = decision_pb2.EvaluationPayload()
            payload.ParseFromString(envelope.payload)
            self.evaluations.append(
                DecisionEvaluationRecord(
                    proposal_id=payload.proposal_id,
                    recommendation=payload.recommendation,
                    confidence=payload.confidence,
                    reason=payload.reason,
                    sender=envelope.sender,
                )
            )
            return

        if message_type == "Objection":
            payload = decision_pb2.ObjectionPayload()
            payload.ParseFromString(envelope.payload)
            self.objections.append(
                DecisionObjectionRecord(
                    proposal_id=payload.proposal_id,
                    reason=payload.reason,
                    severity=payload.severity or "medium",
                    sender=envelope.sender,
                )
            )
            return

        if message_type == "Vote":
            payload = decision_pb2.VotePayload()
            payload.ParseFromString(envelope.payload)
            self.votes.setdefault(payload.proposal_id, {})[envelope.sender] = DecisionVoteRecord(
                proposal_id=payload.proposal_id,
                vote=payload.vote,
                reason=payload.reason,
                sender=envelope.sender,
            )
            self.phase = "Voting"

    # -- State query helpers (no policy enforcement) --

    def vote_totals(self) -> dict[str, int]:
        """Count positive votes per proposal."""
        totals: dict[str, int] = {}
        for proposal_id, sender_votes in self.votes.items():
            totals[proposal_id] = sum(
                1 for vote in sender_votes.values() if _is_positive_vote(vote.vote)
            )
        return totals

    def majority_winner(self) -> str | None:
        """Return the proposal_id with the most positive votes, or None."""
        totals = self.vote_totals()
        if not totals:
            return None
        return max(totals, key=totals.get)  # type: ignore[arg-type]

    def has_blocking_objection(self, proposal_id: str) -> bool:
        """Check if any objection with high/critical/block severity exists."""
        blocking = {"high", "critical", "block"}
        return any(
            objection.proposal_id == proposal_id and objection.severity.lower() in blocking
            for objection in self.objections
        )


def _is_positive_vote(vote: str) -> bool:
    return vote.strip().lower() in {"approve", "approved", "yes", "accept", "accepted"}
