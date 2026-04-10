from __future__ import annotations

from macp.modes.proposal.v1 import proposal_pb2

from macp_sdk.constants import MODE_PROPOSAL
from macp_sdk.proposal import ProposalProjection
from tests.conftest import make_envelope


class TestProposalProjection:
    def _proj(self) -> ProposalProjection:
        return ProposalProjection()

    def test_initial_state(self):
        p = self._proj()
        assert p.phase == "Negotiating"
        assert not p.is_committed
        assert p.accepted_proposal() is None

    def test_proposal(self):
        p = self._proj()
        env = make_envelope(
            MODE_PROPOSAL,
            "Proposal",
            proposal_pb2.ProposalPayload(proposal_id="p1", title="Plan A", summary="first"),
            sender="alice",
        )
        p.apply_envelope(env)
        assert "p1" in p.proposals
        assert p.proposals["p1"].status == "open"

    def test_counter_proposal_does_not_retire_original(self):
        """Counter-proposal does NOT retire the original — both stay live."""
        p = self._proj()
        p.apply_envelope(
            make_envelope(
                MODE_PROPOSAL,
                "Proposal",
                proposal_pb2.ProposalPayload(proposal_id="p1", title="A"),
                sender="alice",
            )
        )
        p.apply_envelope(
            make_envelope(
                MODE_PROPOSAL,
                "CounterProposal",
                proposal_pb2.CounterProposalPayload(
                    proposal_id="p2", supersedes_proposal_id="p1", title="B"
                ),
                sender="bob",
            )
        )
        assert p.proposals["p1"].status == "open"
        assert p.proposals["p2"].status == "open"
        assert len(p.live_proposals()) == 2

    def test_accept_convergence(self):
        p = self._proj()
        for sender in ["alice", "bob"]:
            p.apply_envelope(
                make_envelope(
                    MODE_PROPOSAL,
                    "Accept",
                    proposal_pb2.AcceptPayload(proposal_id="p1", reason="agreed"),
                    sender=sender,
                )
            )
        assert p.accepted_proposal() == "p1"

    def test_accept_divergence(self):
        p = self._proj()
        p.apply_envelope(
            make_envelope(
                MODE_PROPOSAL,
                "Accept",
                proposal_pb2.AcceptPayload(proposal_id="p1"),
                sender="alice",
            )
        )
        p.apply_envelope(
            make_envelope(
                MODE_PROPOSAL,
                "Accept",
                proposal_pb2.AcceptPayload(proposal_id="p2"),
                sender="bob",
            )
        )
        assert p.accepted_proposal() is None

    def test_terminal_rejection(self):
        p = self._proj()
        p.apply_envelope(
            make_envelope(
                MODE_PROPOSAL,
                "Reject",
                proposal_pb2.RejectPayload(proposal_id="p1", terminal=True, reason="no deal"),
                sender="bob",
            )
        )
        assert p.has_terminal_rejection()
        assert p.phase == "TerminalRejected"

    def test_rejection_audit_trail(self):
        """Both terminal and non-terminal rejections are tracked."""
        p = self._proj()
        p.apply_envelope(
            make_envelope(
                MODE_PROPOSAL,
                "Reject",
                proposal_pb2.RejectPayload(proposal_id="p1", terminal=False, reason="maybe not"),
                sender="alice",
            )
        )
        p.apply_envelope(
            make_envelope(
                MODE_PROPOSAL,
                "Reject",
                proposal_pb2.RejectPayload(proposal_id="p1", terminal=True, reason="no deal"),
                sender="bob",
            )
        )
        assert len(p.rejections) == 2
        assert p.rejections[0].terminal is False
        assert p.rejections[1].terminal is True
        assert sum(1 for r in p.rejections if r.terminal) == 1

    def test_withdraw(self):
        p = self._proj()
        p.apply_envelope(
            make_envelope(
                MODE_PROPOSAL,
                "Proposal",
                proposal_pb2.ProposalPayload(proposal_id="p1", title="A"),
                sender="alice",
            )
        )
        p.apply_envelope(
            make_envelope(
                MODE_PROPOSAL,
                "Withdraw",
                proposal_pb2.WithdrawPayload(proposal_id="p1", reason="changed mind"),
                sender="alice",
            )
        )
        assert p.proposals["p1"].status == "withdrawn"
        assert len(p.live_proposals()) == 0
