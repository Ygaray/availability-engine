"""Proves D-02/D-03/PKG-03: the example adapter satisfies the consumer's
`AvailabilityContractSuite` end to end against the real engine.

`TestChatbotConformance` has no test methods of its own — all 9 are
inherited from the shared suite. `test_place_hold_retry_after_confirm_*`
below is an additional, adapter-specific regression test (CR-01): the
inherited suite's own `port` fixture uses a capacity=1 resource, which
cannot exercise the capacity>1 double-hold bug (a confirmed Booking on a
capacity=1 resource always leaves zero remaining capacity, so the buggy
fix's "fall through to a fresh capacity check" path happened to always
raise there too).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from chatbot_engine.availability.port import AvailabilityPort, HoldConflict
from chatbot_engine.availability.testing.contract import AvailabilityContractSuite


class TestChatbotConformance(AvailabilityContractSuite):
    pass


def test_place_hold_retry_after_confirm_raises_hold_conflict_on_capacity2(
    capacity2_port: AvailabilityPort,
) -> None:
    """CR-01 regression: a place_hold retry with the same idempotency_key,
    made AFTER the original hold was confirmed into a booking, must raise
    HoldConflict -- even when the resource's capacity (2) still has room
    for the fresh capacity re-check to otherwise succeed and silently mint
    a second, independent Hold on the same slot."""
    window = (datetime.now(UTC), datetime.now(UTC) + timedelta(days=2))
    slots = capacity2_port.query_availability(
        "conformance-resource-capacity2", window, party_size=1
    )
    assert slots, "expected at least one available slot in the query window"
    slot = slots[0]

    idempotency_key = "retry-after-confirm-capacity2"
    hold = capacity2_port.place_hold(
        slot.slot_id, ttl_seconds=300, idempotency_key=idempotency_key
    )
    capacity2_port.confirm_hold(hold.hold_id, details={"order_id": "abc-123"})

    with pytest.raises(HoldConflict):
        capacity2_port.place_hold(
            slot.slot_id, ttl_seconds=300, idempotency_key=idempotency_key
        )
