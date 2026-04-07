"""Tests for handoff context after accept and has_accepted_offer."""

from __future__ import annotations

from macp.modes.handoff.v1 import handoff_pb2

from macp_sdk.constants import MODE_HANDOFF
from macp_sdk.handoff import HandoffProjection
from tests.conftest import make_envelope


class TestHandoffContextAfterAccept:
    def _proj(self) -> HandoffProjection:
        return HandoffProjection()

    def test_has_accepted_offer_initial(self):
        p = self._proj()
        assert p.has_accepted_offer is False

    def test_has_accepted_offer_after_accept(self):
        p = self._proj()
        p.apply_envelope(
            make_envelope(
                MODE_HANDOFF,
                "HandoffOffer",
                handoff_pb2.HandoffOfferPayload(handoff_id="h1", target_participant="bob"),
                sender="alice",
            )
        )
        p.apply_envelope(
            make_envelope(
                MODE_HANDOFF,
                "HandoffAccept",
                handoff_pb2.HandoffAcceptPayload(handoff_id="h1", accepted_by="bob"),
                sender="bob",
            )
        )
        assert p.has_accepted_offer is True

    def test_context_after_accept_is_tracked(self):
        """Per RFC-MACP-0010 section 2.1, HandoffContext after accept is permitted."""
        p = self._proj()
        p.apply_envelope(
            make_envelope(
                MODE_HANDOFF,
                "HandoffOffer",
                handoff_pb2.HandoffOfferPayload(handoff_id="h1", target_participant="bob"),
                sender="alice",
            )
        )
        p.apply_envelope(
            make_envelope(
                MODE_HANDOFF,
                "HandoffAccept",
                handoff_pb2.HandoffAcceptPayload(handoff_id="h1", accepted_by="bob"),
                sender="bob",
            )
        )
        # Now send context after accept — should work
        p.apply_envelope(
            make_envelope(
                MODE_HANDOFF,
                "HandoffContext",
                handoff_pb2.HandoffContextPayload(
                    handoff_id="h1",
                    content_type="text/plain",
                    context=b"supplementary docs",
                ),
                sender="alice",
            )
        )
        assert len(p.contexts["h1"]) == 1
        assert p.contexts["h1"][0].context == b"supplementary docs"

    def test_any_participant_can_send_context(self):
        """Any declared participant can send context, not just the initiator."""
        p = self._proj()
        p.apply_envelope(
            make_envelope(
                MODE_HANDOFF,
                "HandoffOffer",
                handoff_pb2.HandoffOfferPayload(handoff_id="h1", target_participant="bob"),
                sender="alice",
            )
        )
        # Bob (target) sends context
        p.apply_envelope(
            make_envelope(
                MODE_HANDOFF,
                "HandoffContext",
                handoff_pb2.HandoffContextPayload(
                    handoff_id="h1",
                    content_type="text/plain",
                    context=b"from target",
                ),
                sender="bob",
            )
        )
        assert len(p.contexts["h1"]) == 1
        assert p.contexts["h1"][0].sender == "bob"
