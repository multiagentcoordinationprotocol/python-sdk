from __future__ import annotations

from macp.modes.handoff.v1 import handoff_pb2

from macp_sdk.constants import MODE_HANDOFF
from macp_sdk.handoff import HandoffProjection
from tests.conftest import make_envelope


class TestHandoffProjection:
    def _proj(self) -> HandoffProjection:
        return HandoffProjection()

    def test_initial_state(self):
        p = self._proj()
        assert p.phase == "Pending"
        assert p.active_offer() is None
        assert not p.is_committed

    def test_offer(self):
        p = self._proj()
        p.apply_envelope(
            make_envelope(
                MODE_HANDOFF,
                "HandoffOffer",
                handoff_pb2.HandoffOfferPayload(
                    handoff_id="h1",
                    target_participant="bob",
                    scope="service-xyz",
                    reason="rotating",
                ),
                sender="alice",
            )
        )
        assert "h1" in p.handoffs
        assert p.handoffs["h1"].status == "offered"
        assert p.active_offer() is not None
        assert p.phase == "OfferPending"

    def test_context(self):
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
                "HandoffContext",
                handoff_pb2.HandoffContextPayload(
                    handoff_id="h1",
                    content_type="application/json",
                    context=b'{"key":"val"}',
                ),
                sender="alice",
            )
        )
        handoff = p.get_handoff("h1")
        assert handoff is not None
        assert handoff.context_content_type == "application/json"
        assert handoff.status == "context_sent"
        assert p.phase == "ContextSharing"

    def test_accept(self):
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
        assert p.is_accepted("h1")
        assert not p.is_declined("h1")
        assert p.phase == "Accepted"

    def test_decline(self):
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
                "HandoffDecline",
                handoff_pb2.HandoffDeclinePayload(
                    handoff_id="h1", declined_by="bob", reason="not ready"
                ),
                sender="bob",
            )
        )
        assert p.is_declined("h1")
        assert not p.is_accepted("h1")
        assert p.phase == "Declined"
