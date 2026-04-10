"""Tests for new error codes and structured POLICY_DENIED."""

from __future__ import annotations

from macp_sdk.errors import (
    INVALID_POLICY_DEFINITION,
    POLICY_DENIED,
    SESSION_ALREADY_EXISTS,
    UNKNOWN_POLICY_VERSION,
    AckFailure,
    MacpAckError,
)
from macp_sdk.retry import RetryPolicy


class TestErrorCodeConstants:
    def test_session_already_exists(self):
        assert SESSION_ALREADY_EXISTS == "SESSION_ALREADY_EXISTS"

    def test_policy_denied(self):
        assert POLICY_DENIED == "POLICY_DENIED"

    def test_unknown_policy_version(self):
        assert UNKNOWN_POLICY_VERSION == "UNKNOWN_POLICY_VERSION"

    def test_invalid_policy_definition(self):
        assert INVALID_POLICY_DEFINITION == "INVALID_POLICY_DEFINITION"


class TestAckFailureReasons:
    def test_reasons_default_empty(self):
        f = AckFailure(code="TEST", message="test")
        assert f.reasons == []

    def test_reasons_populated(self):
        f = AckFailure(
            code="POLICY_DENIED",
            message="denied",
            reasons=["voting quorum not met", "evaluation required"],
        )
        assert len(f.reasons) == 2
        assert "voting quorum not met" in f.reasons

    def test_macp_ack_error_reasons_property(self):
        f = AckFailure(
            code="POLICY_DENIED",
            message="denied",
            reasons=["reason-a", "reason-b"],
        )
        err = MacpAckError(f)
        assert err.reasons == ["reason-a", "reason-b"]

    def test_macp_ack_error_repr_includes_reasons(self):
        f = AckFailure(
            code="POLICY_DENIED",
            message="denied",
            reasons=["quorum"],
        )
        err = MacpAckError(f)
        assert "reasons=" in repr(err)


class TestNonRetryableCodes:
    def test_session_already_exists_not_retryable(self):
        policy = RetryPolicy()
        assert SESSION_ALREADY_EXISTS not in policy.retryable_codes

    def test_policy_denied_not_retryable(self):
        policy = RetryPolicy()
        assert POLICY_DENIED not in policy.retryable_codes

    def test_unknown_policy_version_not_retryable(self):
        policy = RetryPolicy()
        assert UNKNOWN_POLICY_VERSION not in policy.retryable_codes

    def test_invalid_policy_definition_not_retryable(self):
        policy = RetryPolicy()
        assert INVALID_POLICY_DEFINITION not in policy.retryable_codes
