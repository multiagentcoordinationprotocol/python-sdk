# Determinism and Replay

MACP provides formal determinism guarantees that enable reliable session replay, audit verification, and distributed state reconstruction. Understanding these guarantees is essential for building robust multi-agent systems.

## Structural replay integrity (Core guarantee)

MACP Core guarantees that replaying identical accepted envelope sequences under identical:

- `macp_version`
- Mode identifier and mode version
- `configuration_version`
- `policy_version`

will reproduce **identical state transitions** (OPEN → RESOLVED or OPEN → EXPIRED).

This is the baseline guarantee: the session lifecycle is deterministic regardless of mode.

## Determinism classes

Each mode declares a determinism class that specifies what additional guarantees it provides:

### `semantic-deterministic`

**Modes:** Decision, Proposal, Quorum

Same accepted history → same semantic outcome. The mode's logic is fully determined by the envelope sequence. No time-dependent logic beyond TTL, no external I/O.

```
replay(same envelopes) → same proposals, same votes, same commitment
```

This is the strongest guarantee. If you replay a Decision session's transcript, you will get the same winner with the same vote counts.

### `structural-only`

**Modes:** Task

Core replay is preserved (state transitions are deterministic), but semantic outcomes are **not guaranteed**. The Task mode coordinates external execution that may produce different results.

```
replay(same envelopes) → same session lifecycle, but output may differ
```

The Commitment documents the *intended* outcome, but the actual task execution is external to MACP.

### `context-frozen`

**Modes:** Handoff

Determinism depends on the exact bound context at SessionStart. Same messages + same frozen context = same outcome, but the frozen context must be reproduced exactly.

```
replay(same envelopes + same context) → same handoff result
```

### `non-deterministic`

No guarantees beyond structural. Modes that call external APIs with unpredictable results or use randomness. Replay may produce different outcomes.

## Version binding

Sessions bind three versions at `SessionStart` that **cannot change** during the session:

| Version | Purpose |
|---------|---------|
| `mode_version` | Which mode semantics apply |
| `configuration_version` | Which execution profile is active |
| `policy_version` | Which governance rules apply |

This ensures that replaying a session uses the same rules that applied when the session was live. Different versions create different sessions.

```python
# Version binding happens automatically in session helpers:
session = DecisionSession(
    client,
    mode_version="1.0.0",
    configuration_version="org-2025.q4",
    policy_version="procurement-v3",
)
```

## External side effects

When modes trigger actions beyond the session boundary (deploying code, sending emails, transferring funds), MACP defines patterns to preserve determinism:

### Pattern 1: Plan then execute

The session produces a Commitment with an execution plan. External execution happens *after* the session resolves, using idempotency keys to prevent duplicate execution.

```python
session.commit(
    action="deployment.approved",
    authority_scope="release",
    reason="approved with idempotency_key=deploy-v2.1-20250329",
)
# External system uses the idempotency key to prevent double-deploy
```

### Pattern 2: Log external results

Side-effect results are recorded as accepted session messages. On replay, the logged results are used instead of re-executing the external call.

### Pattern 3: Idempotent external transactions

External systems accept transaction IDs and guarantee that repeated attempts with the same ID produce no additional side effects.

## Testing determinism

You can verify replay correctness by recording a session transcript and replaying it:

```python
# Record the transcript during a session
transcript = session.projection.transcript

# Later, replay against a new projection
from macp_sdk.projections import DecisionProjection
replay = DecisionProjection()
for envelope in transcript:
    replay.apply_envelope(envelope)

# Verify same outcome
assert replay.majority_winner() == original_winner
assert replay.is_committed == original_committed
```

For modes with `semantic-deterministic` class, the replayed projection will always match the original.
