"""`grid_slots()` basic and buffer-application unit tests (GRID-01, MODEL-03).

No production code is modified by this file.
"""

from datetime import UTC, datetime, timedelta

from availability_engine.core.grid import grid_slots
from availability_engine.core.intervals import Interval

_FRAGMENT_START = datetime(2026, 9, 7, 9, 0, tzinfo=UTC)
_FRAGMENT_END = _FRAGMENT_START + timedelta(hours=1)


def test_grid_slots_basic() -> None:
    fragment = Interval(start=_FRAGMENT_START, end=_FRAGMENT_END)

    slots = grid_slots(
        fragment, slot_duration=timedelta(minutes=30), buffer=timedelta(0)
    )

    assert len(slots) == 2
    assert all(slot.end - slot.start == timedelta(minutes=30) for slot in slots)
    # Contiguous: no gap between consecutive slots when buffer is zero.
    assert slots[0].end == slots[1].start


def test_buffer_applied() -> None:
    fragment = Interval(start=_FRAGMENT_START, end=_FRAGMENT_END)

    slots = grid_slots(
        fragment, slot_duration=timedelta(minutes=20), buffer=timedelta(minutes=10)
    )

    # A third 20-min slot would need another 30 minutes (20 + 10 buffer) past the
    # second slot's start, which doesn't fit in the remaining fragment.
    assert len(slots) == 2
    assert slots[1].start - slots[0].end == timedelta(minutes=10)
