from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class IncomingMessage:
    """A message received from the MACP session event stream."""

    message_type: str
    sender: str
    payload: dict[str, Any]
    proposal_id: str | None = None
    raw: Any = None
    seq: int | None = None


@dataclass(slots=True)
class SessionInfo:
    """Metadata about the current MACP session."""

    session_id: str
    mode: str
    participants: list[str] = field(default_factory=list)
    mode_version: str | None = None
    configuration_version: str | None = None
    policy_version: str | None = None


@dataclass(slots=True)
class TerminalResult:
    """Represents a terminal (committed/cancelled) session outcome."""

    state: str
    commitment: Any | None = None


class HandlerContext:
    """Context object passed to message handlers.

    Provides access to participant identity, session state projection,
    action methods, session metadata, and logging.
    """

    def __init__(
        self,
        participant: str,
        projection: Any,
        actions: Any,
        session: SessionInfo,
        log_fn: Callable[..., None],
    ) -> None:
        self.participant = participant
        self.projection = projection
        self.actions = actions
        self.session = session
        self.log = log_fn


MessageHandler = Callable[[IncomingMessage, HandlerContext], None]
TerminalHandler = Callable[[TerminalResult], None]
PhaseChangeHandler = Callable[[str, HandlerContext], None]
