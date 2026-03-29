from __future__ import annotations

import time
from dataclasses import dataclass, field

from macp.v1 import envelope_pb2

from ._logging import logger
from .auth import AuthConfig
from .errors import MacpRetryError, MacpTransportError

# Re-export for convenience
__all__ = ["RetryPolicy", "retry_send"]


@dataclass(frozen=True)
class RetryPolicy:
    """Configuration for retry behaviour on transient failures."""

    max_retries: int = 3
    backoff_base: float = 0.1
    backoff_max: float = 2.0
    retryable_codes: frozenset[str] = field(
        default_factory=lambda: frozenset({"RATE_LIMITED", "INTERNAL_ERROR"})
    )


def retry_send(
    client: object,
    envelope: envelope_pb2.Envelope,
    *,
    policy: RetryPolicy | None = None,
    auth: AuthConfig | None = None,
) -> object:
    """Send an envelope with retries on transient failures.

    Uses the client's ``send`` method. On ``MacpTransportError`` or retryable
    NACK codes, backs off and retries up to ``policy.max_retries`` times.
    """
    from .errors import MacpAckError  # avoid circular

    pol = policy or RetryPolicy()
    last_error: Exception | None = None

    for attempt in range(1 + pol.max_retries):
        try:
            return client.send(envelope, auth=auth)  # type: ignore[union-attr]
        except MacpTransportError as exc:
            last_error = exc
        except MacpAckError as exc:
            if exc.failure.code not in pol.retryable_codes:
                raise
            last_error = exc

        if attempt < pol.max_retries:
            delay = min(pol.backoff_base * (2**attempt), pol.backoff_max)
            logger.debug(
                "retry attempt=%d delay=%.2fs error=%s",
                attempt + 1,
                delay,
                last_error,
            )
            time.sleep(delay)

    raise MacpRetryError(f"retries exhausted after {pol.max_retries} attempts") from last_error
