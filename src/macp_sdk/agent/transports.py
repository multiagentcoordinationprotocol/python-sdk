"""Transport adapters for the agent event loop.

Provides a :class:`TransportAdapter` protocol and two implementations:

- :class:`GrpcTransportAdapter` — uses a bidirectional ``StreamSession`` RPC.
- :class:`HttpTransportAdapter` — polls an HTTP endpoint for new envelopes.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any, Protocol

from .._logging import logger
from ..auth import AuthConfig
from ..client import MacpClient
from .types import IncomingMessage


class TransportAdapter(Protocol):
    """Protocol for delivering session envelopes to a Participant."""

    def start(self) -> Iterator[IncomingMessage]:
        """Yield incoming messages from the transport."""
        ...

    def stop(self) -> None:
        """Signal the transport to stop delivering messages."""
        ...


class GrpcTransportAdapter:
    """Delivers messages via the bidirectional ``StreamSession`` gRPC RPC."""

    def __init__(
        self,
        client: MacpClient,
        session_id: str,
        *,
        auth: AuthConfig | None = None,
        timeout: float | None = None,
    ) -> None:
        self._client = client
        self._session_id = session_id
        self._auth = auth
        self._timeout = timeout
        self._stream: Any = None
        self._stopped = False

    def start(self) -> Iterator[IncomingMessage]:
        """Open a stream and yield messages for the target session."""
        self._stream = self._client.open_stream(auth=self._auth, timeout=self._timeout)
        try:
            for envelope in self._stream.responses():
                if self._stopped:
                    break
                if envelope.session_id != self._session_id:
                    continue
                yield _envelope_to_message(envelope)
        finally:
            if self._stream is not None:
                self._stream.close()

    def stop(self) -> None:
        self._stopped = True
        if self._stream is not None:
            self._stream.close()


class HttpTransportAdapter:
    """Delivers messages by polling an HTTP endpoint for new envelopes.

    Expects the endpoint to return a JSON array of envelope objects at
    ``GET {base_url}/sessions/{session_id}/events?after={last_seq}``.
    """

    def __init__(
        self,
        *,
        base_url: str,
        session_id: str,
        participant_id: str,
        poll_interval_ms: int = 1000,
        auth_token: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._session_id = session_id
        self._participant_id = participant_id
        self._poll_interval = poll_interval_ms / 1000.0
        self._auth_token = auth_token
        self._stopped = False
        self._last_seq = -1

    def start(self) -> Iterator[IncomingMessage]:
        """Poll the HTTP endpoint and yield messages."""
        import urllib.request

        url = f"{self._base_url}/sessions/{self._session_id}/events"
        headers: dict[str, str] = {"Accept": "application/json"}
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"

        while not self._stopped:
            try:
                req_url = f"{url}?after={self._last_seq}"
                req = urllib.request.Request(req_url, headers=headers)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode())

                if isinstance(data, list):
                    for item in data:
                        seq = item.get("seq", self._last_seq + 1)
                        if seq > self._last_seq:
                            self._last_seq = seq
                        yield IncomingMessage(
                            message_type=item.get("message_type", ""),
                            sender=item.get("sender", ""),
                            payload=item.get("payload", {}),
                            proposal_id=item.get("proposal_id"),
                            seq=seq,
                        )
            except Exception:
                logger.debug("http poll error, retrying in %ss", self._poll_interval)

            if not self._stopped:
                time.sleep(self._poll_interval)

    def stop(self) -> None:
        self._stopped = True


def _envelope_to_message(envelope: Any) -> IncomingMessage:
    """Convert a protobuf Envelope to an IncomingMessage."""
    payload_dict: dict[str, Any] = {}
    if envelope.payload:
        try:
            payload_dict = json.loads(envelope.payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload_dict = {"_raw_bytes": envelope.payload}

    proposal_id: str | None = None
    if "proposal_id" in payload_dict:
        proposal_id = str(payload_dict["proposal_id"])

    return IncomingMessage(
        message_type=envelope.message_type,
        sender=envelope.sender,
        payload=payload_dict,
        proposal_id=proposal_id,
        raw=envelope,
    )
