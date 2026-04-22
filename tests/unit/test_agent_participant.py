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
            "secure": False,
            "allow_insecure": True,
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
            "secure": False,
            "allow_insecure": True,
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
            "secure": False,
            "allow_insecure": True,
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

    def test_bootstrap_rejects_insecure_without_opt_in(self):
        """secure=false without allow_insecure=true must fail (RFC-0006 §3)."""
        import pytest

        from macp_sdk.errors import MacpSdkError

        bootstrap = {
            "participant_id": "agent-x",
            "session_id": "sess-x",
            "mode": "macp.mode.decision.v1",
            "runtime_url": "localhost:50051",
            "auth": {"agent_id": "agent-x"},
            "secure": False,
            # allow_insecure intentionally omitted
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(bootstrap, f)
            path = f.name
        try:
            with pytest.raises(MacpSdkError, match="allow_insecure=True"):
                from_bootstrap(path)
        finally:
            os.unlink(path)

    def test_bootstrap_propagates_expected_sender(self):
        """auth.expected_sender (or participant_id fallback) wires through to AuthConfig."""
        bootstrap = {
            "participant_id": "alice",
            "session_id": "sess-1",
            "mode": "macp.mode.decision.v1",
            "runtime_url": "localhost:50051",
            "auth": {"bearer_token": "tok-alice"},
            "secure": False,
            "allow_insecure": True,
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(bootstrap, f)
            path = f.name
        try:
            p = from_bootstrap(path)
            assert p._auth is not None
            assert p._auth.expected_sender == "alice"
            assert p._auth.bearer_token == "tok-alice"
        finally:
            os.unlink(path)

    def test_bootstrap_flat_auth_token(self):
        """Flat ``auth_token`` field (new examples-service format)."""
        bootstrap = {
            "participant_id": "agent-flat",
            "session_id": "sess-flat",
            "mode": "macp.mode.decision.v1",
            "runtime_url": "localhost:50051",
            "auth_token": "tok-flat-123",
            "secure": False,
            "allow_insecure": True,
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(bootstrap, f)
            path = f.name
        try:
            p = from_bootstrap(path)
            assert p._auth is not None
            assert p._auth.bearer_token == "tok-flat-123"
            assert p._auth.expected_sender == "agent-flat"
        finally:
            os.unlink(path)

    def test_bootstrap_flat_agent_id(self):
        """Flat ``agent_id`` field for dev auth."""
        bootstrap = {
            "participant_id": "dev-1",
            "session_id": "sess-dev",
            "mode": "macp.mode.decision.v1",
            "agent_id": "dev-1",
            "secure": False,
            "allow_insecure": True,
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(bootstrap, f)
            path = f.name
        try:
            p = from_bootstrap(path)
            assert p._auth is not None
            # Since SDK 0.2.4, ``for_dev_agent`` tunnels the agent id
            # through the Bearer header (runtime v0.4.0+ rejects the
            # legacy ``x-macp-agent-id`` header).
            assert p._auth.bearer_token == "dev-1"
            assert p._auth.sender == "dev-1"
            assert p._auth.expected_sender == "dev-1"
        finally:
            os.unlink(path)

    def test_bootstrap_runtime_address_alias(self):
        """``runtime_address`` is accepted as an alias for ``runtime_url``."""
        bootstrap = {
            "participant_id": "agent-addr",
            "session_id": "sess-addr",
            "mode": "macp.mode.decision.v1",
            "runtime_address": "runtime.local:50052",
            "auth": {"agent_id": "agent-addr"},
            "secure": False,
            "allow_insecure": True,
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(bootstrap, f)
            path = f.name
        try:
            p = from_bootstrap(path)
            assert p._client.target == "runtime.local:50052"
        finally:
            os.unlink(path)

    def test_bootstrap_with_initiator_config(self):
        """Bootstrap with ``initiator`` block populates InitiatorConfig."""
        bootstrap = {
            "participant_id": "coord",
            "session_id": "sess-init",
            "mode": "macp.mode.decision.v1",
            "auth": {"agent_id": "coord"},
            "participants": ["coord", "alice"],
            "secure": False,
            "allow_insecure": True,
            "initiator": {
                "session_start": {
                    "intent": "pick a plan",
                    "participants": ["coord", "alice", "bob"],
                    "ttl_ms": 120000,
                },
                "kickoff": {
                    "message_type": "Proposal",
                    "payload": {
                        "proposal_id": "p1",
                        "option": "deploy-v3",
                        "rationale": "tests green",
                    },
                },
            },
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(bootstrap, f)
            path = f.name
        try:
            p = from_bootstrap(path)
            cfg = p._initiator_config
            assert cfg is not None
            assert cfg.intent == "pick a plan"
            assert cfg.participants == ["coord", "alice", "bob"]
            assert cfg.ttl_ms == 120000
            assert cfg.kickoff_message_type == "Proposal"
            assert cfg.kickoff_payload["proposal_id"] == "p1"
        finally:
            os.unlink(path)

    def test_bootstrap_initiator_extensions_decoded_from_base64(self):
        """SDK-PY-1: ``initiator.session_start.extensions`` (a proto
        ``map<string, bytes>`` encoded as base64 per proto-JSON canonical
        form) must be decoded back into ``dict[str, bytes]`` on the
        resulting ``InitiatorConfig``."""
        import base64

        aitp_bytes = b"\x01\x02\x03aitp"
        ctxm_bytes = b"ctxm-provenance"
        bootstrap = {
            "participant_id": "coord",
            "session_id": "sess-ext",
            "mode": "macp.mode.decision.v1",
            "auth": {"agent_id": "coord"},
            "secure": False,
            "allow_insecure": True,
            "initiator": {
                "session_start": {
                    "intent": "with-ext",
                    "participants": ["coord"],
                    "ttl_ms": 60000,
                    "extensions": {
                        "aitp.v1": base64.b64encode(aitp_bytes).decode("ascii"),
                        "ctxm.v1": base64.b64encode(ctxm_bytes).decode("ascii"),
                    },
                },
            },
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(bootstrap, f)
            path = f.name
        try:
            p = from_bootstrap(path)
            cfg = p._initiator_config
            assert cfg is not None
            assert cfg.extensions == {
                "aitp.v1": aitp_bytes,
                "ctxm.v1": ctxm_bytes,
            }
        finally:
            os.unlink(path)

    def test_bootstrap_initiator_extensions_absent_defaults_empty(self):
        """A bootstrap without an ``extensions`` key must yield an empty
        dict so ``_emit_initiator_envelopes()`` does not send a nil map."""
        bootstrap = {
            "participant_id": "coord",
            "session_id": "sess-noext",
            "mode": "macp.mode.decision.v1",
            "auth": {"agent_id": "coord"},
            "secure": False,
            "allow_insecure": True,
            "initiator": {
                "session_start": {
                    "intent": "no-ext",
                    "participants": ["coord"],
                    "ttl_ms": 60000,
                },
            },
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(bootstrap, f)
            path = f.name
        try:
            p = from_bootstrap(path)
            cfg = p._initiator_config
            assert cfg is not None
            assert cfg.extensions == {}
        finally:
            os.unlink(path)

    def test_emit_initiator_envelopes_passes_extensions(self):
        """SDK-PY-1: ``_emit_initiator_envelopes`` must forward
        ``InitiatorConfig.extensions`` to ``ParticipantActions.start_session``
        so the bytes survive onto the SessionStart envelope."""
        from macp_sdk.agent.runner import InitiatorConfig

        client = _make_mock_client()
        cfg = InitiatorConfig(
            intent="i",
            participants=["coord", "alice"],
            ttl_ms=30000,
            context_id="ctx-123",
            extensions={"aitp.v1": b"\xde\xad"},
        )
        p = Participant(
            participant_id="coord",
            session_id="sess-emit",
            mode=MODE_DECISION,
            client=client,
            auth=client.auth,
            participants=["coord", "alice"],
            initiator_config=cfg,
        )
        p._actions = MagicMock(spec=ParticipantActions)

        p._emit_initiator_envelopes()

        p._actions.start_session.assert_called_once()
        kwargs = p._actions.start_session.call_args.kwargs
        assert kwargs["extensions"] == {"aitp.v1": b"\xde\xad"}
        assert kwargs["context_id"] == "ctx-123"

    def test_emit_initiator_envelopes_empty_extensions_sent_as_none(self):
        """An empty ``extensions`` dict should be normalised to ``None``
        so the builder emits an empty proto map (default), not a
        sentinel value the runtime would have to parse specially."""
        from macp_sdk.agent.runner import InitiatorConfig

        client = _make_mock_client()
        cfg = InitiatorConfig(
            intent="i",
            participants=["coord"],
            ttl_ms=30000,
        )
        p = Participant(
            participant_id="coord",
            session_id="sess-empty-ext",
            mode=MODE_DECISION,
            client=client,
            auth=client.auth,
            participants=["coord"],
            initiator_config=cfg,
        )
        p._actions = MagicMock(spec=ParticipantActions)

        p._emit_initiator_envelopes()

        assert p._actions.start_session.call_args.kwargs["extensions"] is None

    def test_bootstrap_cancel_callback_binds_to_participant_stop(self):
        """When the bootstrap JSON carries a ``cancel_callback`` block
        (RFC-0001 §7.2 Option A), ``from_bootstrap`` must spin up the
        HTTP server and wire it to ``participant.stop()`` so a POST
        from the control-plane tears the event loop down cleanly.
        Before 0.2.4 every agent had to hand-roll this."""
        import json as _json
        import urllib.request

        bootstrap = {
            "participant_id": "coord",
            "session_id": "sess-cc",
            "mode": "macp.mode.decision.v1",
            "auth": {"agent_id": "coord"},
            "secure": False,
            "allow_insecure": True,
            "cancel_callback": {
                "host": "127.0.0.1",
                "port": 0,  # let the OS pick — we read the real port off the server
                "path": "/cancel",
            },
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            _json.dump(bootstrap, f)
            path = f.name
        try:
            p = from_bootstrap(path)
            server = p._cancel_callback_server
            assert server is not None, "cancel_callback server not attached"

            # POST and verify the participant stops.
            host, port = server.address
            req = urllib.request.Request(
                f"http://{host}:{port}/cancel",
                data=b'{"runId":"r","reason":"test"}',
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            resp = urllib.request.urlopen(req, timeout=2.0)
            assert resp.status == 202
            assert p.is_stopped, "participant.stop() was not called"
            # After stop the server is closed and detached.
            assert p._cancel_callback_server is None
        finally:
            os.unlink(path)

    def test_bootstrap_without_cancel_callback_leaves_server_none(self):
        bootstrap = {
            "participant_id": "coord",
            "session_id": "sess-no-cc",
            "mode": "macp.mode.decision.v1",
            "auth": {"agent_id": "coord"},
            "secure": False,
            "allow_insecure": True,
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(bootstrap, f)
            path = f.name
        try:
            p = from_bootstrap(path)
            assert p._cancel_callback_server is None
        finally:
            os.unlink(path)

    def test_bootstrap_without_initiator_has_no_config(self):
        """Non-initiator bootstrap has ``initiator_config=None``."""
        bootstrap = {
            "participant_id": "alice",
            "session_id": "sess-non",
            "mode": "macp.mode.decision.v1",
            "auth": {"agent_id": "alice"},
            "secure": False,
            "allow_insecure": True,
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(bootstrap, f)
            path = f.name
        try:
            p = from_bootstrap(path)
            assert p._initiator_config is None
        finally:
            os.unlink(path)
