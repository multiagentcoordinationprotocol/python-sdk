"""Tests for signal_type validation."""

from __future__ import annotations

import pytest

from macp_sdk.envelope import build_signal_payload
from macp_sdk.errors import MacpSessionError


class TestSignalValidation:
    def test_empty_type_with_data_raises(self):
        with pytest.raises(MacpSessionError, match="signal_type must be non-empty"):
            build_signal_payload(signal_type="", data=b"some data")

    def test_whitespace_type_with_data_raises(self):
        with pytest.raises(MacpSessionError, match="signal_type must be non-empty"):
            build_signal_payload(signal_type="  ", data=b"some data")

    def test_empty_type_without_data_ok(self):
        # No data means empty signal_type is allowed
        payload = build_signal_payload(signal_type="")
        assert payload.signal_type == ""

    def test_non_empty_type_with_data_ok(self):
        payload = build_signal_payload(signal_type="heartbeat", data=b"ping")
        assert payload.signal_type == "heartbeat"
        assert payload.data == b"ping"
