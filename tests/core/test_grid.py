"""`grid_slots()` basic and buffer-application unit tests (GRID-01, MODEL-03).
"""

from datetime import UTC, datetime, timedelta

import pytest

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


def test_grid_slots_duration_overrides_step() -> None:
    # D-04: a 2-hour fragment, 30-minute step (via slot_duration), 60-minute
    # query duration. Candidates are stepped by the 30-minute slot_duration,
    # NOT by the 60-minute duration, so each candidate's own end is
    # start + 60min and consecutive candidates overlap by 30 minutes. This
    # is expected: grid generation produces overlapping candidates by
    # design when duration > step; capacity/conflict resolution downstream
    # is what prevents two overlapping candidates from both being held.
    fragment = Interval(start=_FRAGMENT_START, end=_FRAGMENT_START + timedelta(hours=2))

    slots = grid_slots(
        fragment,
        slot_duration=timedelta(minutes=30),
        buffer=timedelta(0),
        duration=timedelta(minutes=60),
    )

    assert len(slots) == 3
    assert all(slot.end - slot.start == timedelta(minutes=60) for slot in slots)
    assert slots[0].start == _FRAGMENT_START
    assert slots[1].start == _FRAGMENT_START + timedelta(minutes=30)
    assert slots[2].start == _FRAGMENT_START + timedelta(minutes=60)


def test_grid_slots_nonpositive_duration_rejected() -> None:
    fragment = Interval(start=_FRAGMENT_START, end=_FRAGMENT_END)

    for bad_duration in (timedelta(0), timedelta(minutes=-5)):
        with pytest.raises(ValueError):
            grid_slots(
                fragment,
                slot_duration=timedelta(minutes=30),
                buffer=timedelta(0),
                duration=bad_duration,
            )
