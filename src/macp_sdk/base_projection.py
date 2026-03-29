from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from macp.v1 import core_pb2, envelope_pb2


class BaseProjection(ABC):
    """Abstract base for in-process mode state tracking.

    Maintains a local transcript and delegates mode-specific message handling
    to subclasses.  Needed because the runtime's ``GetSession`` RPC returns
    metadata only, not mode state or transcript.
    """

    MODE: ClassVar[str]

    def __init__(self) -> None:
        self.transcript: list[envelope_pb2.Envelope] = []
        self.phase: str = ""
        self.commitment: core_pb2.CommitmentPayload | None = None

    @property
    def is_committed(self) -> bool:
        return self.commitment is not None

    def apply_envelope(self, envelope: envelope_pb2.Envelope) -> None:
        """Process an accepted envelope and update local state."""
        if envelope.mode != self.MODE:
            return
        self.transcript.append(envelope)

        if envelope.message_type == "Commitment":
            payload = core_pb2.CommitmentPayload()
            payload.ParseFromString(envelope.payload)
            self.commitment = payload
            self.phase = "Committed"
            return

        self._apply_mode_message(envelope)

    @abstractmethod
    def _apply_mode_message(self, envelope: envelope_pb2.Envelope) -> None:
        """Handle a mode-specific (non-Commitment) envelope."""
