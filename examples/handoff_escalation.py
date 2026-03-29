"""Handoff mode example: transferring responsibility between agents.

Demonstrates: offer, add_context, accept_handoff, commit.
Requires a running MACP runtime on localhost:50051.
"""

from macp_sdk import AuthConfig, MacpClient
from macp_sdk.handoff import HandoffSession

# --- Create client ---
client = MacpClient(
    target="127.0.0.1:50051",
    secure=False,
    auth=AuthConfig.for_dev_agent("owner-a"),
)

# --- Start handoff session ---
session = HandoffSession(client, auth=AuthConfig.for_dev_agent("owner-a"))
session.start(
    intent="transfer service-xyz ownership",
    participants=["owner-a", "owner-b"],
    ttl_ms=60_000,
)

# --- Owner-A offers the handoff ---
session.offer(
    "h1",
    "owner-b",
    scope="service-xyz",
    reason="team rotation",
)

# --- Owner-A attaches context ---
session.add_context(
    "h1",
    content_type="application/json",
    context=b'{"runbooks": "https://wiki/service-xyz", "oncall": "owner-b"}',
)

# --- Owner-B accepts ---
session.accept_handoff("h1", sender="owner-b")

# --- Commit the handoff ---
proj = session.handoff_projection
if proj.is_accepted("h1"):
    session.commit(
        action="handoff.accepted",
        authority_scope="service-ownership",
        reason="owner-b now holds service-xyz",
    )
    print("Handoff completed successfully")

client.close()
