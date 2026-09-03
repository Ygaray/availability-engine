"""Fixed-duration slot grid generation over a free fragment (GRID-01)."""

from datetime import timedelta

from availability_engine.core.intervals import Interval


def grid_slots(
    fragment: Interval, slot_duration: timedelta, buffer: timedelta
) -> list[Interval]:
    """Lay out consecutive `slot_duration`-length slots starting at
    `fragment.start`, advancing each next slot's start by
    `slot_duration + buffer` (buffer owned by the preceding slot's trailing
    edge, per Open Question #1's resolution). Discards any slot whose `end`
    would exceed `fragment.end`.
    """
    slots: list[Interval] = []
    cursor = fragment.start
    step = slot_duration + buffer

    while True:
        slot_end = cursor + slot_duration
        if slot_end > fragment.end:
            break
        slots.append(Interval(start=cursor, end=slot_end))
        cursor = cursor + step

    return slots
