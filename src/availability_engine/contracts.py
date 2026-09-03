"""Public boundary types — the product surface a consumer codes against.

Every datetime crossing this boundary is Pydantic-validated as UTC-aware
(`UtcDatetime`). Internal engine math uses `core.intervals.Interval`
(stdlib dataclass) instead — see `core/intervals.py`.
"""

import zoneinfo
from datetime import UTC, datetime, time, timedelta
from enum import IntEnum, StrEnum
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
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


class Resource(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    capacity: Annotated[int, Field(ge=1)]  # MODEL-01
    operating_hours: dict[Weekday, list[LocalInterval]]  # MODEL-02, D-03
    buffer: timedelta = Field(default=timedelta(0))  # MODEL-03
    timezone: str  # MODEL-04
    slot_duration: timedelta  # GRID-01 — required, no default (see plan design note)

    @field_validator("timezone")
    @classmethod
    def _validate_iana(cls, v: str) -> str:
        try:
            zoneinfo.ZoneInfo(v)
        except zoneinfo.ZoneInfoNotFoundError as exc:
            raise ValueError(f"not a valid IANA timezone: {v!r}") from exc
        return v


class SlotStatus(StrEnum):
    AVAILABLE = "available"
    BOOKED = "booked"
    # NOTE: Phase 2 (AVAIL-02) needs the two-list available/booked split with an
    # explicit capacity_remaining int per FEATURES.md's capacity-shape gray area.
    # Phase 1 ships a single flat list with a `status` field per slot as the
    # walking-skeleton minimum — field names chosen so Phase 2 can extend
    # additively (add capacity_remaining as a new field) rather than restructure.


class PublicSlot(BaseModel):
    model_config = ConfigDict(frozen=True)
    start: UtcDatetime
    end: UtcDatetime
    resource_id: str
    status: SlotStatus


class AvailabilityResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    resource_id: str
    slots: list[PublicSlot]


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
