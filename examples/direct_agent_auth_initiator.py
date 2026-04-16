"""Initiator agent — direct-agent-auth flow (Q-13).

This is the reference template for the agent that *opens* a session under
the topology described in ``docs/guides/direct-agent-auth.md``. It:

    1. reads the pre-allocated ``session_id`` from bootstrap,
    2. authenticates to the runtime directly with its own Bearer token,
    3. emits SessionStart (unary ``Send``),
    4. opens a bidi stream for subsequent events,
    5. emits the first mode-specific envelope (a ``Proposal`` here).

In production, the orchestrator hands the agent a bootstrap JSON file; for
this example we inline the values so you can run it against a local
runtime started with::

    MACP_ALLOW_INSECURE=1 MACP_ALLOW_DEV_SENDER_HEADER=1 cargo run

See ``examples/direct_agent_auth_observer.py`` for the non-initiator side.
"""

from __future__ import annotations

import os

from macp_sdk import (
    AuthConfig,
    DecisionSession,
    MacpClient,
    new_session_id,
)


def main() -> None:
    # ── Bootstrap values (supplied by orchestrator in production) ─────────
    session_id = os.environ.get("MACP_SESSION_ID") or new_session_id()
    participant_id = "coordinator"
    bearer_token = os.environ.get("MACP_INITIATOR_BEARER")

    # ── AuthConfig: Bearer when provided, dev-header otherwise (local only).
    if bearer_token:
        auth = AuthConfig.for_bearer(bearer_token, expected_sender=participant_id)
    else:
        auth = AuthConfig.for_dev_agent(participant_id)

    client = MacpClient(
        target=os.environ.get("MACP_RUNTIME_TARGET", "127.0.0.1:50051"),
        allow_insecure=True,  # local dev — production uses TLS by default
        auth=auth,
    )
    try:
        init = client.initialize()
        print(f"connected: {init.runtime_info.name}")

        # ── 1. SessionStart (unary) — runtime binds initiator_sender to us.
        session = DecisionSession(client, session_id=session_id, auth=auth)
        ack = session.start(
            intent="pick a deployment plan",
            participants=[participant_id, "alice", "bob"],
            ttl_ms=60_000,
        )
        assert ack.ok
        print(f"session opened: {session.session_id}")

        # ── 2. Open bidi stream for subsequent events.
        stream = session.open_stream()
        try:
            # ── 3. Emit the kickoff envelope (first mode-specific Send).
            session.propose("p1", "deploy-v2.1", rationale="tests passed")
            print("kickoff proposal emitted — non-initiators can now react.")

            # In a real agent this would be the event-loop:
            #   for envelope in stream.responses(): ...
            # We just commit to end the demo.
            session.commit(
                action="deployment.approved",
                authority_scope="release",
                reason="demo complete",
            )
            print("committed.")
        finally:
            stream.close()
    finally:
        client.close()


if __name__ == "__main__":
    main()
