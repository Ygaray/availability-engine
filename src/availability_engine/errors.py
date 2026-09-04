"""Domain exceptions.

Every constructor accepts only non-sensitive identifiers (`resource_id`,
`hold_id`) and never accepts or stores a payload argument, so no exception
message can ever carry consumer payload contents (Security Domain, T-01-01).

Every exception is a subclass of `AvailabilityEngineError`, which exposes a
`.reason_code` from the closed `ReasonCode` enum (D-03/HOLD-08) — a consumer
can `except AvailabilityEngineError` to catch any domain rejection, or
inspect `.reason_code` to branch without string-matching the exception type.
"""

from __future__ import annotations

from availability_engine.contracts import ReasonCode
from availability_engine.core.intervals import Interval


class AvailabilityEngineError(Exception):
    """Common base for every domain rejection this engine raises."""

    reason_code: ReasonCode


class CapacityExhaustedError(AvailabilityEngineError):
    """Raised when a hold is requested but the resource's capacity is full."""

    reason_code = ReasonCode.CAPACITY_EXHAUSTED

    def __init__(self, resource_id: str, slot: Interval) -> None:
        self.resource_id = resource_id
        self.slot = slot
        super().__init__(f"capacity exhausted for resource {resource_id!r}")


class OutsideHoursError(AvailabilityEngineError):
    """Raised when a hold is requested outside the resource's operating hours."""

    reason_code = ReasonCode.OUTSIDE_HOURS

    def __init__(self, resource_id: str, slot: Interval) -> None:
        self.resource_id = resource_id
        self.slot = slot
        super().__init__(f"slot outside operating hours for resource {resource_id!r}")


class HoldExpiredError(AvailabilityEngineError):
    """Raised when confirming a hold whose TTL has elapsed."""

    reason_code = ReasonCode.HOLD_EXPIRED

    def __init__(self, hold_id: str) -> None:
        self.hold_id = hold_id
        super().__init__(f"hold {hold_id!r} has expired")


class HoldNotFoundError(AvailabilityEngineError):
    """Raised when a hold_id does not refer to a currently active hold."""

    reason_code = ReasonCode.NOT_FOUND

    def __init__(self, hold_id: str) -> None:
        self.hold_id = hold_id
        super().__init__(f"hold {hold_id!r} not found")


class ResourceNotFoundError(AvailabilityEngineError):
    """Raised when a resource_id does not refer to a defined Resource."""

    # Shares ReasonCode.NOT_FOUND with HoldNotFoundError rather than a
    # distinct resource_not_found variant — HOLD-08's requirement text lists
    # exactly one generic not_found code, and the enum is closed (D-03), so
    # adding a second not_found variant later would itself be breaking.
    reason_code = ReasonCode.NOT_FOUND

    def __init__(self, resource_id: str) -> None:
        self.resource_id = resource_id
        super().__init__(f"resource {resource_id!r} not found")
