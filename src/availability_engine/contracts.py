"""Public boundary types — the product surface a consumer codes against.

Every datetime crossing this boundary is Pydantic-validated as UTC-aware
(`UtcDatetime`). Internal engine math uses `core.intervals.Interval`
(stdlib dataclass) instead — see `core/intervals.py`.
"""

import zoneinfo
from datetime import UTC, datetime, time, timedelta
from enum import IntEnum, StrEnum
from itertools import pairwise
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)


def _require_utc(value: datetime) -> datetime:
    # AwareDatetime already guarantees tzinfo is set (raises "timezone_aware"
    # ValidationError otherwise) — this validator narrows further to UTC only.
    if value.utcoffset() != UTC.utcoffset(None):
        raise ValueError("datetime must be UTC (offset 00:00)")
    return value


UtcDatetime = Annotated[AwareDatetime, AfterValidator(_require_utc)]


class Weekday(IntEnum):
    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6


class LocalInterval(BaseModel):
    """A half-open [start, end) window in a resource's own local wall-clock time.

    D-03: list-of-half-open-intervals per weekday (not a single open/close pair)
    to physically accommodate overnight/split shifts, even though correct
    midnight-crossing GENERATION is deferred to Phase 2.
    """

    model_config = ConfigDict(frozen=True)
    start: time
    end: time
    # NOTE: v1 does not validate end > start here — Phase 2's midnight-hours
    # decision explicitly tolerates end < start for overnight shifts (per
    # v1.0-DECISION-MAP.md Phase 2 [midnight-hours]). Do not add a same-day-only
    # validator in this phase; it would need reverting in Phase 2.
    #
    # WR-02: end == start IS rejected, though. `time.py::localize_operating_hours`
    # treats any `end <= start` as the overnight sentinel and anchors `end` on
    # the following calendar day — for `end == start` that silently produces a
    # full 24-hour window, the most permissive possible outcome for a
    # scheduling engine, which is almost never what a caller who wrote
    # `start=end` (e.g. zeroing out a disabled day) actually intended. Fail
    # loudly here instead of guessing.
    @field_validator("end")
    @classmethod
    def _reject_zero_length(cls, v: time, info: ValidationInfo) -> time:
        start = info.data.get("start")
        if start is not None and v == start:
            raise ValueError(
                "LocalInterval.end must differ from start "
                "(use disjoint start/end, or omit the weekday for 'no hours')"
            )
        return v


class Resource(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    capacity: Annotated[int, Field(ge=1)]  # MODEL-01
    operating_hours: dict[Weekday, list[LocalInterval]]  # MODEL-02, D-03
    # ge=timedelta(0): a negative buffer could make grid_slots' step
    # (slot_duration + buffer) non-positive, hanging the grid-generation loop
    # (CR-02).
    buffer: Annotated[timedelta, Field(ge=timedelta(0))] = Field(
        default=timedelta(0)
    )  # MODEL-03
    timezone: str  # MODEL-04
    # gt=timedelta(0): grid_slots' loop only terminates because cursor
    # strictly advances past fragment.end each iteration; slot_duration <= 0
    # (combined with a non-negative buffer) would make the step size
    # non-positive and hang the loop forever (CR-02).
    slot_duration: Annotated[
        timedelta, Field(gt=timedelta(0))
    ]  # GRID-01 — required, no default (see plan design note)

    @field_validator("timezone")
    @classmethod
    def _validate_iana(cls, v: str) -> str:
        try:
            zoneinfo.ZoneInfo(v)
        except zoneinfo.ZoneInfoNotFoundError as exc:
            raise ValueError(f"not a valid IANA timezone: {v!r}") from exc
        return v

    @model_validator(mode="after")
    def _reject_overlapping_intervals(self) -> "Resource":
        # WR-01: two overlapping LocalIntervals declared for the same
        # Weekday cause free_fragments to scan (and emit) the overlapping
        # region twice, producing duplicate PublicSlots in the two-list
        # contract. Reject at construction time instead.
        for weekday, local_intervals in self.operating_hours.items():
            ranges: list[tuple[int, int]] = []
            for local_interval in local_intervals:
                start_min = (
                    local_interval.start.hour * 60 + local_interval.start.minute
                )
                end_min = local_interval.end.hour * 60 + local_interval.end.minute
                # D-05 overnight sentinel (end < start, end == start already
                # rejected by LocalInterval itself): anchor end on a
                # "double day" timeline (minutes 1440-2880 == the following
                # calendar day) so overlap comparisons below stay a plain
                # half-open-interval check even across midnight.
                if end_min < start_min:
                    end_min += 24 * 60
                ranges.append((start_min, end_min))
            ranges.sort()
            for (_, prev_end), (next_start, _) in pairwise(ranges):
                if next_start < prev_end:
                    raise ValueError(
                        f"overlapping LocalIntervals declared for "
                        f"{weekday.name}: intervals must not overlap"
                    )
        return self


class SlotStatus(StrEnum):
    AVAILABLE = "available"
    BOOKED = "booked"
    # Phase 2 (D-04) split AvailabilityResult into two lists (`available`/
    # `booked`) rather than a flat `slots` list — list membership now encodes
    # status, but `status` itself is kept on PublicSlot as a shipped,
    # derivable convenience field (RESEARCH.md Pattern 1's recommendation:
    # removing it would be a separate, reversible decision, not a Phase-2
    # requirement).


class BookingStatus(StrEnum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class ReasonCode(StrEnum):
    """Closed, one-way enum (D-03) — a consumer can exhaustiveness-match on
    this. `IDEMPOTENCY_CONFLICT` is reserved: only Phase 3 raises it, but it
    is pre-included here so widening the enum later isn't required.
    """

    CAPACITY_EXHAUSTED = "capacity_exhausted"
    OUTSIDE_HOURS = "outside_hours"
    HOLD_EXPIRED = "hold_expired"
    NOT_FOUND = "not_found"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"


class PublicSlot(BaseModel):
    model_config = ConfigDict(frozen=True)
    start: UtcDatetime
    end: UtcDatetime
    resource_id: str
    status: SlotStatus
    capacity: Annotated[int, Field(ge=1)]
    remaining: Annotated[int, Field(ge=0)]


class AvailabilityResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    resource_id: str
    available: list[PublicSlot]
    booked: list[PublicSlot]


class Hold(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    resource_id: str
    slot_start: UtcDatetime
    slot_end: UtcDatetime
    expires_at: UtcDatetime


class Booking(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    resource_id: str
    slot_start: UtcDatetime
    slot_end: UtcDatetime
    payload: dict[str, Any]
    status: BookingStatus = BookingStatus.CONFIRMED
