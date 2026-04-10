from __future__ import annotations

from macp_sdk.agent.dispatcher import Dispatcher
from macp_sdk.agent.types import (
    HandlerContext,
    IncomingMessage,
    SessionInfo,
    TerminalResult,
)


def _make_message(message_type: str = "Proposal", sender: str = "agent-a") -> IncomingMessage:
    return IncomingMessage(
        message_type=message_type,
        sender=sender,
        payload={"key": "value"},
    )


def _make_context(participant: str = "test-participant") -> HandlerContext:
    return HandlerContext(
        participant=participant,
        projection=None,
        actions=None,
        session=SessionInfo(session_id="s1", mode="macp.mode.decision.v1"),
        log_fn=lambda *a, **kw: None,
    )


class TestDispatcher:
    def test_on_registers_handler(self):
        d = Dispatcher()
        called = []
        d.on("Proposal", lambda msg, ctx: called.append(msg.message_type))
        assert "Proposal" in d.registered_message_types
        d.dispatch(_make_message("Proposal"), _make_context())
        assert called == ["Proposal"]

    def test_multiple_handlers_same_type(self):
        d = Dispatcher()
        calls: list[str] = []
        d.on("Vote", lambda msg, ctx: calls.append("h1"))
        d.on("Vote", lambda msg, ctx: calls.append("h2"))
        d.dispatch(_make_message("Vote"), _make_context())
        assert calls == ["h1", "h2"]

    def test_dispatch_no_handler_does_not_raise(self):
        d = Dispatcher()
        d.dispatch(_make_message("UnknownType"), _make_context())

    def test_on_phase_change(self):
        d = Dispatcher()
        phases: list[str] = []
        d.on_phase_change("Evaluation", lambda phase, ctx: phases.append(phase))
        assert "Evaluation" in d.registered_phases
        d.dispatch_phase_change("Evaluation", _make_context())
        assert phases == ["Evaluation"]

    def test_phase_change_no_handler(self):
        d = Dispatcher()
        d.dispatch_phase_change("UnknownPhase", _make_context())

    def test_terminal_handler(self):
        d = Dispatcher()
        results: list[str] = []
        d.on_terminal(lambda result: results.append(result.state))
        assert d.has_terminal_handler
        d.dispatch_terminal(TerminalResult(state="Committed"))
        assert results == ["Committed"]

    def test_terminal_no_handler(self):
        d = Dispatcher()
        assert not d.has_terminal_handler
        d.dispatch_terminal(TerminalResult(state="Committed"))

    def test_registered_message_types_empty(self):
        d = Dispatcher()
        assert d.registered_message_types == []

    def test_registered_phases_empty(self):
        d = Dispatcher()
        assert d.registered_phases == []

    def test_handler_receives_correct_context(self):
        d = Dispatcher()
        received_ctx: list[HandlerContext] = []
        d.on("Proposal", lambda msg, ctx: received_ctx.append(ctx))
        ctx = _make_context("my-agent")
        d.dispatch(_make_message("Proposal"), ctx)
        assert len(received_ctx) == 1
        assert received_ctx[0].participant == "my-agent"

    def test_dispatch_passes_correct_message(self):
        d = Dispatcher()
        received: list[IncomingMessage] = []
        d.on("Evaluation", lambda msg, ctx: received.append(msg))
        msg = _make_message("Evaluation", sender="evaluator")
        d.dispatch(msg, _make_context())
        assert len(received) == 1
        assert received[0].sender == "evaluator"
        assert received[0].payload == {"key": "value"}


class TestWildcardHandlers:
    def test_wildcard_message_handler(self):
        d = Dispatcher()
        calls: list[str] = []
        d.on("*", lambda msg, ctx: calls.append(msg.message_type))
        d.dispatch(_make_message("Proposal"), _make_context())
        d.dispatch(_make_message("Vote"), _make_context())
        assert calls == ["Proposal", "Vote"]

    def test_wildcard_runs_after_specific(self):
        d = Dispatcher()
        order: list[str] = []
        d.on("Proposal", lambda msg, ctx: order.append("specific"))
        d.on("*", lambda msg, ctx: order.append("wildcard"))
        d.dispatch(_make_message("Proposal"), _make_context())
        assert order == ["specific", "wildcard"]

    def test_wildcard_not_in_registered_message_types(self):
        d = Dispatcher()
        d.on("*", lambda msg, ctx: None)
        assert d.registered_message_types == []

    def test_wildcard_handles_unregistered_types(self):
        d = Dispatcher()
        calls: list[str] = []
        d.on("*", lambda msg, ctx: calls.append(msg.message_type))
        d.dispatch(_make_message("NeverRegistered"), _make_context())
        assert calls == ["NeverRegistered"]

    def test_wildcard_phase_handler(self):
        d = Dispatcher()
        phases: list[str] = []
        d.on_phase_change("*", lambda phase, ctx: phases.append(phase))
        d.dispatch_phase_change("Evaluation", _make_context())
        d.dispatch_phase_change("Voting", _make_context())
        assert phases == ["Evaluation", "Voting"]

    def test_wildcard_phase_runs_after_specific(self):
        d = Dispatcher()
        order: list[str] = []
        d.on_phase_change("Evaluation", lambda phase, ctx: order.append("specific"))
        d.on_phase_change("*", lambda phase, ctx: order.append("wildcard"))
        d.dispatch_phase_change("Evaluation", _make_context())
        assert order == ["specific", "wildcard"]

    def test_wildcard_phase_not_in_registered_phases(self):
        d = Dispatcher()
        d.on_phase_change("*", lambda phase, ctx: None)
        assert d.registered_phases == []
