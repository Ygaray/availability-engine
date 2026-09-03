"""availability-engine — a reusable, domain-agnostic scheduling library."""

from availability_engine.contracts import (
    AvailabilityResult,
    Booking,
    Hold,
    LocalInterval,
    PublicSlot,
    Resource,
    SlotStatus,
    Weekday,
)
from availability_engine.engine import AvailabilityEngine
from availability_engine.errors import (
    CapacityExhaustedError,
    HoldExpiredError,
    HoldNotFoundError,
)
from availability_engine.storage.protocol import StorageBackend

__all__ = [
    "AvailabilityEngine",
    "AvailabilityResult",
    "Booking",
    "CapacityExhaustedError",
    "Hold",
    "HoldExpiredError",
    "HoldNotFoundError",
    "LocalInterval",
    "PublicSlot",
    "Resource",
    "SlotStatus",
    "StorageBackend",
    "Weekday",
]
