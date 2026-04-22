from __future__ import annotations

from macp.modes.quorum.v1 import quorum_pb2

from macp_sdk.constants import MODE_QUORUM
from macp_sdk.envelope import build_commitment_payload
from macp_sdk.quorum import QuorumProjection
from tests.conftest import make_envelope


class TestQuorumProjection:
    def _proj(self) -> QuorumProjection:
        return QuorumProjection()

    def test_initial_state(self):
        p = self._proj()
        assert p.phase == "Pending"
        assert len(p.requests) == 0
        assert p.approval_count("r1") == 0
        assert not p.has_quorum("r1")

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
        assert "r1" in p.requests
        assert p.requests["r1"].required_approvals == 2
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
        assert p.approval_count("r1") == 1
        assert not p.has_quorum("r1")

        p.apply_envelope(
            make_envelope(
                MODE_QUORUM,
                "Approve",
                quorum_pb2.ApprovePayload(request_id="r1", reason="lgtm"),
                sender="bob",
            )
        )
        assert p.approval_count("r1") == 2
        assert p.has_quorum("r1")
        assert p.commitment_ready("r1")

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
        assert p.rejection_count("r1") == 1
        assert p.abstention_count("r1") == 1
        assert p.approval_count("r1") == 0

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
        assert p.is_threshold_unreachable("r1", total_eligible=3)

    def test_commitment_ready_false_after_commit(self):
        """Cross-SDK parity (matches TypeScript ``commitmentReady``):
        ``commitment_ready`` must return False once the session is Committed,
        even if the approval threshold is still met. Callers that want the
        raw "threshold reached" check should use :meth:`has_quorum`.
        """
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
                "Approve",
                quorum_pb2.ApprovePayload(request_id="r1"),
                sender="alice",
            )
        )
        assert p.has_quorum("r1")
        assert p.commitment_ready("r1")

        # Commit the session
        commitment = build_commitment_payload(
            action="approve", authority_scope="quorum", reason="threshold met"
        )
        p.apply_envelope(
            make_envelope(
                MODE_QUORUM,
                "Commitment",
                commitment,
                sender="coordinator",
            )
        )
        assert p.phase == "Committed"
        # Threshold remains reached — but commitment_ready is now false
        assert p.has_quorum("r1")
        assert not p.commitment_ready("r1")

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
        assert p.approval_count("r1") == 1
        assert p.rejection_count("r1") == 0
        assert len(p.voted_senders("r1")) == 1
