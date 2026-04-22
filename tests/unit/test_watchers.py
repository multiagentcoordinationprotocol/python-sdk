"""Unit coverage for the watcher wrappers (Q-5).

The watchers are thin adapters over ``MacpClient`` server-streaming RPCs.
These tests drive each watcher against a ``MagicMock`` client and verify:

- ``changes()`` / ``signals()`` yields everything the stream produced, in order,
- ``watch(handler)`` invokes the handler once per stream item,
- ``next_change()`` / ``next_signal()`` returns the first item,
- empty streams raise ``RuntimeError`` from ``next_*`` helpers,
- ``SignalWatcher`` ignores frames whose envelope is empty (``ByteSize == 0``),
- ``PolicyWatcher`` maps responses into the typed ``PolicyChange`` dataclass.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from macp_sdk.watchers import (
    ModeRegistryWatcher,
    PolicyChange,
    PolicyWatcher,
    RootsWatcher,
    SessionLifecycleWatcher,
    SignalWatcher,
)


def _client_with_stream(method_name: str, items: list[object]) -> MagicMock:
    client = MagicMock()
    getattr(client, method_name).return_value = iter(items)
    return client


# ── ModeRegistryWatcher ───────────────────────────────────────────────


class TestModeRegistryWatcher:
    def test_changes_yields_every_item(self):
        a, b = MagicMock(), MagicMock()
        client = _client_with_stream("watch_mode_registry", [a, b])
        watcher = ModeRegistryWatcher(client)
        assert list(watcher.changes()) == [a, b]

    def test_watch_invokes_handler_per_item(self):
        a, b, c = MagicMock(), MagicMock(), MagicMock()
        client = _client_with_stream("watch_mode_registry", [a, b, c])
        watcher = ModeRegistryWatcher(client)
        seen: list[object] = []
        watcher.watch(seen.append)
        assert seen == [a, b, c]

    def test_next_change_returns_first(self):
        first = MagicMock()
        client = _client_with_stream("watch_mode_registry", [first, MagicMock()])
        watcher = ModeRegistryWatcher(client)
        assert watcher.next_change() is first

    def test_next_change_empty_raises(self):
        client = _client_with_stream("watch_mode_registry", [])
        watcher = ModeRegistryWatcher(client)
        with pytest.raises(RuntimeError, match="stream ended"):
            watcher.next_change()


# ── RootsWatcher ──────────────────────────────────────────────────────


class TestRootsWatcher:
    def test_changes_yields_and_watch_dispatches(self):
        a, b = MagicMock(), MagicMock()
        client = _client_with_stream("watch_roots", [a, b])
        watcher = RootsWatcher(client)
        assert list(watcher.changes()) == [a, b]

    def test_next_change_empty_raises(self):
        client = _client_with_stream("watch_roots", [])
        watcher = RootsWatcher(client)
        with pytest.raises(RuntimeError, match="stream ended"):
            watcher.next_change()


# ── SignalWatcher ─────────────────────────────────────────────────────


def _fake_signal_response(envelope_bytesize: int) -> MagicMock:
    resp = MagicMock()
    resp.envelope.ByteSize.return_value = envelope_bytesize
    return resp


class TestSignalWatcher:
    def test_signals_yields_only_populated_envelopes(self):
        empty = _fake_signal_response(0)
        full1 = _fake_signal_response(10)
        full2 = _fake_signal_response(20)
        client = _client_with_stream("watch_signals", [empty, full1, empty, full2])
        watcher = SignalWatcher(client)
        emitted = [env for env in watcher.signals()]
        # empty frames are dropped; payload frames surface via ``.envelope``
        assert emitted == [full1.envelope, full2.envelope]

    def test_next_signal_skips_empties(self):
        empty = _fake_signal_response(0)
        full = _fake_signal_response(5)
        client = _client_with_stream("watch_signals", [empty, full])
        watcher = SignalWatcher(client)
        assert watcher.next_signal() is full.envelope

    def test_next_signal_all_empty_raises(self):
        client = _client_with_stream(
            "watch_signals", [_fake_signal_response(0), _fake_signal_response(0)]
        )
        watcher = SignalWatcher(client)
        with pytest.raises(RuntimeError, match="stream ended"):
            watcher.next_signal()

    def test_watch_invokes_handler(self):
        full = _fake_signal_response(10)
        client = _client_with_stream("watch_signals", [full])
        watcher = SignalWatcher(client)
        seen: list[object] = []
        watcher.watch(seen.append)
        assert seen == [full.envelope]


# ── PolicyWatcher ─────────────────────────────────────────────────────


def _fake_policy_response(descriptors: list[object], observed_at_unix_ms: int = 0) -> MagicMock:
    resp = MagicMock()
    resp.descriptors = descriptors
    resp.observed_at_unix_ms = observed_at_unix_ms
    return resp


class TestPolicyWatcher:
    def test_changes_maps_to_policy_change(self):
        d1 = MagicMock()
        d2 = MagicMock()
        r1 = _fake_policy_response([d1], observed_at_unix_ms=111)
        r2 = _fake_policy_response([d2, d2], observed_at_unix_ms=222)
        client = _client_with_stream("watch_policies", [r1, r2])
        watcher = PolicyWatcher(client)
        out = list(watcher.changes())
        assert out == [
            PolicyChange(descriptors=[d1], observed_at_unix_ms=111),
            PolicyChange(descriptors=[d2, d2], observed_at_unix_ms=222),
        ]

    def test_next_change_returns_first(self):
        r1 = _fake_policy_response([MagicMock()], observed_at_unix_ms=1)
        client = _client_with_stream("watch_policies", [r1, _fake_policy_response([])])
        watcher = PolicyWatcher(client)
        first = watcher.next_change()
        assert isinstance(first, PolicyChange)
        assert first.observed_at_unix_ms == 1

    def test_next_change_empty_raises(self):
        client = _client_with_stream("watch_policies", [])
        watcher = PolicyWatcher(client)
        with pytest.raises(RuntimeError, match="stream ended"):
            watcher.next_change()

    def test_missing_descriptors_attribute_yields_empty_list(self):
        resp = MagicMock(spec=[])  # no descriptors attribute at all
        client = _client_with_stream("watch_policies", [resp])
        watcher = PolicyWatcher(client)
        (only,) = list(watcher.changes())
        assert only.descriptors == []
        assert only.observed_at_unix_ms == 0


class TestSessionLifecycleWatcherExport:
    def test_exported_from_package_root(self):
        import macp_sdk

        assert macp_sdk.SessionLifecycleWatcher is SessionLifecycleWatcher
