from __future__ import annotations

from macp.modes.decision.v1 import decision_pb2
from macp.v1 import core_pb2

from macp_sdk.constants import MODE_DECISION
from macp_sdk.projections import DecisionProjection
from tests.conftest import make_envelope


class TestDecisionProjection:
    def _proj(self) -> DecisionProjection:
        return DecisionProjection()

    def test_initial_state(self):
        p = self._proj()
        assert p.phase == "Proposal"
        assert not p.is_committed
        assert p.vote_totals() == {}
        assert p.majority_winner() is None

    def test_proposal_advances_phase(self):
        p = self._proj()
        env = make_envelope(
            MODE_DECISION,
            "Proposal",
            decision_pb2.ProposalPayload(proposal_id="p1", option="opt-a", rationale="good"),
        )
        p.apply_envelope(env)
        assert "p1" in p.proposals
        assert p.phase == "Evaluation"
        assert len(p.transcript) == 1

    def test_evaluation_recorded(self):
        p = self._proj()
        env = make_envelope(
            MODE_DECISION,
            "Evaluation",
            decision_pb2.EvaluationPayload(
                proposal_id="p1", recommendation="APPROVE", confidence=0.9, reason="ok"
            ),
            sender="alice",
        )
        p.apply_envelope(env)
        assert len(p.evaluations) == 1
        assert p.evaluations[0].recommendation == "APPROVE"

    def test_objection_recorded(self):
        p = self._proj()
        env = make_envelope(
            MODE_DECISION,
            "Objection",
            decision_pb2.ObjectionPayload(proposal_id="p1", reason="risk", severity="critical"),
        )
        p.apply_envelope(env)
        assert len(p.objections) == 1
        assert p.has_blocking_objection("p1")

    def test_non_blocking_objection(self):
        p = self._proj()
        env = make_envelope(
            MODE_DECISION,
            "Objection",
            decision_pb2.ObjectionPayload(proposal_id="p1", reason="minor", severity="low"),
        )
        p.apply_envelope(env)
        assert not p.has_blocking_objection("p1")

    def test_vote_and_totals(self):
        p = self._proj()
        for sender, vote_val in [("alice", "approve"), ("bob", "approve"), ("carol", "reject")]:
            env = make_envelope(
                MODE_DECISION,
                "Vote",
                decision_pb2.VotePayload(proposal_id="p1", vote=vote_val, reason=""),
                sender=sender,
            )
            p.apply_envelope(env)
        assert p.phase == "Voting"
        assert p.vote_totals() == {"p1": 2}
        assert p.majority_winner() == "p1"

    def test_commitment(self):
        p = self._proj()
        env = make_envelope(
            MODE_DECISION,
            "Commitment",
            core_pb2.CommitmentPayload(
                commitment_id="c1",
                action="deploy",
                authority_scope="release",
                reason="approved",
            ),
        )
        p.apply_envelope(env)
        assert p.is_committed
        assert p.phase == "Committed"
        assert p.commitment is not None
        assert p.commitment.action == "deploy"

    def test_ignores_wrong_mode(self):
        p = self._proj()
        env = make_envelope(
            "macp.mode.task.v1",
            "TaskRequest",
            decision_pb2.ProposalPayload(proposal_id="p1", option="x"),
        )
        p.apply_envelope(env)
        assert len(p.transcript) == 0
