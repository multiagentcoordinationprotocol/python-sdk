from __future__ import annotations

import json
import os

from ..auth import AuthConfig
from ..client import MacpClient
from .participant import Participant


def from_bootstrap(bootstrap_path: str | None = None) -> Participant:
    """Create a Participant from a bootstrap context file.

    The bootstrap file is a JSON document produced by the MACP hosting
    infrastructure containing the information needed to connect and
    participate in a session.

    If ``bootstrap_path`` is not provided, the ``MACP_BOOTSTRAP_FILE``
    environment variable is used.

    Expected bootstrap JSON structure::

        {
            "participant_id": "...",
            "session_id": "...",
            "mode": "macp.mode.decision.v1",
            "runtime_url": "localhost:50051",
            "auth": {
                "bearer_token": "...",   // or "agent_id": "..."
            },
            "participants": ["agent-a", "agent-b"],
            "policy_version": "policy.default",
            "secure": false
        }
    """
    path = bootstrap_path or os.environ.get("MACP_BOOTSTRAP_FILE")
    if not path:
        raise ValueError("No bootstrap path provided and MACP_BOOTSTRAP_FILE not set")

    with open(path) as f:
        ctx: dict[str, object] = json.load(f)

    participant_id = str(ctx["participant_id"])
    session_id = str(ctx["session_id"])
    mode = str(ctx["mode"])
    runtime_url = str(ctx.get("runtime_url", "localhost:50051"))
    secure = bool(ctx.get("secure", False))

    # Build auth config
    auth_data = ctx.get("auth")
    auth: AuthConfig | None = None
    if isinstance(auth_data, dict):
        bearer = auth_data.get("bearer_token")
        agent_id = auth_data.get("agent_id")
        if bearer:
            auth = AuthConfig.for_bearer(str(bearer), sender_hint=participant_id)
        elif agent_id:
            auth = AuthConfig.for_dev_agent(str(agent_id))

    # Build client
    client = MacpClient(
        target=runtime_url,
        secure=secure,
        auth=auth,
    )

    # Extract optional fields
    raw_participants = ctx.get("participants")
    participants: list[str] = []
    if isinstance(raw_participants, list):
        participants = [str(p) for p in raw_participants]

    policy_version = ctx.get("policy_version")

    return Participant(
        participant_id=participant_id,
        session_id=session_id,
        mode=mode,
        client=client,
        auth=auth,
        participants=participants,
        policy_version=str(policy_version) if policy_version else None,
    )
