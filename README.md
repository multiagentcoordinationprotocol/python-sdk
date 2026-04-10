# macp-sdk-python

Python SDK for the [MACP](https://github.com/multiagentcoordinationprotocol/multiagentcoordinationprotocol) Rust runtime.

## What this package does

- Connects to the Rust runtime over gRPC
- Provides typed session helpers for all 5 standard coordination modes
- Maintains in-process projections for local state tracking
- Supports envelope builders, retry helpers, and structured logging

## Important runtime boundary

This SDK **calls** the Rust runtime. The runtime does not call into this Python package.
If you need runtime-driven business logic, run a Python agent/orchestrator as a separate process and let it communicate with the runtime over MACP transport.

## Install

```bash
pip install macp-sdk-python
```

## Quick start

```python
from macp_sdk import AuthConfig, MacpClient, DecisionSession

client = MacpClient(
    target="127.0.0.1:50051",
    secure=False,
    auth=AuthConfig.for_dev_agent("coordinator"),
)

session = DecisionSession(client)
session.start(
    intent="pick a deployment plan",
    participants=["alice", "bob"],
    ttl_ms=60_000,
)
session.propose("p1", "deploy v2.1", rationale="tests passed")
session.evaluate("p1", "approve", confidence=0.94, reason="low risk", sender="alice")
session.vote("p1", "approve", reason="ship it", sender="bob")

winner = session.decision_projection.majority_winner()
if winner and not session.decision_projection.has_blocking_objection(winner):
    session.commit(
        action="deployment.approved",
        authority_scope="release-management",
        reason=f"winner={winner}",
    )
```

## Supported modes

| Mode | Session Helper | Projection | Example |
|------|---------------|------------|---------|
| Decision | `DecisionSession` | `DecisionProjection` | `examples/decision_smoke.py` |
| Proposal | `ProposalSession` | `ProposalProjection` | `examples/proposal_negotiation.py` |
| Task | `TaskSession` | `TaskProjection` | `examples/task_delegation.py` |
| Handoff | `HandoffSession` | `HandoffProjection` | `examples/handoff_escalation.py` |
| Quorum | `QuorumSession` | `QuorumProjection` | `examples/quorum_approval.py` |

## Development

```bash
# Setup
make setup              # pip install -e ".[dev,docs]"

# Quality
make lint               # ruff check
make fmt                # ruff format
make typecheck          # mypy strict
make test               # unit tests
make test-all           # lint + typecheck + all tests
make coverage           # coverage report

# Build
make build              # sdist + wheel

# Proto definitions (provided by macp-proto package)
make dev-link-protos    # link local proto package for development
```

For local development against the runtime:

```bash
export MACP_ALLOW_INSECURE=1
export MACP_ALLOW_DEV_SENDER_HEADER=1
cargo run   # in the runtime repo
```

## Documentation

Full docs available in `docs/` — build with `mkdocs serve` after `make setup`.

## Architecture boundary

This SDK is a **thin typed client library**. It provides:
- Typed state models and action builders
- Session helpers (`propose()`, `vote()`, `commit()`)
- Local state projections (because `GetSession` returns metadata only)

Business logic — voting rules, AI decision heuristics, policy enforcement — belongs in the orchestrator/agent layer **above** the SDK.

## Known runtime limitations

- `GetSession` returns metadata only (not mode state/transcript) — hence the local projection pattern
- `StreamSession` has no late-attach handshake for already-running sessions
- Business policy (majority, quorum, veto) belongs in your orchestrator/policy layer
