"""Proposal mode example: buyer/seller negotiation.

Demonstrates: propose, counter_propose, accept, reject, commit.
Requires a running MACP runtime on localhost:50051.
"""

from macp_sdk import AuthConfig, MacpClient
from macp_sdk.proposal import ProposalSession

# --- Create clients for each participant ---
coordinator = MacpClient(
    target="127.0.0.1:50051",
    allow_insecure=True,  # local dev only; production requires TLS (RFC-0006 §3)
    auth=AuthConfig.for_dev_agent("coordinator"),
)
buyer = AuthConfig.for_dev_agent("buyer")
seller = AuthConfig.for_dev_agent("seller")

# --- Start a proposal session ---
session = ProposalSession(coordinator, auth=AuthConfig.for_dev_agent("coordinator"))
session.start(
    intent="negotiate service contract terms",
    participants=["coordinator", "buyer", "seller"],
    ttl_ms=60_000,
)

# --- Seller makes initial proposal ---
session.propose("p1", "Standard Package", summary="$100k/year, basic SLA", sender="seller")

# --- Buyer counter-proposes ---
session.counter_propose(
    "p2",
    "p1",
    "Enhanced Package",
    summary="$80k/year, enhanced SLA",
    sender="buyer",
)

# --- Seller accepts the counter-proposal ---
session.accept("p2", reason="terms acceptable", sender="seller")
# --- Buyer also accepts ---
session.accept("p2", reason="agreed", sender="buyer")

# --- Check convergence and commit ---
proj = session.proposal_projection
if proj.accepted_proposal() == "p2":
    session.commit(
        action="contract.agreed",
        authority_scope="procurement",
        reason="Both parties accepted proposal p2",
    )
    print(f"Negotiation resolved: {proj.commitment.action}")  # type: ignore[union-attr]
else:
    print("No convergence reached")

coordinator.close()
