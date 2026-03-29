from __future__ import annotations

from macp_sdk.errors import (
    AckFailure,
    MacpAckError,
    MacpRetryError,
    MacpSdkError,
    MacpSessionError,
    MacpTimeoutError,
    MacpTransportError,
)


class TestErrorHierarchy:
    def test_base(self):
        assert issubclass(MacpSdkError, Exception)

    def test_transport_is_sdk(self):
        assert issubclass(MacpTransportError, MacpSdkError)

    def test_ack_is_sdk(self):
        assert issubclass(MacpAckError, MacpSdkError)

    def test_session_is_sdk(self):
        assert issubclass(MacpSessionError, MacpSdkError)

    def test_timeout_is_transport(self):
        assert issubclass(MacpTimeoutError, MacpTransportError)

    def test_retry_is_transport(self):
        assert issubclass(MacpRetryError, MacpTransportError)


class TestMacpAckError:
    def test_message(self):
        failure = AckFailure(code="FORBIDDEN", message="not allowed")
        err = MacpAckError(failure)
        assert "FORBIDDEN" in str(err)
        assert "not allowed" in str(err)

    def test_repr_with_context(self):
        failure = AckFailure(
            code="SESSION_NOT_FOUND",
            message="gone",
            session_id="sid-1",
        )
        err = MacpAckError(failure, mode="macp.mode.decision.v1", message_type="Vote")
        r = repr(err)
        assert "SESSION_NOT_FOUND" in r
        assert "sid-1" in r
        assert "decision" in r
        assert "Vote" in r

    def test_repr_minimal(self):
        failure = AckFailure(code="X", message="y")
        err = MacpAckError(failure)
        r = repr(err)
        assert "MacpAckError" in r
