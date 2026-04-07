"""Tests for outcome_positive inference and CommitmentPayload integration."""

from __future__ import annotations

from macp_sdk.envelope import _infer_outcome_positive, build_commitment_payload


class TestInferOutcomePositive:
    def test_positive_suffixes(self):
        assert _infer_outcome_positive("deployment.selected") is True
        assert _infer_outcome_positive("proposal.accepted") is True
        assert _infer_outcome_positive("task.completed") is True
        assert _infer_outcome_positive("quorum.approved") is True

    def test_negative_suffixes(self):
        assert _infer_outcome_positive("proposal.rejected") is False
        assert _infer_outcome_positive("task.failed") is False
        assert _infer_outcome_positive("handoff.declined") is False

    def test_unknown_suffix_defaults_positive(self):
        assert _infer_outcome_positive("custom.action") is True
        assert _infer_outcome_positive("commit") is True

    def test_case_insensitive(self):
        assert _infer_outcome_positive("DEPLOYMENT.REJECTED") is False
        assert _infer_outcome_positive("TASK.COMPLETED") is True


class TestBuildCommitmentPayloadOutcome:
    def test_auto_inferred_positive(self):
        payload = build_commitment_payload(
            action="deployment.approved",
            authority_scope="release",
            reason="test",
        )
        assert payload.action == "deployment.approved"

    def test_auto_inferred_negative(self):
        payload = build_commitment_payload(
            action="proposal.rejected",
            authority_scope="negotiation",
            reason="test",
        )
        assert payload.action == "proposal.rejected"

    def test_explicit_override(self):
        payload = build_commitment_payload(
            action="custom.action",
            authority_scope="test",
            reason="test",
            outcome_positive=False,
        )
        assert payload.action == "custom.action"
