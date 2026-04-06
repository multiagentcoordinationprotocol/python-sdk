from __future__ import annotations

from macp.modes.quorum.v1 import quorum_pb2

from macp_sdk.constants import MODE_QUORUM
from macp_sdk.quorum import QuorumProjection
from tests.conftest import make_envelope


class TestQuorumProjection:
    def _proj(self) -> QuorumProjection:
        return QuorumProjection()

    def test_initial_state(self):
        p = self._proj()
        assert p.phase == "Pending"
        assert p.request is None
        assert p.approval_count() == 0
        assert not p.is_threshold_reached()

    def test_approval_request(self):
        p = self._proj()
        p.apply_envelope(
            make_envelope(
                MODE_QUORUM,
                "ApprovalRequest",
                quorum_pb2.ApprovalRequestPayload(
                    request_id="r1",
                    action="deploy",
                    summary="release v2",
                    required_approvals=2,
                ),
                sender="coordinator",
            )
        )
        assert p.request is not None
        assert p.request.required_approvals == 2
        assert p.phase == "Voting"

    def test_approve_and_threshold(self):
        p = self._proj()
        p.apply_envelope(
            make_envelope(
                MODE_QUORUM,
                "ApprovalRequest",
                quorum_pb2.ApprovalRequestPayload(
                    request_id="r1", action="x", required_approvals=2
                ),
                sender="coordinator",
            )
        )
        p.apply_envelope(
            make_envelope(
                MODE_QUORUM,
                "Approve",
                quorum_pb2.ApprovePayload(request_id="r1", reason="ok"),
                sender="alice",
            )
        )
        assert p.approval_count() == 1
        assert not p.is_threshold_reached()

        p.apply_envelope(
            make_envelope(
                MODE_QUORUM,
                "Approve",
                quorum_pb2.ApprovePayload(request_id="r1", reason="lgtm"),
                sender="bob",
            )
        )
        assert p.approval_count() == 2
        assert p.is_threshold_reached()
        assert p.commitment_ready(total_eligible=3)

    def test_reject_and_abstain(self):
        p = self._proj()
        p.apply_envelope(
            make_envelope(
                MODE_QUORUM,
                "ApprovalRequest",
                quorum_pb2.ApprovalRequestPayload(
                    request_id="r1", action="x", required_approvals=3
                ),
                sender="coordinator",
            )
        )
        p.apply_envelope(
            make_envelope(
                MODE_QUORUM,
                "Reject",
                quorum_pb2.RejectPayload(request_id="r1", reason="nope"),
                sender="alice",
            )
        )
        p.apply_envelope(
            make_envelope(
                MODE_QUORUM,
                "Abstain",
                quorum_pb2.AbstainPayload(request_id="r1", reason="neutral"),
                sender="bob",
            )
        )
        assert p.rejection_count() == 1
        assert p.abstention_count() == 1
        assert p.approval_count() == 0

    def test_threshold_unreachable(self):
        p = self._proj()
        p.apply_envelope(
            make_envelope(
                MODE_QUORUM,
                "ApprovalRequest",
                quorum_pb2.ApprovalRequestPayload(
                    request_id="r1", action="x", required_approvals=3
                ),
                sender="coordinator",
            )
        )
        # 3 participants, all reject
        for sender in ["alice", "bob", "carol"]:
            p.apply_envelope(
                make_envelope(
                    MODE_QUORUM,
                    "Reject",
                    quorum_pb2.RejectPayload(request_id="r1"),
                    sender=sender,
                )
            )
        assert p.is_threshold_unreachable(total_eligible=3)
        assert p.commitment_ready(total_eligible=3)

    def test_one_sender_one_ballot(self):
        """Latest ballot per sender supersedes previous."""
        p = self._proj()
        p.apply_envelope(
            make_envelope(
                MODE_QUORUM,
                "ApprovalRequest",
                quorum_pb2.ApprovalRequestPayload(
                    request_id="r1", action="x", required_approvals=1
                ),
                sender="coordinator",
            )
        )
        p.apply_envelope(
            make_envelope(
                MODE_QUORUM,
                "Reject",
                quorum_pb2.RejectPayload(request_id="r1"),
                sender="alice",
            )
        )
        # Same sender changes vote
        p.apply_envelope(
            make_envelope(
                MODE_QUORUM,
                "Approve",
                quorum_pb2.ApprovePayload(request_id="r1"),
                sender="alice",
            )
        )
        assert p.approval_count() == 1
        assert p.rejection_count() == 0
        assert len(p.ballots) == 1
