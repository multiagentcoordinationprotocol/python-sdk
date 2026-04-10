"""High-level watcher classes wrapping raw client streaming RPCs.

Each watcher provides three consumption patterns:
- ``changes()`` / ``signals()`` — a Python iterator
- ``watch(handler)`` — blocking callback loop
- ``next_change()`` / ``next_signal()`` — pull a single item
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .auth import AuthConfig
    from .client import MacpClient


@dataclass(slots=True)
class PolicyChange:
    """A snapshot of governance policy changes from the runtime."""

    descriptors: list[Any] = field(default_factory=list)
    observed_at_unix_ms: int = 0


class ModeRegistryWatcher:
    """Watch for mode registry changes from the runtime."""

    def __init__(self, client: MacpClient, *, auth: AuthConfig | None = None) -> None:
        self._client = client
        self._auth = auth

    def changes(self) -> Iterator[Any]:
        """Yield ``WatchModeRegistryResponse`` items from the runtime stream."""
        yield from self._client.watch_mode_registry()

    def watch(self, handler: Callable[[Any], None]) -> None:
        """Block and invoke *handler* for each registry change."""
        for change in self.changes():
            handler(change)

    def next_change(self) -> Any:
        """Pull a single change from the stream and return it."""
        for change in self.changes():
            return change
        raise RuntimeError("stream ended before receiving a change")


class RootsWatcher:
    """Watch for root changes from the runtime."""

    def __init__(self, client: MacpClient, *, auth: AuthConfig | None = None) -> None:
        self._client = client
        self._auth = auth

    def changes(self) -> Iterator[Any]:
        """Yield ``WatchRootsResponse`` items from the runtime stream."""
        yield from self._client.watch_roots()

    def watch(self, handler: Callable[[Any], None]) -> None:
        """Block and invoke *handler* for each root change."""
        for change in self.changes():
            handler(change)

    def next_change(self) -> Any:
        """Pull a single change from the stream and return it."""
        for change in self.changes():
            return change
        raise RuntimeError("stream ended before receiving a change")


class SignalWatcher:
    """Watch for ambient signal envelopes from the runtime."""

    def __init__(self, client: MacpClient, *, auth: AuthConfig | None = None) -> None:
        self._client = client
        self._auth = auth

    def signals(self) -> Iterator[Any]:
        """Yield envelope objects extracted from ``WatchSignalsResponse``."""
        for response in self._client.watch_signals():
            if hasattr(response, "envelope") and response.envelope.ByteSize() > 0:
                yield response.envelope

    def watch(self, handler: Callable[[Any], None]) -> None:
        """Block and invoke *handler* for each signal envelope."""
        for envelope in self.signals():
            handler(envelope)

    def next_signal(self) -> Any:
        """Pull a single signal envelope from the stream and return it."""
        for envelope in self.signals():
            return envelope
        raise RuntimeError("stream ended before receiving a signal")


class PolicyWatcher:
    """Watch for governance policy changes from the runtime."""

    def __init__(self, client: MacpClient, *, auth: AuthConfig | None = None) -> None:
        self._client = client
        self._auth = auth

    def changes(self) -> Iterator[PolicyChange]:
        """Yield ``PolicyChange`` items from the runtime stream."""
        for response in self._client.watch_policies():
            descriptors = list(response.descriptors) if hasattr(response, "descriptors") else []
            observed = getattr(response, "observed_at_unix_ms", 0)
            yield PolicyChange(descriptors=descriptors, observed_at_unix_ms=observed)

    def watch(self, handler: Callable[[PolicyChange], None]) -> None:
        """Block and invoke *handler* for each policy change."""
        for change in self.changes():
            handler(change)

    def next_change(self) -> PolicyChange:
        """Pull a single policy change from the stream and return it."""
        for change in self.changes():
            return change
        raise RuntimeError("stream ended before receiving a policy change")
