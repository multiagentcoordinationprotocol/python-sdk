# Authentication

All authenticated operations require an `AuthConfig`. The SDK supports two authentication methods, matching the runtime's security model.

## Development: dev agent headers

```python
from macp_sdk import AuthConfig

auth = AuthConfig.for_dev_agent("my-agent")
```

This sends the `x-macp-agent-id: my-agent` header. The runtime uses this as the sender identity.

!!! warning "Development only"
    Dev agent headers require the runtime to be started with `MACP_ALLOW_DEV_SENDER_HEADER=1`. **Never use in production** — the header is trivially spoofable.

## Production: bearer tokens

```python
auth = AuthConfig.for_bearer("tok-abc123", sender_hint="my-agent")
```

This sends the `Authorization: Bearer tok-abc123` header. The runtime validates the token against its token configuration and maps it to a sender identity.

### Token configuration (runtime side)

The runtime accepts token configuration via `MACP_AUTH_TOKENS_JSON` or `MACP_AUTH_TOKENS_FILE`:

```json
{
  "tokens": [
    {
      "token": "tok-coordinator-secret",
      "sender": "coordinator",
      "allowed_modes": ["macp.mode.decision.v1", "macp.mode.quorum.v1"],
      "can_start_sessions": true,
      "max_open_sessions": 25,
      "can_manage_mode_registry": true
    },
    {
      "token": "tok-alice-secret",
      "sender": "alice",
      "can_start_sessions": false,
      "max_open_sessions": 10
    }
  ]
}
```

| Field | Description |
|-------|-------------|
| `sender` | Identity assigned to this token |
| `allowed_modes` | Restrict to specific modes (omit for all) |
| `can_start_sessions` | Whether this token can initiate sessions |
| `max_open_sessions` | Concurrent OPEN session limit |
| `can_manage_mode_registry` | Whether this token can register/unregister modes |

## Sender identity

The `sender` field on envelopes is **runtime-derived**, not self-asserted:

```python
# SDK sets sender from AuthConfig
auth = AuthConfig.for_dev_agent("alice")
# auth.sender → "alice"

# When sending a message, the SDK populates the envelope's sender field
session.vote("p1", "approve", sender="alice")
# The runtime validates that the authenticated identity matches "alice"
```

If you attempt to send with a sender that doesn't match your credentials, the runtime rejects with `UNAUTHENTICATED`.

### The `sender_hint` field

`sender_hint` is the identity the SDK uses when constructing envelopes. For dev agents, it's automatically set to the `agent_id`. For bearer tokens, you should provide it explicitly:

```python
# Bearer token — sender_hint tells the SDK which sender to use in envelopes
auth = AuthConfig.for_bearer("tok-123", sender_hint="alice")
assert auth.sender == "alice"

# Without sender_hint, auth.sender is None and you must specify sender explicitly
auth = AuthConfig.for_bearer("tok-123")
session.vote("p1", "approve", sender="alice")  # must specify sender
```

## Per-operation auth overrides

Session helpers accept an `auth=` parameter on each method to override the session/client default:

```python
coordinator_auth = AuthConfig.for_dev_agent("coordinator")
alice_auth = AuthConfig.for_dev_agent("alice")
bob_auth = AuthConfig.for_dev_agent("bob")

# Session uses coordinator auth by default
session = DecisionSession(client, auth=coordinator_auth)
session.start(intent="...", participants=["coordinator", "alice", "bob"], ttl_ms=60_000)

# Override auth for specific messages
session.vote("p1", "approve", sender="alice", auth=alice_auth)
session.vote("p1", "approve", sender="bob", auth=bob_auth)

# Commitment uses the session's default (coordinator)
session.commit(action="approved", authority_scope="release", reason="majority")
```

This pattern is essential for multi-agent sessions where different participants use different credentials.

## Client-level vs. session-level auth

```python
# Client-level: used as fallback for all operations
client = MacpClient(target="...", auth=coordinator_auth)

# Session-level: overrides client auth for this session
session = DecisionSession(client, auth=special_auth)

# Method-level: overrides both client and session auth
session.vote("p1", "approve", auth=alice_auth)
```

Priority: **method-level > session-level > client-level**

## TLS configuration

For production deployments with TLS:

```python
client = MacpClient(
    target="runtime.example.com:50051",
    secure=True,
    root_certificates=open("ca.pem", "rb").read(),  # CA certificate
    auth=AuthConfig.for_bearer("tok-prod-123", sender_hint="my-agent"),
)
```

The runtime must be configured with `MACP_TLS_CERT_PATH` and `MACP_TLS_KEY_PATH`.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `MacpSdkError: this operation requires auth` | No auth configured | Pass `auth=` to client, session, or method |
| `MacpAckError: UNAUTHENTICATED` | Token invalid or expired | Check token in runtime config |
| `MacpAckError: FORBIDDEN` | Sender not authorized for this mode | Check `allowed_modes` in token config |
| `MacpAckError: FORBIDDEN` on Commitment | Sender is not the session initiator | Only the initiator can commit |
| Spoofed sender rejected | Sender doesn't match auth identity | Use correct auth for each participant |

## API Reference

::: macp_sdk.auth.AuthConfig
