"""Domain exceptions.

Every constructor accepts only non-sensitive identifiers (`resource_id`,
`hold_id`) and never accepts or stores a payload argument, so no exception
message can ever carry consumer payload contents (Security Domain, T-01-01).
"""

from __future__ import annotations

from typing import Any


class CapacityExhaustedError(Exception):
    """Raised when a hold is requested but the resource's capacity is full."""

    def __init__(self, resource_id: str, slot: Any) -> None:
        self.resource_id = resource_id
        self.slot = slot
        super().__init__(f"capacity exhausted for resource {resource_id!r}")


class HoldExpiredError(Exception):
    """Raised when confirming a hold whose TTL has elapsed."""

    def __init__(self, hold_id: str) -> None:
        self.hold_id = hold_id
        super().__init__(f"hold {hold_id!r} has expired")


class HoldNotFoundError(Exception):
    """Raised when a hold_id does not refer to a currently active hold."""

    def __init__(self, hold_id: str) -> None:
        self.hold_id = hold_id
        super().__init__(f"hold {hold_id!r} not found")


class ResourceNotFoundError(Exception):
    """Raised when a resource_id does not refer to a defined Resource."""

    def __init__(self, resource_id: str) -> None:
        self.resource_id = resource_id
        super().__init__(f"resource {resource_id!r} not found")
