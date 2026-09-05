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

from collections.abc import Generator
from datetime import UTC, datetime, time, timedelta

import pytest
from chatbot_engine.availability.port import AvailabilityPort, HoldConflict
from chatbot_engine.availability.testing.contract import AvailabilityContractSuite
from examples.chatbot_adapter import AvailabilityEngineAdapter

from availability_engine.contracts import LocalInterval, Resource, Weekday
from availability_engine.storage.memory import InMemoryStore
from availability_engine.sync import SyncAvailabilityEngine


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


@pytest.fixture
def pipe_resource_id_port() -> Generator[AvailabilityPort, None, None]:
    """WR-03 regression fixture: a resource_id containing the old raw
    delimiter character, "|" -- a plausible domain-injected id, since the
    engine names zero domain concepts and imposes no character
    restriction on Resource.id."""
    store = InMemoryStore()
    engine = SyncAvailabilityEngine(store)
    engine.define_resource(
        Resource(
            id="table|1",
            capacity=1,
            operating_hours={
                weekday: [LocalInterval(start=time(0, 0), end=time(23, 59))]
                for weekday in Weekday
            },
            buffer=timedelta(minutes=0),
            timezone="America/Chicago",
            slot_duration=timedelta(minutes=30),
        )
    )
    adapter = AvailabilityEngineAdapter(engine)
    try:
        yield adapter
    finally:
        engine.close()


def test_place_hold_succeeds_for_resource_id_containing_pipe_character(
    pipe_resource_id_port: AvailabilityPort,
) -> None:
    """WR-03 regression: a resource_id containing "|" must not corrupt
    slot_id encoding/decoding -- place_hold must succeed against the
    correct resource_id/start/end rather than raising an unhandled
    ValueError (or unpacking to the wrong fields) from a naive
    "|"-delimited split()."""
    window = (datetime.now(UTC), datetime.now(UTC) + timedelta(days=2))
    slots = pipe_resource_id_port.query_availability("table|1", window, party_size=1)
    assert slots, "expected at least one available slot in the query window"
    slot = slots[0]
    assert slot.resource_id == "table|1"

    hold = pipe_resource_id_port.place_hold(
        slot.slot_id, ttl_seconds=300, idempotency_key="pipe-id-key"
    )
    assert hold.slot_id == slot.slot_id
