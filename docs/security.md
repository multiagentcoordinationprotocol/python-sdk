# Security

MACP defines a comprehensive security model. This page covers the security guarantees, authentication mechanisms, and operational practices relevant to SDK users.

## Core security principles

1. **Transport security** — All communication must be encrypted (TLS 1.2+ required, TLS 1.3 recommended)
2. **Authentication** — All agents must be identified (mTLS, JWT, or OAuth2/OIDC)
3. **Authorization** — Access control is enforced per session and per message type
4. **Isolation** — Sessions are isolated; cross-session injection is prevented
5. **Replay protection** — `message_id` deduplication within sessions
6. **DoS mitigation** — Rate limiting, payload size limits, and resource quotas

## Authentication methods

### Bearer tokens (production)

```python
from macp_sdk import AuthConfig, MacpClient

auth = AuthConfig.for_bearer("tok-abc123", expected_sender="my-agent")
client = MacpClient(target="runtime:50051", auth=auth)  # secure=True by default
```

SDK 0.2.0+ defaults `secure=True` and enforces `expected_sender` client-side,
preventing plaintext channels and spoofed-sender envelopes from ever leaving
the process.

The runtime validates the token and maps it to a sender identity with specific permissions:

- **allowed_modes** — Which modes this token can access
- **can_start_sessions** — Whether this token can initiate sessions
- **max_open_sessions** — Maximum concurrent OPEN sessions
- **can_manage_mode_registry** — Whether this token can register/unregister extension modes

### Dev-agent bearer auth (development only)

```python
auth = AuthConfig.for_dev_agent("my-agent")
```

Sends `Authorization: Bearer my-agent`. The runtime's `dev_authenticate`
fallback binds the bearer token value verbatim as the authenticated
sender. **Never use in production** — the token is unencrypted and
trivially spoofable.

### mTLS (mutual TLS)

For agent-to-agent authentication with client certificates:

```python
client = MacpClient(
    target="runtime:50051",
    root_certificates=open("ca.pem", "rb").read(),
    auth=AuthConfig.for_bearer("tok-123", expected_sender="my-agent"),
)
```

The runtime can be configured with `MACP_TLS_CERT_PATH` and `MACP_TLS_KEY_PATH` for server-side TLS.

## Authorization model

### Sender identity

The `sender` field on envelopes is **runtime-derived**, never self-asserted. The runtime overwrites any sender value with the identity from the authentication credentials. Attempting to spoof a sender results in `UNAUTHENTICATED`.

### Per-mode authorization

Tokens can restrict which modes an agent can access:

```json
{
  "token": "agent-token-123",
  "sender": "alice",
  "allowed_modes": ["macp.mode.decision.v1", "macp.mode.task.v1"],
  "can_start_sessions": true,
  "max_open_sessions": 10
}
```

Attempting to send a message in a mode not in `allowed_modes` results in `FORBIDDEN`.

### Per-message authorization

Each mode defines who can send which message types:

| Mode | Message | Who can send |
|------|---------|-------------|
| Decision | Commitment | Session initiator / coordinator |
| Decision | Proposal, Vote | Any declared participant |
| Task | TaskRequest | Session initiator |
| Task | TaskAccept/Complete/Fail | Assigned worker |
| Handoff | HandoffAccept/Decline | Target participant only |
| Quorum | Commitment | Authorized coordinator |

The runtime enforces these rules. The SDK will receive `MacpAckError` with code `FORBIDDEN` if authorization fails.

## Session isolation

- Sessions are identified by cryptographically strong, unguessable `session_id` values (UUID v4/v7)
- The runtime rejects any attempt to reference a session the requesting agent is not authorized for
- Cross-session message injection is prevented at the protocol level
- In multi-tenant deployments, `session_id` values are scoped to tenant namespaces

## Replay protection

- Each message carries a unique `message_id`
- The runtime deduplicates by `message_id` within a session
- Sending the same `message_id` twice returns `duplicate=true` without side effects
- This makes retries safe: the SDK's `retry_send()` can safely retry on transient failures

## Rate limiting

The runtime enforces per-sender rate limits:

| Limit | Default | Environment variable |
|-------|---------|---------------------|
| SessionStart per minute | 60 | `MACP_SESSION_START_LIMIT_PER_MINUTE` |
| Messages per minute | 600 | `MACP_MESSAGE_LIMIT_PER_MINUTE` |
| Max payload size | 1 MB | `MACP_MAX_PAYLOAD_BYTES` |

When rate-limited, the SDK receives `MacpAckError` with code `RATE_LIMITED`. Use `retry_send()` with the default `RetryPolicy` to handle this automatically:

```python
from macp_sdk import RetryPolicy, retry_send

policy = RetryPolicy(
    max_retries=5,
    backoff_base=0.5,
    retryable_codes=frozenset({"RATE_LIMITED", "INTERNAL_ERROR"}),
)
retry_send(client, envelope, policy=policy, auth=auth)
```

## Audit logging

The runtime logs security-relevant events. SDK users should be aware that these actions are recorded:

- Session creation (who, when, mode, participants)
- Authentication failures
- Authorization denials
- Terminal transitions and outcomes
- Duplicate message rejections
- Cancellation requests
- Rate-limit violations

## Production checklist

- [ ] Use TLS (default since SDK 0.2.0) — never pass `allow_insecure=True` in prod
- [ ] Set `expected_sender` on every `AuthConfig.for_bearer` call so sender spoofing fails fast (`MacpIdentityMismatchError`)
- [ ] Use bearer tokens, not dev agent headers
- [ ] Scope tokens to minimum required modes (`allowed_modes`)
- [ ] Set `max_open_sessions` to prevent resource exhaustion
- [ ] Configure rate limits appropriate to your workload
- [ ] Set `MACP_MAX_PAYLOAD_BYTES` to prevent payload amplification
- [ ] Enable audit logging in the runtime
- [ ] Rotate tokens periodically
- [ ] Monitor for `UNAUTHENTICATED` and `FORBIDDEN` errors
