"""Non-initiator / observer agent — direct-agent-auth flow (Q-13).

Companion to ``direct_agent_auth_initiator.py``. A non-initiator never
calls ``session.start()``; it opens a bidi stream on a known
``session_id`` (pre-allocated by the orchestrator) and reacts to events
as the initiator's SessionStart + action envelopes arrive.

Run the initiator first (or in parallel) so a session exists for this
observer to attach to. Use the same ``MACP_SESSION_ID`` env var in both
processes::

    MACP_SESSION_ID=$(python -c "import uuid; print(uuid.uuid4())")
    MACP_SESSION_ID=$MACP_SESSION_ID python examples/direct_agent_auth_initiator.py &
    MACP_SESSION_ID=$MACP_SESSION_ID python examples/direct_agent_auth_observer.py
"""

from __future__ import annotations

import os

from macp_sdk import AuthConfig, DecisionSession, MacpClient


def main() -> None:
    session_id = os.environ["MACP_SESSION_ID"]
    participant_id = "alice"
    bearer_token = os.environ.get("MACP_ALICE_BEARER")

    if bearer_token:
        auth = AuthConfig.for_bearer(bearer_token, expected_sender=participant_id)
    else:
        auth = AuthConfig.for_dev_agent(participant_id)

    client = MacpClient(
        target=os.environ.get("MACP_RUNTIME_TARGET", "127.0.0.1:50051"),
        allow_insecure=True,  # local dev; production uses TLS by default
        auth=auth,
    )
    try:
        client.initialize()

        session = DecisionSession(client, session_id=session_id, auth=auth)
        stream = session.open_stream()
        try:
            print(f"observer {participant_id} attached to {session_id}")
            for envelope in stream.responses(timeout=5.0):
                print(f"  ← {envelope.message_type} from {envelope.sender}")
                if envelope.message_type == "Proposal":
                    ack = session.evaluate(
                        "p1",
                        "APPROVE",
                        confidence=0.9,
                        reason="looks good",
                    )
                    print(f"    → Evaluation ack.ok={ack.ok}")
                elif envelope.message_type == "Commitment":
                    print("  session committed — exiting observer loop.")
                    return
        finally:
            stream.close()
    finally:
        client.close()


if __name__ == "__main__":
    main()
