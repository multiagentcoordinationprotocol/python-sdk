# Core Protocol Concepts

This page covers the foundational MACP protocol concepts that every SDK user should understand. For the full specification, see the [MACP RFCs](https://github.com/multiagentcoordinationprotocol/multiagentcoordinationprotocol).

## Two planes of communication

MACP separates all agent communication into two planes:

**Ambient Plane (Signals)** — Continuous, non-binding informational messages. Signals do not create sessions, mutate state, or produce binding outcomes. They may be handled ephemerally.

**Coordination Plane (Sessions)** — Bounded, explicit, binding coordination. All coordination that produces binding outcomes must happen inside a session. Sessions have monotonic lifecycles, durable history, and replay-capable transcripts.

This separation is the core invariant: *binding coordination MUST occur inside explicit, bounded Coordination Sessions*.

## The Envelope

Every MACP message is wrapped in a canonical `Envelope`:

```
Envelope {
    macp_version        # Protocol version ("1.0")
    mode                # Mode URI (empty for Signals)
    message_type        # "SessionStart", "Proposal", "Vote", etc.
    message_id          # Unique within session (idempotency key)
    session_id          # Empty for Signals, non-empty for coordinated
    sender              # Authenticated identity (runtime-derived, never self-asserted)
    timestamp_unix_ms   # Informational only
    payload             # Mode-specific protobuf bytes
}
```

The SDK's `build_envelope()` and session helpers handle envelope construction automatically.

### Idempotency

Each envelope carries a unique `message_id`. The runtime deduplicates by `message_id` within a session — sending the same `message_id` twice is a no-op (returns `duplicate=true` in the Ack). This is the foundation for safe retries.

### Sender identity

The `sender` field is **derived from the authenticated identity**, not self-asserted. The runtime overwrites any `sender` value with the identity from the auth credentials. The SDK resolves the sender through `AuthConfig.sender`.

## Session lifecycle

Sessions follow a monotonic finite state machine:

```
[*] ──→ OPEN ──→ RESOLVED ──→ [*]
              ╲
               ──→ EXPIRED ──→ [*]
```

| State | Meaning |
|-------|---------|
| **OPEN** | Session is active, accepting messages |
| **RESOLVED** | Terminal — a Commitment was accepted |
| **EXPIRED** | Terminal — TTL elapsed, or session was cancelled |

**Key rules:**

- Transitions are **monotonic** — a session can only move forward, never backward
- Only **Commitment** messages resolve a session (OPEN → RESOLVED)
- TTL expiry and `CancelSession` produce EXPIRED
- The runtime enforces these transitions; the SDK tracks them via projections

### SessionStart

Every session begins with a `SessionStart` envelope that declares:

- **intent** — Human-readable purpose
- **participants** — Declared agent IDs
- **ttl_ms** — Maximum session lifetime (1ms–86,400,000ms / 24h)
- **mode_version** — Which mode semantics to use
- **configuration_version** — Which execution profile
- **policy_version** — Which governance rules (optional)
- **context** — Optional bound context (bytes/string/JSON)
- **roots** — Optional coordination boundaries

These versions are **bound at SessionStart** and cannot change during the session.

### Commitment

A Commitment is the terminal message that resolves a session:

```python
session.commit(
    action="deployment.approved",
    authority_scope="release-management",
    reason="2/3 majority approved",
)
```

Commitments carry an `authority_scope` that declares under what authority the action is taken. Only authorized senders can emit Commitments (typically the session initiator or coordinator).

## Accepted-history discipline

All accepted envelopes form an **immutable, append-only session log** — the authoritative ordered transcript. This enables:

- **Replay** for determinism verification
- **Audit** for compliance
- **Debugging** for post-incident analysis
- **State reconstruction** from transcript

!!! note "Acceptance order is authoritative order"
    In a distributed system with multiple senders, "order" means **runtime acceptance order**, not sender transmission order. The runtime defines a single, durable, replayable total order per session.

## Capabilities and initialization

Before any session work, the client negotiates capabilities with the runtime via the `Initialize` RPC:

```python
response = client.initialize()
# response.selected_protocol_version  → "1.0"
# response.capabilities               → what the runtime supports
# response.supported_modes             → available mode URIs
```

The SDK advertises standard capabilities during initialization. The runtime responds with its supported features, including which modes are available.

## Error model

The runtime returns structured errors with RFC-defined codes:

| Code | HTTP | When |
|------|------|------|
| `UNAUTHENTICATED` | 401 | Authentication failed |
| `FORBIDDEN` | 403 | Not authorized for this session/message |
| `SESSION_NOT_FOUND` | 404 | Session doesn't exist |
| `SESSION_NOT_OPEN` | 409 | Session is RESOLVED or EXPIRED |
| `DUPLICATE_MESSAGE` | 409 | `message_id` already accepted |
| `INVALID_ENVELOPE` | 400 | Envelope validation failed |
| `MODE_NOT_SUPPORTED` | 400 | Mode/version not available |
| `PAYLOAD_TOO_LARGE` | 413 | Exceeds size limits (default 1MB) |
| `RATE_LIMITED` | 429 | Too many requests |
| `INTERNAL_ERROR` | 500 | Unrecoverable runtime error |

The SDK maps these to Python exceptions:

```python
from macp_sdk import MacpAckError, MacpTransportError

try:
    session.vote("p1", "approve", sender="alice")
except MacpAckError as e:
    print(e.failure.code)     # "FORBIDDEN"
    print(e.failure.message)  # "sender not authorized"
except MacpTransportError as e:
    print(e)                  # gRPC transport failure
```

!!! tip "Retryable errors"
    `RATE_LIMITED` and `INTERNAL_ERROR` are transient — use `retry_send()` with a `RetryPolicy` for automatic exponential backoff. `FORBIDDEN`, `SESSION_NOT_FOUND`, and `INVALID_ENVELOPE` are permanent and should not be retried.

## Discovery

The runtime exposes discovery RPCs for introspection:

```python
# List available standard modes
modes = client.list_modes()
for desc in modes.modes:
    print(f"{desc.mode} — {desc.title}")

# Get runtime/agent manifest
manifest = client.get_manifest()
print(manifest.manifest.description)

# List registered extension modes
ext_modes = client.list_ext_modes()

# List coordination roots
roots = client.list_roots()
```

These are useful for building dynamic orchestrators that adapt to the runtime's capabilities.
