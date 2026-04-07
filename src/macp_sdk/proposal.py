from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from macp.modes.proposal.v1 import proposal_pb2
from macp.v1 import envelope_pb2

from .auth import AuthConfig
from .base_projection import BaseProjection
from .base_session import BaseSession
from .constants import MODE_PROPOSAL
from .envelope import build_envelope, serialize_message
from .errors import MacpSessionError

# ---------------------------------------------------------------------------
# Projection records
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ProposalRecord:
    proposal_id: str
    title: str
    summary: str
    proposer: str
    supersedes: str  # "" if original
    disposition: str  # "live" | "withdrawn"


@dataclass(slots=True)
class RejectRecord:
    proposal_id: str
    reason: str
    sender: str
    terminal: bool


@dataclass(slots=True)
class TerminalRejectRecord:
    proposal_id: str
    reason: str
    sender: str


@dataclass(slots=True)
class AcceptRecord:
    proposal_id: str
    reason: str
    sender: str


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------


class ProposalProjection(BaseProjection):
    """In-process state tracking for Proposal mode sessions."""

    MODE = MODE_PROPOSAL

    def __init__(self) -> None:
        super().__init__()
        self.phase = "Negotiating"
        self.proposals: dict[str, ProposalRecord] = {}
        self.accepts: dict[str, AcceptRecord] = {}  # sender -> latest accept
        self.rejections: list[RejectRecord] = []
        self.terminal_rejections: list[TerminalRejectRecord] = []

    def _apply_mode_message(self, envelope: envelope_pb2.Envelope) -> None:
        mt = envelope.message_type

        if mt == "Proposal":
            p = proposal_pb2.ProposalPayload()
            p.ParseFromString(envelope.payload)
            self.proposals[p.proposal_id] = ProposalRecord(
                proposal_id=p.proposal_id,
                title=p.title,
                summary=p.summary,
                proposer=envelope.sender,
                supersedes="",
                disposition="live",
            )
            return

        if mt == "CounterProposal":
            p = proposal_pb2.CounterProposalPayload()
            p.ParseFromString(envelope.payload)
            # Counter-proposal does NOT retire the original — both stay live.
            self.proposals[p.proposal_id] = ProposalRecord(
                proposal_id=p.proposal_id,
                title=p.title,
                summary=p.summary,
                proposer=envelope.sender,
                supersedes=p.supersedes_proposal_id,
                disposition="live",
            )
            return

        if mt == "Accept":
            p = proposal_pb2.AcceptPayload()
            p.ParseFromString(envelope.payload)
            self.accepts[envelope.sender] = AcceptRecord(
                proposal_id=p.proposal_id,
                reason=p.reason,
                sender=envelope.sender,
            )
            return

        if mt == "Reject":
            p = proposal_pb2.RejectPayload()
            p.ParseFromString(envelope.payload)
            self.rejections.append(
                RejectRecord(
                    proposal_id=p.proposal_id,
                    reason=p.reason,
                    sender=envelope.sender,
                    terminal=p.terminal,
                )
            )
            if p.terminal:
                self.terminal_rejections.append(
                    TerminalRejectRecord(
                        proposal_id=p.proposal_id,
                        reason=p.reason,
                        sender=envelope.sender,
                    )
                )
                self.phase = "TerminalRejected"
            return

        if mt == "Withdraw":
            p = proposal_pb2.WithdrawPayload()
            p.ParseFromString(envelope.payload)
            if p.proposal_id in self.proposals:
                self.proposals[p.proposal_id].disposition = "withdrawn"

    # -- State query helpers --

    def live_proposals(self) -> dict[str, ProposalRecord]:
        """Return proposals that have not been withdrawn."""
        return {k: v for k, v in self.proposals.items() if v.disposition == "live"}

    def accepted_proposal(self) -> str | None:
        """Return the proposal_id that all accepting senders agree on, or None."""
        if not self.accepts:
            return None
        ids = {a.proposal_id for a in self.accepts.values()}
        if len(ids) == 1:
            return ids.pop()
        return None

    def has_terminal_rejection(self) -> bool:
        return len(self.terminal_rejections) > 0


# ---------------------------------------------------------------------------
# Session helper
# ---------------------------------------------------------------------------


class ProposalSession(BaseSession):
    """High-level helper for Proposal mode sessions."""

    MODE = MODE_PROPOSAL

    def _create_projection(self) -> BaseProjection:
        return ProposalProjection()

    @property
    def proposal_projection(self) -> ProposalProjection:
        assert isinstance(self.projection, ProposalProjection)
        return self.projection

    def propose(
        self,
        proposal_id: str,
        title: str,
        *,
        summary: str = "",
        details: bytes = b"",
        tags: list[str] | None = None,
        sender: str | None = None,
        auth: AuthConfig | None = None,
    ) -> Any:
        payload = proposal_pb2.ProposalPayload(
            proposal_id=proposal_id,
            title=title,
            summary=summary,
            details=details,
            tags=tags or [],
        )
        envelope = build_envelope(
            mode=self.MODE,
            message_type="Proposal",
            session_id=self.session_id,
            sender=self._sender_for(sender),
            payload=serialize_message(payload),
        )
        return self._send_and_track(envelope, auth=auth)

    def counter_propose(
        self,
        proposal_id: str,
        supersedes_proposal_id: str,
        title: str,
        *,
        summary: str = "",
        details: bytes = b"",
        sender: str | None = None,
        auth: AuthConfig | None = None,
    ) -> Any:
        payload = proposal_pb2.CounterProposalPayload(
            proposal_id=proposal_id,
            supersedes_proposal_id=supersedes_proposal_id,
            title=title,
            summary=summary,
            details=details,
        )
        envelope = build_envelope(
            mode=self.MODE,
            message_type="CounterProposal",
            session_id=self.session_id,
            sender=self._sender_for(sender),
            payload=serialize_message(payload),
        )
        return self._send_and_track(envelope, auth=auth)

    def accept(
        self,
        proposal_id: str,
        *,
        reason: str = "",
        sender: str | None = None,
        auth: AuthConfig | None = None,
    ) -> Any:
        payload = proposal_pb2.AcceptPayload(
            proposal_id=proposal_id,
            reason=reason,
        )
        envelope = build_envelope(
            mode=self.MODE,
            message_type="Accept",
            session_id=self.session_id,
            sender=self._sender_for(sender),
            payload=serialize_message(payload),
        )
        return self._send_and_track(envelope, auth=auth)

    def reject(
        self,
        proposal_id: str,
        *,
        terminal: bool = False,
        reason: str = "",
        sender: str | None = None,
        auth: AuthConfig | None = None,
    ) -> Any:
        payload = proposal_pb2.RejectPayload(
            proposal_id=proposal_id,
            terminal=terminal,
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

    def withdraw(
        self,
        proposal_id: str,
        *,
        reason: str = "",
        sender: str | None = None,
        auth: AuthConfig | None = None,
    ) -> Any:
        if not proposal_id or not proposal_id.strip():
            raise MacpSessionError("proposal_id must be non-empty for withdraw")
        payload = proposal_pb2.WithdrawPayload(
            proposal_id=proposal_id,
            reason=reason,
        )
        envelope = build_envelope(
            mode=self.MODE,
            message_type="Withdraw",
            session_id=self.session_id,
            sender=self._sender_for(sender),
            payload=serialize_message(payload),
        )
        return self._send_and_track(envelope, auth=auth)
