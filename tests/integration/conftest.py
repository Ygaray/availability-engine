"""Fixtures the consumer's `AvailabilityContractSuite` requires (D-02).

Declared here (never in the shared suite itself, per its own docstring): a
fresh `port` per test, plus `one_available_slot` / `no_available_slot` /
`held_slot` seeded against it.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator
from datetime import UTC, datetime, time, timedelta

import pytest
from chatbot_engine.availability.port import AvailabilityPort, Hold, Slot
from examples.chatbot_adapter import AvailabilityEngineAdapter

from availability_engine.contracts import LocalInterval, Resource, Weekday
from availability_engine.storage.memory import InMemoryStore
from availability_engine.sync import SyncAvailabilityEngine

_RESOURCE_ID = "conformance-resource"
# CR-01 regression fixture: distinct id + capacity>1, so a confirmed
# Booking never occupies the resource's ENTIRE capacity for a slot --
# exactly the case where the old idempotency-after-confirm bug's fresh
# capacity re-check would silently succeed (and mint a duplicate Hold)
# instead of raising CapacityExhaustedError, letting the buggy fix
# escape detection. `_RESOURCE_ID` (capacity=1) can never exercise this
# because a confirmed Booking always leaves it at zero remaining
# capacity.
_CAPACITY2_RESOURCE_ID = "conformance-resource-capacity2"


@pytest.fixture
def port() -> Generator[AvailabilityPort, None, None]:
    store = InMemoryStore()
    engine = SyncAvailabilityEngine(store)
    engine.define_resource(
        Resource(
            id=_RESOURCE_ID,
            capacity=1,
            # All seven weekdays, near-full-day hours, so the fixture
            # produces multiple 30-minute slots regardless of which
            # calendar day the suite actually runs on.
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


@pytest.fixture
def capacity2_port() -> Generator[AvailabilityPort, None, None]:
    """CR-01 regression fixture: same shape as `port`, but capacity=2 so
    a confirmed Booking never exhausts the slot's capacity on its own."""
    store = InMemoryStore()
    engine = SyncAvailabilityEngine(store)
    engine.define_resource(
        Resource(
            id=_CAPACITY2_RESOURCE_ID,
            capacity=2,
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


@pytest.fixture
def _query_window() -> tuple[datetime, datetime]:
    # Snapshotted once per test so every fixture that queries availability
    # sees the exact same window (no drift between two datetime.now() calls).
    now = datetime.now(UTC)
    return now, now + timedelta(days=2)


@pytest.fixture
def one_available_slot(
    port: AvailabilityPort, _query_window: tuple[datetime, datetime]
) -> Slot:
    slots = port.query_availability(_RESOURCE_ID, _query_window, party_size=1)
    assert slots, "expected at least one available slot in the query window"
    return slots[0]


@pytest.fixture
def no_available_slot(
    port: AvailabilityPort,
    _query_window: tuple[datetime, datetime],
    one_available_slot: Slot,
) -> Slot:
    slots = port.query_availability(_RESOURCE_ID, _query_window, party_size=1)
    candidates = [s for s in slots if s.slot_id != one_available_slot.slot_id]
    assert candidates, "expected a second distinct slot in the query window"
    target = candidates[0]
    # Pre-exhaust this specific slot's one unit of capacity -- distinct
    # from one_available_slot's own slot, so it stays untouched.
    port.place_hold(target.slot_id, ttl_seconds=300, idempotency_key=str(uuid.uuid4()))
    return target


@pytest.fixture
def held_slot(port: AvailabilityPort, one_available_slot: Slot) -> Hold:
    return port.place_hold(
        one_available_slot.slot_id, ttl_seconds=300, idempotency_key=str(uuid.uuid4())
    )
