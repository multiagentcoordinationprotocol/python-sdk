from __future__ import annotations

from typing import Any

from .._logging import logger
from ..auth import AuthConfig
from ..base_projection import BaseProjection
from ..client import MacpClient
from ..constants import (
    MODE_DECISION,
    MODE_HANDOFF,
    MODE_PROPOSAL,
    MODE_QUORUM,
    MODE_TASK,
)
from ..handoff import HandoffProjection
from ..projections import DecisionProjection
from ..proposal import ProposalProjection
from ..quorum import QuorumProjection
from ..task import TaskProjection
from .dispatcher import Dispatcher
from .transports import GrpcTransportAdapter, TransportAdapter, _envelope_to_message
from .types import (
    HandlerContext,
    IncomingMessage,
    MessageHandler,
    PhaseChangeHandler,
    SessionInfo,
    TerminalHandler,
    TerminalResult,
)

_MODE_PROJECTIONS: dict[str, type[BaseProjection]] = {
    MODE_DECISION: DecisionProjection,
    MODE_PROPOSAL: ProposalProjection,
    MODE_QUORUM: QuorumProjection,
    MODE_TASK: TaskProjection,
    MODE_HANDOFF: HandoffProjection,
}


class ParticipantActions:
    """Thin wrapper providing action methods bound to a participant's session."""

    def __init__(self, client: MacpClient, session_id: str, auth: AuthConfig | None) -> None:
        self._client = client
        self._session_id = session_id
        self._auth = auth

    def send_envelope(self, envelope: Any) -> Any:
        """Send a pre-built envelope via the MACP client."""
        return self._client.send(envelope, auth=self._auth)

    def get_session(self) -> Any:
        """Query session metadata from the runtime."""
        return self._client.get_session(self._session_id, auth=self._auth)

    def cancel_session(self, reason: str = "") -> Any:
        """Cancel the session."""
        return self._client.cancel_session(self._session_id, reason=reason, auth=self._auth)


class Participant:
    """High-level agent abstraction for participating in MACP sessions.

    Wraps a :class:`MacpClient`, a :class:`Dispatcher`, and a mode-specific
    projection.  Handlers are registered via ``on()``, ``on_phase_change()``,
    and ``on_terminal()`` with a fluent API.

    The ``run()`` method enters a blocking event loop that polls the
    control-plane for session events and dispatches them to handlers.
    Call ``stop()`` to signal the loop to exit.
    """

    def __init__(
        self,
        *,
        participant_id: str,
        session_id: str,
        mode: str,
        client: MacpClient,
        auth: AuthConfig | None = None,
        participants: list[str] | None = None,
        policy_version: str | None = None,
        transport: TransportAdapter | None = None,
    ) -> None:
        self._participant_id = participant_id
        self._session_id = session_id
        self._mode = mode
        self._client = client
        self._auth = auth
        self._stopped = False

        self._dispatcher = Dispatcher()
        self._session = SessionInfo(
            session_id=session_id,
            mode=mode,
            participants=list(participants or []),
            policy_version=policy_version,
        )

        projection_cls = _MODE_PROJECTIONS.get(mode)
        if projection_cls is not None:
            self._projection: BaseProjection | None = projection_cls()
        else:
            self._projection = None

        self._actions = ParticipantActions(client, session_id, auth)
        self._last_phase: str | None = None
        self._transport = transport

    @property
    def participant_id(self) -> str:
        return self._participant_id

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def projection(self) -> BaseProjection | None:
        return self._projection

    @property
    def actions(self) -> ParticipantActions:
        return self._actions

    @property
    def session(self) -> SessionInfo:
        return self._session

    @property
    def is_stopped(self) -> bool:
        return self._stopped

    def on(self, message_type: str, handler: MessageHandler) -> Participant:
        """Register a handler for a message type (fluent API)."""
        self._dispatcher.on(message_type, handler)
        return self

    def on_phase_change(self, phase: str, handler: PhaseChangeHandler) -> Participant:
        """Register a handler for a phase change (fluent API)."""
        self._dispatcher.on_phase_change(phase, handler)
        return self

    def on_terminal(self, handler: TerminalHandler) -> Participant:
        """Register the terminal handler (fluent API)."""
        self._dispatcher.on_terminal(handler)
        return self

    def _build_context(self) -> HandlerContext:
        return HandlerContext(
            participant=self._participant_id,
            projection=self._projection,
            actions=self._actions,
            session=self._session,
            log_fn=logger.info,
        )

    def _process_envelope(self, envelope: Any) -> None:
        """Process a single envelope: update projection, dispatch handlers."""
        # Update the projection if available
        if self._projection is not None:
            self._projection.apply_envelope(envelope)

        # Check for terminal messages
        if envelope.message_type == "Commitment":
            result = TerminalResult(
                state="Committed",
                commitment=envelope,
            )
            self._dispatcher.dispatch_terminal(result)
            self._stopped = True
            return

        if envelope.message_type == "SessionCancel":
            result = TerminalResult(state="Cancelled")
            self._dispatcher.dispatch_terminal(result)
            self._stopped = True
            return

        # Build the message and context
        message = _envelope_to_message(envelope)
        ctx = self._build_context()

        # Dispatch message handler
        self._dispatcher.dispatch(message, ctx)

        # Check for phase changes
        if self._projection is not None:
            current_phase = self._projection.phase
            if current_phase and current_phase != self._last_phase:
                self._dispatcher.dispatch_phase_change(current_phase, ctx)
                self._last_phase = current_phase

    def _process_message(self, message: IncomingMessage) -> None:
        """Process a pre-built IncomingMessage (from HTTP transport)."""
        ctx = self._build_context()

        if message.message_type == "Commitment":
            result = TerminalResult(state="Committed")
            self._dispatcher.dispatch_terminal(result)
            self._stopped = True
            return

        if message.message_type == "SessionCancel":
            result = TerminalResult(state="Cancelled")
            self._dispatcher.dispatch_terminal(result)
            self._stopped = True
            return

        self._dispatcher.dispatch(message, ctx)

    def run(self) -> None:
        """Enter the blocking event loop.

        If a :class:`TransportAdapter` was provided, it is used to receive
        messages.  Otherwise a gRPC ``StreamSession`` is opened.

        Dispatches received events to registered handlers until the session
        reaches a terminal state or ``stop()`` is called.
        """
        logger.info(
            "participant %s joining session %s (mode=%s)",
            self._participant_id,
            self._session_id,
            self._mode,
        )

        transport = self._transport or GrpcTransportAdapter(
            self._client,
            self._session_id,
            auth=self._auth,
        )
        try:
            for message in transport.start():
                if self._stopped:
                    break
                # If the transport yields raw envelopes (gRPC), process as envelope
                if message.raw is not None:
                    self._process_envelope(message.raw)
                else:
                    self._process_message(message)
        finally:
            transport.stop()

    def process_event(self, envelope: Any) -> None:
        """Manually process a single envelope (for testing or polling transports)."""
        self._process_envelope(envelope)

    def stop(self) -> None:
        """Signal the event loop to stop."""
        self._stopped = True
