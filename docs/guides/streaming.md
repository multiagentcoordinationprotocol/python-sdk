# Streaming

The SDK supports several streaming patterns for real-time coordination.

## Bidirectional session streaming (MacpStream)

`MacpStream` provides bidirectional communication with the runtime via the `StreamSession` RPC. Messages sent through a stream are processed by the runtime and accepted envelopes are broadcast back.

```python
from macp_sdk import MacpClient, AuthConfig
from macp_sdk.envelope import build_envelope, serialize_message
from macp.modes.decision.v1 import decision_pb2

client = MacpClient(
    target="127.0.0.1:50051",
    allow_insecure=True,  # local dev only — TLS is default
    auth=AuthConfig.for_dev_agent("coordinator"),
)

# Open a stream
stream = client.open_stream()

# Send an envelope through the stream
payload = decision_pb2.VotePayload(proposal_id="p1", vote="approve")
envelope = build_envelope(
    mode="macp.mode.decision.v1",
    message_type="Vote",
    session_id="my-session",
    sender="coordinator",
    payload=serialize_message(payload),
)
stream.send(envelope)

# Read accepted envelopes (blocking)
response = stream.read(timeout=5.0)
if response is not None:
    print(f"Accepted: {response.message_type} from {response.sender}")

# Iterate over all responses
for envelope in stream.responses(timeout=10.0):
    print(f"Got: {envelope.message_type}")

# Close when done
stream.close()
```

### How it works

`MacpStream` uses a background thread and queue-based message pump:

- `send()` puts envelopes in an outgoing queue
- `send_subscribe(session_id, after_sequence=0)` enqueues a *subscribe-only*
  frame (RFC-MACP-0006-A1) — see [Session subscription + replay](#session-subscription--replay)
- A background thread reads from the gRPC stream and puts responses in an incoming queue
- `read()` and `responses()` pull from the incoming queue
- `close()` signals the background thread to stop

### Session subscription + replay

Per **RFC-MACP-0006-A1**, a `StreamSessionRequest` can carry *either* an
envelope *or* a subscribe-only frame with `subscribe_session_id` (and
optional `after_sequence`). When the runtime receives a subscribe frame:

1. It replays every accepted envelope for the session, starting from
   `after_sequence` (0 = from the very first envelope), in acceptance
   order.
2. It then switches the stream to live broadcast.

This is how a non-initiator agent that connects *after* the initiator
has already sent `SessionStart` + the first `Proposal` still receives
both envelopes. `GrpcTransportAdapter` (in
`macp_sdk.agent.transports`) calls `send_subscribe` automatically right
after opening the stream, so participants built on top of the agent
framework get the correct behaviour for free — regardless of spawn
order or connection timing.

```python
# Late-joining observer (non-initiator)
stream = client.open_stream()
stream.send_subscribe("sess-xyz")               # replay from start, then live
for envelope in stream.responses(timeout=5.0):
    ...

# Reconnecting observer that already saw envelopes up to sequence 17
stream = client.open_stream()
stream.send_subscribe("sess-xyz", after_sequence=17)  # resume from 18 onward
```

Subscribe-only frames do not carry a sender envelope and leave
`envelope` empty on the request. The caller must still be
authenticated as a declared participant (or observer identity) for the
session.

### Session helpers + streaming

Session helpers use unary `Send` RPCs by default. To combine session helpers with streaming:

```python
session = DecisionSession(client, session_id="my-session")
session.start(intent="...", participants=["a", "b"], ttl_ms=60_000)

# Open a stream to observe accepted envelopes
stream = session.open_stream()

# Send via session helpers (unary RPCs)
session.propose("p1", "option-a")

# Read the accepted envelope from the stream
response = stream.read(timeout=5.0)
```

## Server-streaming: WatchModeRegistry

Monitor mode registry changes in real time:

```python
for event in client.watch_mode_registry(timeout=60.0):
    print(f"Registry changed: {event}")
```

This is useful for dynamic orchestrators that need to adapt when new modes are registered or existing ones are removed.

## Server-streaming: WatchRoots

Monitor coordination root changes:

```python
for event in client.watch_roots(timeout=60.0):
    print(f"Roots changed: {event}")
```

## Known limitations

- **Single session per stream**: Each stream is scoped to one session. Open multiple streams for multiple sessions.
- **Background thread**: `MacpStream` uses a daemon thread. Ensure you call `close()` for clean shutdown, or use the client as a context manager.

> Late attach *is* supported since SDK 0.2.3 / `macp-proto 0.1.2` via
> the subscribe frame described above. Earlier versions only saw
> envelopes accepted after the stream was opened.
