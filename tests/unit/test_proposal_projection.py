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
        assert p.proposals["p1"].disposition == "live"

    def test_counter_proposal_supersedes(self):
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
        assert p.proposals["p1"].disposition == "withdrawn"
        assert p.proposals["p2"].disposition == "live"
        assert len(p.live_proposals()) == 1

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
        assert p.proposals["p1"].disposition == "withdrawn"
        assert len(p.live_proposals()) == 0
