"""Fixed-duration slot grid generation over a free fragment (GRID-01)."""

from datetime import timedelta

from availability_engine.core.intervals import Interval


def grid_slots(
    fragment: Interval,
    slot_duration: timedelta,
    buffer: timedelta,
    duration: timedelta | None = None,
) -> list[Interval]:
    """Lay out consecutive candidate slots starting at `fragment.start`.
    Discards any slot whose `end` would exceed `fragment.end`.

    Two parameter combinations (D-04):

    - `duration is None` (default, v1-identical): each candidate is
      `slot_duration` long, and the cursor advances by
      `slot_duration + buffer` (buffer owned by the preceding slot's
      trailing edge, per Open Question #1's resolution). Behavior is
      byte-for-byte unchanged from the pre-D-04 signature.
    - `duration` is given: each candidate is `duration` long instead of
      `slot_duration`, but the cursor still advances by `slot_duration`
      alone (buffer enforcement for the duration-aware path moves to the
      busy-interval-padding mechanism at the engine/store layer, D-03, not
      this grid step). When `duration > slot_duration`, consecutive
      candidates overlap by design — grid generation does not resolve
      conflicts; capacity/hold logic downstream does.

    Raises `ValueError` if `duration` is given and is not positive.
    """
    if duration is not None and duration <= timedelta(0):
        raise ValueError("duration must be positive")

    slots: list[Interval] = []
    cursor = fragment.start
    effective_duration = duration if duration is not None else slot_duration
    step = slot_duration + buffer if duration is None else slot_duration

    while True:
        slot_end = cursor + effective_duration
        if slot_end > fragment.end:
            break
        slots.append(Interval(start=cursor, end=slot_end))
        cursor = cursor + step

    return slots
