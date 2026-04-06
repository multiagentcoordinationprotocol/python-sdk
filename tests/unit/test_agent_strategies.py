from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from macp_sdk.agent.strategies import (
    CommitmentDecision,
    EvaluationResult,
    VoteDecision,
    commitment_handler,
    evaluation_handler,
    function_committer,
    function_evaluator,
    function_voter,
    majority_committer,
    majority_voter,
    voting_handler,
)
from macp_sdk.agent.types import (
    HandlerContext,
    IncomingMessage,
    SessionInfo,
)


def _make_message(
    message_type: str = "Proposal",
    payload: dict[str, Any] | None = None,
) -> IncomingMessage:
    return IncomingMessage(
        message_type=message_type,
        sender="agent-a",
        payload=payload or {"option": "deploy"},
    )


def _make_context(projection: Any = None) -> HandlerContext:
    logs: list[str] = []

    def log_fn(fmt: str, *args: Any) -> None:
        logs.append(fmt % args if args else fmt)

    ctx = HandlerContext(
        participant="test-participant",
        projection=projection,
        actions=None,
        session=SessionInfo(session_id="s1", mode="macp.mode.decision.v1"),
        log_fn=log_fn,
    )
    ctx._test_logs = logs  # type: ignore[attr-defined]
    return ctx


class TestEvaluationStrategy:
    def test_function_evaluator(self):
        def eval_fn(
            proposal: dict[str, Any], context: SessionInfo
        ) -> EvaluationResult:
            return EvaluationResult(
                recommendation="APPROVE",
                confidence=0.95,
                reason="looks good",
            )

        strategy = function_evaluator(eval_fn)
        result = strategy.evaluate({"option": "deploy"}, SessionInfo("s1", "m1"))
        assert result.recommendation == "APPROVE"
        assert result.confidence == 0.95
        assert result.reason == "looks good"

    def test_evaluation_handler(self):
        strategy = function_evaluator(
            lambda p, c: EvaluationResult("REJECT", 0.3, "risky")
        )
        handler = evaluation_handler(strategy)
        ctx = _make_context()
        handler(_make_message(), ctx)
        logs = ctx._test_logs  # type: ignore[attr-defined]
        assert len(logs) == 1
        assert "REJECT" in logs[0]
        assert "0.30" in logs[0]

    def test_evaluation_result_frozen(self):
        r = EvaluationResult("APPROVE", 0.9, "ok")
        try:
            r.recommendation = "REJECT"  # type: ignore[misc]
            raise AssertionError("Should have raised")
        except AttributeError:
            pass


class TestVotingStrategy:
    def test_function_voter(self):
        strategy = function_voter(
            should_vote_fn=lambda p: True,
            decide_fn=lambda p: VoteDecision("approve", "good proposal"),
        )
        assert strategy.should_vote(None) is True
        decision = strategy.decide_vote(None)
        assert decision.vote == "approve"
        assert decision.reason == "good proposal"

    def test_voting_handler_votes_when_ready(self):
        strategy = function_voter(
            should_vote_fn=lambda p: True,
            decide_fn=lambda p: VoteDecision("approve", "all clear"),
        )
        handler = voting_handler(strategy)
        ctx = _make_context()
        handler(_make_message(), ctx)
        logs = ctx._test_logs  # type: ignore[attr-defined]
        assert len(logs) == 1
        assert "approve" in logs[0]

    def test_voting_handler_skips_when_not_ready(self):
        strategy = function_voter(
            should_vote_fn=lambda p: False,
            decide_fn=lambda p: VoteDecision("approve", ""),
        )
        handler = voting_handler(strategy)
        ctx = _make_context()
        handler(_make_message(), ctx)
        logs = ctx._test_logs  # type: ignore[attr-defined]
        assert len(logs) == 0

    def test_vote_decision_frozen(self):
        d = VoteDecision("approve", "ok")
        try:
            d.vote = "reject"  # type: ignore[misc]
            raise AssertionError("Should have raised")
        except AttributeError:
            pass


class TestCommitmentStrategy:
    def test_function_committer(self):
        strategy = function_committer(
            should_commit_fn=lambda p: True,
            decide_fn=lambda p: CommitmentDecision("deploy", "release", "quorum met"),
        )
        assert strategy.should_commit(None) is True
        decision = strategy.decide_commitment(None)
        assert decision.action == "deploy"
        assert decision.authority_scope == "release"
        assert decision.reason == "quorum met"

    def test_commitment_handler_commits_when_ready(self):
        strategy = function_committer(
            should_commit_fn=lambda p: True,
            decide_fn=lambda p: CommitmentDecision("approve", "full", "done"),
        )
        handler = commitment_handler(strategy)
        ctx = _make_context()
        handler(_make_message(), ctx)
        logs = ctx._test_logs  # type: ignore[attr-defined]
        assert len(logs) == 1
        assert "approve" in logs[0]
        assert "full" in logs[0]

    def test_commitment_handler_skips_when_not_ready(self):
        strategy = function_committer(
            should_commit_fn=lambda p: False,
            decide_fn=lambda p: CommitmentDecision("x", "y", "z"),
        )
        handler = commitment_handler(strategy)
        ctx = _make_context()
        handler(_make_message(), ctx)
        logs = ctx._test_logs  # type: ignore[attr-defined]
        assert len(logs) == 0

    def test_commitment_decision_frozen(self):
        d = CommitmentDecision("a", "b", "c")
        try:
            d.action = "x"  # type: ignore[misc]
            raise AssertionError("Should have raised")
        except AttributeError:
            pass


class TestStrategyComposition:
    """Test that strategies can be composed together on a single participant handler chain."""

    def test_evaluation_then_voting(self):
        eval_strategy = function_evaluator(
            lambda p, c: EvaluationResult("APPROVE", 0.9, "fine")
        )
        vote_strategy = function_voter(
            should_vote_fn=lambda p: True,
            decide_fn=lambda p: VoteDecision("approve", "evaluation passed"),
        )
        eval_h = evaluation_handler(eval_strategy)
        vote_h = voting_handler(vote_strategy)

        ctx = _make_context()
        msg = _make_message()
        eval_h(msg, ctx)
        vote_h(msg, ctx)

        logs = ctx._test_logs  # type: ignore[attr-defined]
        assert len(logs) == 2
        assert "APPROVE" in logs[0]
        assert "approve" in logs[1]


class TestMajorityVoter:
    def _mock_projection(self, totals: dict[str, int], winner: str | None = None):
        proj = MagicMock()
        proj.vote_totals.return_value = totals
        proj.majority_winner.return_value = winner
        return proj

    def test_should_vote_with_votes(self):
        strategy = majority_voter()
        proj = self._mock_projection({"approve": 3, "reject": 1}, "approve")
        assert strategy.should_vote(proj) is True

    def test_should_vote_no_votes(self):
        strategy = majority_voter()
        proj = self._mock_projection({})
        assert strategy.should_vote(proj) is False

    def test_should_vote_none_projection(self):
        strategy = majority_voter()
        assert strategy.should_vote(None) is False

    def test_decide_vote_with_winner(self):
        strategy = majority_voter()
        proj = self._mock_projection({"approve": 3}, "deploy-v2")
        decision = strategy.decide_vote(proj)
        assert decision.vote == "approve"
        assert "deploy-v2" in decision.reason

    def test_decide_vote_no_winner(self):
        strategy = majority_voter()
        proj = self._mock_projection({"approve": 1, "reject": 1})
        decision = strategy.decide_vote(proj)
        assert decision.vote == "abstain"

    def test_custom_threshold(self):
        strategy = majority_voter(positive_threshold=0.9)
        proj = self._mock_projection({"approve": 6, "reject": 4})
        # 6/10 = 0.6, below 0.9 threshold
        assert strategy.should_vote(proj) is False

        proj2 = self._mock_projection({"approve": 10, "reject": 1})
        # 10/11 = 0.91, above 0.9 threshold
        assert strategy.should_vote(proj2) is True


class TestMajorityCommitter:
    def _mock_projection(self, totals: dict[str, int], winner: str | None = None):
        proj = MagicMock()
        proj.vote_totals.return_value = totals
        proj.majority_winner.return_value = winner
        return proj

    def test_should_commit_with_quorum_and_winner(self):
        strategy = majority_committer(quorum_size=2)
        proj = self._mock_projection({"approve": 3}, "deploy")
        assert strategy.should_commit(proj) is True

    def test_should_commit_below_quorum(self):
        strategy = majority_committer(quorum_size=5)
        proj = self._mock_projection({"approve": 3}, "deploy")
        assert strategy.should_commit(proj) is False

    def test_should_commit_no_winner(self):
        strategy = majority_committer(quorum_size=1)
        proj = self._mock_projection({"approve": 2, "reject": 2})
        assert strategy.should_commit(proj) is False

    def test_should_commit_none_projection(self):
        strategy = majority_committer()
        assert strategy.should_commit(None) is False

    def test_decide_commitment(self):
        strategy = majority_committer(action="deploy", authority_scope="release")
        proj = self._mock_projection({"approve": 3}, "deploy-v2")
        decision = strategy.decide_commitment(proj)
        assert decision.action == "deploy"
        assert decision.authority_scope == "release"
        assert "deploy-v2" in decision.reason

    def test_default_action_and_scope(self):
        strategy = majority_committer()
        proj = self._mock_projection({"approve": 1}, "opt-a")
        decision = strategy.decide_commitment(proj)
        assert decision.action == "commit"
        assert decision.authority_scope == "default"
