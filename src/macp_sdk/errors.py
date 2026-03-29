from __future__ import annotations

from dataclasses import dataclass


class MacpSdkError(Exception):
    """Base SDK exception."""


@dataclass(slots=True)
class AckFailure:
    code: str
    message: str
    session_id: str = ""
    message_id: str = ""


class MacpAckError(MacpSdkError):
    """Runtime rejected the message (NACK)."""

    def __init__(
        self,
        failure: AckFailure,
        *,
        mode: str = "",
        message_type: str = "",
    ):
        self.failure = failure
        self.mode = mode
        self.message_type = message_type
        super().__init__(f"{failure.code}: {failure.message}")

    def __repr__(self) -> str:
        parts = [f"code={self.failure.code!r}", f"message={self.failure.message!r}"]
        if self.failure.session_id:
            parts.append(f"session_id={self.failure.session_id!r}")
        if self.mode:
            parts.append(f"mode={self.mode!r}")
        if self.message_type:
            parts.append(f"message_type={self.message_type!r}")
        return f"MacpAckError({', '.join(parts)})"


class MacpTransportError(MacpSdkError):
    """gRPC communication failure."""


class MacpSessionError(MacpSdkError):
    """Session-level error (wrong state, not started, already committed)."""


class MacpTimeoutError(MacpTransportError):
    """Operation timed out."""


class MacpRetryError(MacpTransportError):
    """All retry attempts exhausted."""
