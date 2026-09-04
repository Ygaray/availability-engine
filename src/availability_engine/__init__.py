"""availability-engine — a reusable, domain-agnostic scheduling library."""

from availability_engine.contracts import (
    AvailabilityResult,
    Booking,
    BookingStatus,
    Hold,
    LocalInterval,
    PublicSlot,
    Resource,
    SlotStatus,
    Weekday,
)
from availability_engine.engine import AvailabilityEngine
from availability_engine.errors import (
    BookingNotFoundError,
    CapacityExhaustedError,
    HoldExpiredError,
    HoldNotFoundError,
    IdempotencyConflictError,
    ResourceNotFoundError,
)
from availability_engine.storage.protocol import StorageBackend

__all__ = [
    "AvailabilityEngine",
    "AvailabilityResult",
    "Booking",
    "BookingNotFoundError",
    "BookingStatus",
    "CapacityExhaustedError",
    "Hold",
    "HoldExpiredError",
    "HoldNotFoundError",
    "IdempotencyConflictError",
    "LocalInterval",
    "PublicSlot",
    "Resource",
    "ResourceNotFoundError",
    "SlotStatus",
    "StorageBackend",
    "Weekday",
]
