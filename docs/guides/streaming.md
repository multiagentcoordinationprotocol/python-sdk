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
    secure=False,
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
- A background thread reads from the gRPC stream and puts responses in an incoming queue
- `read()` and `responses()` pull from the incoming queue
- `close()` signals the background thread to stop

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

- **No late-attach handshake**: `StreamSession` does not support joining an already-running session mid-flight. You can only observe envelopes that are accepted after the stream is opened.
- **Single session per stream**: Each stream is scoped to one session. Open multiple streams for multiple sessions.
- **Background thread**: `MacpStream` uses a daemon thread. Ensure you call `close()` for clean shutdown, or use the client as a context manager.
