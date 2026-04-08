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
            self.phase = "Evaluation"
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
        """Count votes per proposal, keyed by proposal_id.

        ABSTAIN votes are tracked but excluded from the totals returned
        here (which counts only APPROVE votes).
        """
        totals: dict[str, int] = {}
        for proposal_id, sender_votes in self.votes.items():
            totals[proposal_id] = sum(
                1 for vote in sender_votes.values() if _is_positive_vote(vote.vote)
            )
        return totals

    def majority_winner(self) -> str | None:
        """Return the proposal_id with a majority of non-abstain votes, or None.

        ABSTAIN votes are excluded from the denominator per RFC-MACP-0004.
        """
        totals = self.vote_totals()
        if not totals:
            return None
        # Count total non-abstain votes across all proposals
        non_abstain = 0
        for sender_votes in self.votes.values():
            for vote in sender_votes.values():
                if vote.vote.upper() != "ABSTAIN":
                    non_abstain += 1
        if non_abstain == 0:
            return None
        for proposal_id, count in totals.items():
            if count / non_abstain > 0.5:
                return proposal_id
        return None

    def has_blocking_objection(self, proposal_id: str | None = None) -> bool:
        """Check if any objection with ``critical`` severity exists.

        Only ``critical`` severity triggers a veto per the updated runtime.
        """
        return any(
            objection.severity.lower() == "critical"
            and (proposal_id is None or objection.proposal_id == proposal_id)
            for objection in self.objections
        )

    def review_evaluations(self) -> list[DecisionEvaluationRecord]:
        """Return evaluations with REVIEW recommendation (informational only)."""
        return [e for e in self.evaluations if e.recommendation.upper() == "REVIEW"]

    def qualifying_evaluations(self) -> list[DecisionEvaluationRecord]:
        """Return evaluations that are *not* REVIEW (i.e., they affect decisions)."""
        return [e for e in self.evaluations if e.recommendation.upper() != "REVIEW"]


def _is_positive_vote(vote: str) -> bool:
    return vote.strip().upper() in {"APPROVE", "APPROVED", "YES", "ACCEPT", "ACCEPTED"}
