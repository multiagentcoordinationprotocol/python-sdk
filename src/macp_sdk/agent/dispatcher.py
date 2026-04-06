from __future__ import annotations

from collections import defaultdict

from .._logging import logger
from .types import (
    HandlerContext,
    IncomingMessage,
    MessageHandler,
    PhaseChangeHandler,
    TerminalHandler,
    TerminalResult,
)


class Dispatcher:
    """Routes incoming MACP messages to registered handlers.

    Supports per-message-type handlers, per-phase-change handlers,
    wildcard ``'*'`` handlers (invoked for every event), and a single
    terminal handler.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[MessageHandler]] = defaultdict(list)
        self._wildcard_handlers: list[MessageHandler] = []
        self._phase_handlers: dict[str, list[PhaseChangeHandler]] = defaultdict(list)
        self._wildcard_phase_handlers: list[PhaseChangeHandler] = []
        self._terminal_handler: TerminalHandler | None = None

    def on(self, message_type: str, handler: MessageHandler) -> None:
        """Register a handler for a specific message type.

        Use ``'*'`` as the message_type to register a wildcard handler that
        is invoked for every message after type-specific handlers.
        """
        if message_type == "*":
            self._wildcard_handlers.append(handler)
        else:
            self._handlers[message_type].append(handler)

    def on_phase_change(self, phase: str, handler: PhaseChangeHandler) -> None:
        """Register a handler for a specific phase transition.

        Use ``'*'`` as the phase to register a wildcard handler that is
        invoked for every phase change after phase-specific handlers.
        """
        if phase == "*":
            self._wildcard_phase_handlers.append(handler)
        else:
            self._phase_handlers[phase].append(handler)

    def on_terminal(self, handler: TerminalHandler) -> None:
        """Register the terminal state handler (only one is allowed)."""
        self._terminal_handler = handler

    def dispatch(self, message: IncomingMessage, ctx: HandlerContext) -> None:
        """Dispatch a message to all matching handlers.

        Type-specific handlers are invoked first (in registration order),
        followed by wildcard ``'*'`` handlers.  If no handler matches at
        all, a debug-level log is emitted.
        """
        handlers = self._handlers.get(message.message_type)
        if not handlers and not self._wildcard_handlers:
            logger.debug("no handler for message_type=%s", message.message_type)
            return
        for handler in handlers or []:
            handler(message, ctx)
        for handler in self._wildcard_handlers:
            handler(message, ctx)

    def dispatch_phase_change(self, phase: str, ctx: HandlerContext) -> None:
        """Dispatch a phase change event to matching handlers.

        Phase-specific handlers are invoked first, followed by wildcard
        ``'*'`` phase handlers.
        """
        handlers = self._phase_handlers.get(phase)
        for handler in handlers or []:
            handler(phase, ctx)
        for handler in self._wildcard_phase_handlers:
            handler(phase, ctx)

    def dispatch_terminal(self, result: TerminalResult) -> None:
        """Invoke the terminal handler if registered."""
        if self._terminal_handler is not None:
            self._terminal_handler(result)
        else:
            logger.debug("terminal result with no handler: state=%s", result.state)

    @property
    def registered_message_types(self) -> list[str]:
        """Return all message types that have at least one handler."""
        return list(self._handlers.keys())

    @property
    def registered_phases(self) -> list[str]:
        """Return all phases that have at least one handler."""
        return list(self._phase_handlers.keys())

    @property
    def has_terminal_handler(self) -> bool:
        """Return whether a terminal handler is registered."""
        return self._terminal_handler is not None
