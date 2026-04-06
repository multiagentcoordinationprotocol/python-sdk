from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import MagicMock

from macp.v1 import core_pb2, envelope_pb2

from macp_sdk.agent.participant import Participant, ParticipantActions
from macp_sdk.agent.runner import from_bootstrap
from macp_sdk.agent.types import IncomingMessage, TerminalResult
from macp_sdk.auth import AuthConfig
from macp_sdk.constants import MODE_DECISION
from macp_sdk.envelope import new_message_id, now_unix_ms, serialize_message
from macp_sdk.projections import DecisionProjection


def _make_mock_client() -> MagicMock:
    client = MagicMock()
    auth = AuthConfig.for_dev_agent("test-agent")
    client.auth = auth
    return client


def _make_envelope(
    message_type: str,
    payload_message: object,
    *,
    session_id: str = "test-session",
    sender: str = "agent-a",
    mode: str = MODE_DECISION,
) -> envelope_pb2.Envelope:
    return envelope_pb2.Envelope(
        macp_version="1.0",
        mode=mode,
        message_type=message_type,
        message_id=new_message_id(),
        session_id=session_id,
        sender=sender,
        timestamp_unix_ms=now_unix_ms(),
        payload=serialize_message(payload_message),
    )


class TestParticipantCreation:
    def test_basic_creation(self):
        client = _make_mock_client()
        p = Participant(
            participant_id="agent-a",
            session_id="s1",
            mode=MODE_DECISION,
            client=client,
        )
        assert p.participant_id == "agent-a"
        assert p.session_id == "s1"
        assert p.mode == MODE_DECISION
        assert not p.is_stopped
        assert isinstance(p.projection, DecisionProjection)

    def test_unknown_mode_has_no_projection(self):
        client = _make_mock_client()
        p = Participant(
            participant_id="agent-a",
            session_id="s1",
            mode="ext.custom.v1",
            client=client,
        )
        assert p.projection is None

    def test_session_info(self):
        client = _make_mock_client()
        p = Participant(
            participant_id="agent-a",
            session_id="s1",
            mode=MODE_DECISION,
            client=client,
            participants=["agent-a", "agent-b"],
            policy_version="policy.strict",
        )
        assert p.session.session_id == "s1"
        assert p.session.mode == MODE_DECISION
        assert p.session.participants == ["agent-a", "agent-b"]
        assert p.session.policy_version == "policy.strict"


class TestParticipantHandlerRegistration:
    def test_fluent_on(self):
        client = _make_mock_client()
        p = Participant(
            participant_id="agent-a",
            session_id="s1",
            mode=MODE_DECISION,
            client=client,
        )
        result = p.on("Proposal", lambda msg, ctx: None)
        assert result is p  # fluent API returns self

    def test_fluent_on_phase_change(self):
        client = _make_mock_client()
        p = Participant(
            participant_id="agent-a",
            session_id="s1",
            mode=MODE_DECISION,
            client=client,
        )
        result = p.on_phase_change("Evaluation", lambda phase, ctx: None)
        assert result is p

    def test_fluent_on_terminal(self):
        client = _make_mock_client()
        p = Participant(
            participant_id="agent-a",
            session_id="s1",
            mode=MODE_DECISION,
            client=client,
        )
        result = p.on_terminal(lambda result: None)
        assert result is p

    def test_chained_registration(self):
        client = _make_mock_client()
        p = (
            Participant(
                participant_id="agent-a",
                session_id="s1",
                mode=MODE_DECISION,
                client=client,
            )
            .on("Proposal", lambda msg, ctx: None)
            .on("Vote", lambda msg, ctx: None)
            .on_phase_change("Evaluation", lambda phase, ctx: None)
            .on_terminal(lambda result: None)
        )
        assert isinstance(p, Participant)


class TestParticipantEventProcessing:
    def test_process_event_dispatches_handler(self):
        from macp.modes.decision.v1 import decision_pb2

        client = _make_mock_client()
        received: list[IncomingMessage] = []
        p = Participant(
            participant_id="agent-a",
            session_id="test-session",
            mode=MODE_DECISION,
            client=client,
        )
        p.on("Proposal", lambda msg, ctx: received.append(msg))

        envelope = _make_envelope(
            "Proposal",
            decision_pb2.ProposalPayload(proposal_id="p1", option="opt-a"),
        )
        p.process_event(envelope)
        assert len(received) == 1
        assert received[0].message_type == "Proposal"

    def test_commitment_triggers_terminal(self):
        client = _make_mock_client()
        terminal_results: list[TerminalResult] = []
        p = Participant(
            participant_id="agent-a",
            session_id="test-session",
            mode=MODE_DECISION,
            client=client,
        )
        p.on_terminal(lambda r: terminal_results.append(r))

        envelope = _make_envelope(
            "Commitment",
            core_pb2.CommitmentPayload(
                commitment_id="c1",
                action="deploy",
                authority_scope="release",
                reason="approved",
            ),
        )
        p.process_event(envelope)
        assert p.is_stopped
        assert len(terminal_results) == 1
        assert terminal_results[0].state == "Committed"

    def test_session_cancel_triggers_terminal(self):
        client = _make_mock_client()
        terminal_results: list[TerminalResult] = []
        p = Participant(
            participant_id="agent-a",
            session_id="test-session",
            mode=MODE_DECISION,
            client=client,
        )
        p.on_terminal(lambda r: terminal_results.append(r))

        envelope = _make_envelope(
            "SessionCancel",
            core_pb2.SessionCancelPayload(reason="timeout"),
        )
        p.process_event(envelope)
        assert p.is_stopped
        assert len(terminal_results) == 1
        assert terminal_results[0].state == "Cancelled"
        assert terminal_results[0].commitment is None

    def test_stop_sets_stopped(self):
        client = _make_mock_client()
        p = Participant(
            participant_id="agent-a",
            session_id="s1",
            mode=MODE_DECISION,
            client=client,
        )
        assert not p.is_stopped
        p.stop()
        assert p.is_stopped

    def test_projection_updated_on_event(self):
        from macp.modes.decision.v1 import decision_pb2

        client = _make_mock_client()
        p = Participant(
            participant_id="agent-a",
            session_id="test-session",
            mode=MODE_DECISION,
            client=client,
        )
        envelope = _make_envelope(
            "Proposal",
            decision_pb2.ProposalPayload(proposal_id="p1", option="opt-a"),
        )
        p.process_event(envelope)
        assert p.projection is not None
        proj = p.projection
        assert isinstance(proj, DecisionProjection)
        assert "p1" in proj.proposals


class TestParticipantActions:
    def test_send_envelope(self):
        client = _make_mock_client()
        actions = ParticipantActions(client, "s1", None)
        actions.send_envelope(MagicMock())
        client.send.assert_called_once()

    def test_get_session(self):
        client = _make_mock_client()
        actions = ParticipantActions(client, "s1", None)
        actions.get_session()
        client.get_session.assert_called_once_with("s1", auth=None)

    def test_cancel_session(self):
        client = _make_mock_client()
        actions = ParticipantActions(client, "s1", None)
        actions.cancel_session("timeout")
        client.cancel_session.assert_called_once_with("s1", reason="timeout", auth=None)


class TestFromBootstrap:
    def test_basic_bootstrap(self):
        bootstrap = {
            "participant_id": "agent-x",
            "session_id": "sess-123",
            "mode": "macp.mode.decision.v1",
            "runtime_url": "localhost:50051",
            "auth": {"agent_id": "agent-x"},
            "participants": ["agent-x", "agent-y"],
            "policy_version": "policy.strict",
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(bootstrap, f)
            path = f.name
        try:
            p = from_bootstrap(path)
            assert p.participant_id == "agent-x"
            assert p.session_id == "sess-123"
            assert p.mode == "macp.mode.decision.v1"
            assert p.session.participants == ["agent-x", "agent-y"]
            assert p.session.policy_version == "policy.strict"
        finally:
            os.unlink(path)

    def test_bootstrap_with_bearer_token(self):
        bootstrap = {
            "participant_id": "agent-z",
            "session_id": "sess-456",
            "mode": "macp.mode.task.v1",
            "runtime_url": "localhost:50052",
            "auth": {"bearer_token": "secret-token"},
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(bootstrap, f)
            path = f.name
        try:
            p = from_bootstrap(path)
            assert p.participant_id == "agent-z"
            assert p.mode == "macp.mode.task.v1"
        finally:
            os.unlink(path)

    def test_bootstrap_env_var(self):
        bootstrap = {
            "participant_id": "agent-env",
            "session_id": "sess-env",
            "mode": "macp.mode.quorum.v1",
            "auth": {"agent_id": "agent-env"},
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(bootstrap, f)
            path = f.name
        try:
            os.environ["MACP_BOOTSTRAP_FILE"] = path
            p = from_bootstrap()
            assert p.participant_id == "agent-env"
            assert p.session_id == "sess-env"
        finally:
            os.unlink(path)
            del os.environ["MACP_BOOTSTRAP_FILE"]

    def test_no_path_raises(self):
        # Ensure env var is not set
        old = os.environ.pop("MACP_BOOTSTRAP_FILE", None)
        try:
            try:
                from_bootstrap()
                raise AssertionError("Should have raised")
            except ValueError as e:
                assert "MACP_BOOTSTRAP_FILE" in str(e)
        finally:
            if old is not None:
                os.environ["MACP_BOOTSTRAP_FILE"] = old
