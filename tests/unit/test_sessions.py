"""Test that session helpers build and send correct envelopes via the mock client."""

from __future__ import annotations

from unittest.mock import MagicMock

from macp_sdk.constants import (
    MODE_DECISION,
    MODE_HANDOFF,
    MODE_PROPOSAL,
    MODE_QUORUM,
    MODE_TASK,
)
from macp_sdk.decision import DecisionSession
from macp_sdk.handoff import HandoffSession
from macp_sdk.proposal import ProposalSession
from macp_sdk.quorum import QuorumSession
from macp_sdk.task import TaskSession


def _sent_envelope(mock_client: MagicMock):
    """Extract the last envelope passed to mock_client.send()."""
    args, _ = mock_client.send.call_args
    return args[0]


class TestDecisionSession:
    def test_start(self, mock_client):
        s = DecisionSession(mock_client, session_id="s1")
        s.start(intent="pick", participants=["a", "b"], ttl_ms=60000)
        env = _sent_envelope(mock_client)
        assert env.mode == MODE_DECISION
        assert env.message_type == "SessionStart"
        assert env.session_id == "s1"

    def test_propose(self, mock_client):
        s = DecisionSession(mock_client, session_id="s1")
        s.propose("p1", "option-a")
        env = _sent_envelope(mock_client)
        assert env.message_type == "Proposal"

    def test_vote(self, mock_client):
        s = DecisionSession(mock_client, session_id="s1")
        s.vote("p1", "approve", sender="alice")
        env = _sent_envelope(mock_client)
        assert env.message_type == "Vote"
        assert env.sender == "alice"

    def test_commit(self, mock_client):
        s = DecisionSession(mock_client, session_id="s1")
        s.commit(action="deploy", authority_scope="release", reason="approved")
        env = _sent_envelope(mock_client)
        assert env.message_type == "Commitment"


class TestProposalSession:
    def test_propose(self, mock_client):
        s = ProposalSession(mock_client, session_id="s1")
        s.propose("p1", "Plan A", summary="first offer")
        env = _sent_envelope(mock_client)
        assert env.mode == MODE_PROPOSAL
        assert env.message_type == "Proposal"

    def test_counter_propose(self, mock_client):
        s = ProposalSession(mock_client, session_id="s1")
        s.counter_propose("p2", "p1", "Plan B")
        env = _sent_envelope(mock_client)
        assert env.message_type == "CounterProposal"

    def test_accept(self, mock_client):
        s = ProposalSession(mock_client, session_id="s1")
        s.accept("p1", sender="bob")
        env = _sent_envelope(mock_client)
        assert env.message_type == "Accept"

    def test_reject(self, mock_client):
        s = ProposalSession(mock_client, session_id="s1")
        s.reject("p1", terminal=True, sender="bob")
        env = _sent_envelope(mock_client)
        assert env.message_type == "Reject"

    def test_withdraw(self, mock_client):
        s = ProposalSession(mock_client, session_id="s1")
        s.withdraw("p1", sender="alice")
        env = _sent_envelope(mock_client)
        assert env.message_type == "Withdraw"


class TestTaskSession:
    def test_request(self, mock_client):
        s = TaskSession(mock_client, session_id="s1")
        s.request("t1", "Analyze", instructions="run pipeline")
        env = _sent_envelope(mock_client)
        assert env.mode == MODE_TASK
        assert env.message_type == "TaskRequest"

    def test_accept_task(self, mock_client):
        s = TaskSession(mock_client, session_id="s1")
        s.accept_task("t1", sender="worker")
        env = _sent_envelope(mock_client)
        assert env.message_type == "TaskAccept"

    def test_complete(self, mock_client):
        s = TaskSession(mock_client, session_id="s1")
        s.complete("t1", output=b"result", summary="done", sender="worker")
        env = _sent_envelope(mock_client)
        assert env.message_type == "TaskComplete"

    def test_fail(self, mock_client):
        s = TaskSession(mock_client, session_id="s1")
        s.fail("t1", error_code="ERR", reason="broke", sender="worker")
        env = _sent_envelope(mock_client)
        assert env.message_type == "TaskFail"


class TestHandoffSession:
    def test_offer(self, mock_client):
        s = HandoffSession(mock_client, session_id="s1")
        s.offer("h1", "bob", scope="service-xyz")
        env = _sent_envelope(mock_client)
        assert env.mode == MODE_HANDOFF
        assert env.message_type == "HandoffOffer"

    def test_add_context(self, mock_client):
        s = HandoffSession(mock_client, session_id="s1")
        s.add_context("h1", context=b"data")
        env = _sent_envelope(mock_client)
        assert env.message_type == "HandoffContext"

    def test_accept_handoff(self, mock_client):
        s = HandoffSession(mock_client, session_id="s1")
        s.accept_handoff("h1", sender="bob")
        env = _sent_envelope(mock_client)
        assert env.message_type == "HandoffAccept"

    def test_decline(self, mock_client):
        s = HandoffSession(mock_client, session_id="s1")
        s.decline("h1", reason="not ready", sender="bob")
        env = _sent_envelope(mock_client)
        assert env.message_type == "HandoffDecline"


class TestQuorumSession:
    def test_request_approval(self, mock_client):
        s = QuorumSession(mock_client, session_id="s1")
        s.request_approval("r1", "deploy", required_approvals=2)
        env = _sent_envelope(mock_client)
        assert env.mode == MODE_QUORUM
        assert env.message_type == "ApprovalRequest"

    def test_approve(self, mock_client):
        s = QuorumSession(mock_client, session_id="s1")
        s.approve("r1", sender="alice")
        env = _sent_envelope(mock_client)
        assert env.message_type == "Approve"

    def test_reject(self, mock_client):
        s = QuorumSession(mock_client, session_id="s1")
        s.reject("r1", sender="bob")
        env = _sent_envelope(mock_client)
        assert env.message_type == "Reject"

    def test_abstain(self, mock_client):
        s = QuorumSession(mock_client, session_id="s1")
        s.abstain("r1", sender="carol")
        env = _sent_envelope(mock_client)
        assert env.message_type == "Abstain"
