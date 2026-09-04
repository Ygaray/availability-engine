# Phase 3: Idempotency & Cancellation - Pattern Map

**Mapped:** 2026-09-04
**Files analyzed:** 6 (all modified, no new files this phase)
**Analogs found:** 6 / 6 (self-referential — every touched file extends its own existing pattern)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|----------------|
| `src/availability_engine/storage/memory.py` | storage (in-memory backend) | CRUD + event-driven (lock-guarded check-and-write) | itself — `place_hold`/`confirm_hold`/`get_active_entries` (same file) | exact — extend existing lock-guarded methods, add `cancel_booking` sibling to `release_hold` |
| `src/availability_engine/storage/protocol.py` | interface/config (Protocol contract) | request-response (method signature contract) | itself — `place_hold`/`confirm_hold`/`release_hold` signatures | exact — add `cancel_booking` following `release_hold`'s docstring-only shape |
| `src/availability_engine/contracts.py` | model (Pydantic public contract types) | transform (validation boundary) | itself — `SlotStatus` (StrEnum pattern), `Booking` (frozen BaseModel), `ReasonCode` (closed enum, already pre-seeded) | exact — add `BookingStatus` StrEnum mirroring `SlotStatus`; add `status` field to `Booking` |
| `src/availability_engine/errors.py` | model (exception hierarchy) | error handling | itself — `HoldNotFoundError` (id-only ctor, reuses `ReasonCode.NOT_FOUND`) | exact — new `BookingNotFoundError` and `IdempotencyConflictError` copy this exact shape |
| `src/availability_engine/engine.py` | controller/facade | request-response (thin passthrough) | itself — `release_hold` (thin one-line passthrough), `confirm_hold` (payload passthrough) | exact — add `idempotency_key` kwarg passthrough on `place_hold`/`confirm_hold`; add `cancel_booking` mirroring `release_hold` |
| `src/availability_engine/__init__.py` | config (public export barrel) | transform (re-export) | itself — existing `__all__` list | exact — append new names, alphabetically per existing convention |

No file in this phase needs an external analog search — every change is an incremental extension of an already-established in-repo idiom (per RESEARCH.md's own conclusion). No files with "no analog."

## Pattern Assignments

### `src/availability_engine/storage/memory.py` (storage, CRUD/lock-guarded)

**Analog:** same file — `place_hold` (lines 75-112) and `get_active_entries` (lines 37-73)

**Imports pattern** (lines 9-21):
```python
import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from availability_engine.contracts import Booking, Hold, Resource
from availability_engine.core.intervals import Interval, overlaps
from availability_engine.errors import (
    CapacityExhaustedError,
    HoldExpiredError,
    HoldNotFoundError,
)
```
Add `hashlib`, `json` for fingerprinting; add `BookingStatus` to the `contracts` import; add `BookingNotFoundError`, `IdempotencyConflictError` to the `errors` import.

**Lock-guarded check-and-write pattern to copy** (lines 84-112, `place_hold`):
```python
async with self._lock:
    resource = self._resources.get(resource_id)
    effective_capacity = resource.capacity if resource is not None else capacity
    active = await self.get_active_entries(resource_id, slot)
    if len(active) >= effective_capacity:
        raise CapacityExhaustedError(resource_id, slot)
    hold = Hold(...)
    self._holds[hold.id] = hold
    return hold
```
The idempotency check/store must be inserted at the *start* (check) and *end* (store, success-path only) of this exact block — no `await` may separate check from store (Pitfall 1). `get_active_entries` is itself pure dict iteration (no real I/O), so awaiting it inside the lock does not reopen the TOCTOU window — same reasoning applies to any new pure-computation step (fingerprinting) added here.

**Active-entries filter pattern to extend** (lines 65-72, booking loop inside `get_active_entries`):
```python
for booking in self._bookings.values():
    # Bookings have no expiry — cancellation is Phase 3's HOLD-06,
    # out of scope here.
    if booking.resource_id != resource_id:
        continue
    booking_interval = Interval(start=booking.slot_start, end=booking.slot_end)
    if overlaps(booking_interval, window):
        entries.append(booking)
```
Add one `continue` branch for `booking.status == BookingStatus.CANCELLED`, mirroring the hold-expiry `continue` at lines 50-61 (same file) — same idiom, new predicate.

**Sibling method to copy for `cancel_booking`** (lines 137-139, `release_hold`):
```python
async def release_hold(self, hold_id: str) -> None:
    async with self._lock:
        self._holds.pop(hold_id, None)
```
`cancel_booking` follows the same `async def ... : async with self._lock:` shape but must NOT silently no-op (per D-04/Anti-Pattern) — it looks up, validates status, raises `BookingNotFoundError` on missing-or-already-cancelled, otherwise mutates in place. Do not copy `release_hold`'s pop-and-ignore semantics.

**Error handling pattern** (from `confirm_hold`, lines 120-126):
```python
hold = self._holds.get(hold_id)
if hold is None:
    raise HoldNotFoundError(hold_id)
if datetime.now(UTC) >= hold.expires_at:
    raise HoldExpiredError(hold_id)
```
Same `.get()` + `is None` + raise-dedicated-exception idiom applies to `cancel_booking`'s booking lookup and to the idempotency-record lookup/conflict raise.

---

### `src/availability_engine/storage/protocol.py` (interface, request-response)

**Analog:** same file — `release_hold` (lines 45-47), `confirm_hold` (lines 35-43)

**Method declaration pattern to copy:**
```python
async def release_hold(self, hold_id: str) -> None:
    """Idempotent explicit release."""
    ...
```
New `cancel_booking(self, booking_id: str) -> None: ...` with a docstring noting it is NOT idempotent (raises on not-found/already-cancelled) — contrast explicitly with `release_hold`'s "Idempotent explicit release" docstring so the asymmetry is visible at the interface level.

`idempotency_key` kwargs on `place_hold`/`confirm_hold` (lines 28-29, 39) are **already frozen from Phase 1** — no signature change needed there, only the `InMemoryStore` implementation behind them changes.

---

### `src/availability_engine/contracts.py` (model, transform/validation boundary)

**Analog:** `SlotStatus` (lines 142-150) for the new `BookingStatus` enum; `Booking` (lines 192-198) for the field addition; `ReasonCode` (lines 153-163) already pre-seeded, reuse don't-widen.

**StrEnum pattern to copy:**
```python
class SlotStatus(StrEnum):
    AVAILABLE = "available"
    BOOKED = "booked"
```
New:
```python
class BookingStatus(StrEnum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
```

**Frozen BaseModel field-add pattern** (lines 192-198):
```python
class Booking(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    resource_id: str
    slot_start: UtcDatetime
    slot_end: UtcDatetime
    payload: dict[str, Any]
```
Add `status: BookingStatus = BookingStatus.CONFIRMED` as the new field — default keeps existing `Booking(...)` construction call sites (in `memory.py::confirm_hold`) unchanged/non-breaking.

**Closed-enum reuse (do not widen)** (lines 153-163):
```python
class ReasonCode(StrEnum):
    CAPACITY_EXHAUSTED = "capacity_exhausted"
    OUTSIDE_HOURS = "outside_hours"
    HOLD_EXPIRED = "hold_expired"
    NOT_FOUND = "not_found"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
```
Both new exceptions must reuse `NOT_FOUND` and `IDEMPOTENCY_CONFLICT` respectively — never add a member.

---

### `src/availability_engine/errors.py` (model, error handling)

**Analog:** `HoldNotFoundError` (lines 57-64) — exact shape to copy twice.

```python
class HoldNotFoundError(AvailabilityEngineError):
    """Raised when a hold_id does not refer to a currently active hold."""

    reason_code = ReasonCode.NOT_FOUND

    def __init__(self, hold_id: str) -> None:
        self.hold_id = hold_id
        super().__init__(f"hold {hold_id!r} not found")
```

Copy verbatim-shape for:
- `BookingNotFoundError` — `reason_code = ReasonCode.NOT_FOUND`, ctor takes only `booking_id: str`, message `f"booking {booking_id!r} not found"`.
- `IdempotencyConflictError` — `reason_code = ReasonCode.IDEMPOTENCY_CONFLICT`, ctor takes only `(operation_type: str, key: str)` — **never** the conflicting args/payload (module docstring rule, lines 3-5: "never accepts or stores a payload argument").

---

### `src/availability_engine/engine.py` (facade, request-response passthrough)

**Analog:** `release_hold` (lines 119-120) for `cancel_booking`; `confirm_hold` (lines 114-117) for kwarg passthrough shape.

**Thin passthrough pattern:**
```python
async def release_hold(self, hold_id: str) -> None:
    await self._storage.release_hold(hold_id)
```
```python
async def confirm_hold(self, hold_id: str, payload: dict[str, Any]) -> Booking:
    # Never log `payload` anywhere (T-01-01) — it flows only into
    # Booking.payload, untouched.
    return await self._storage.confirm_hold(hold_id, payload)
```
New `cancel_booking(self, booking_id: str) -> None` copies the `release_hold` one-liner shape exactly. `place_hold`/`confirm_hold` gain a new defaulted `idempotency_key: str | None = None` parameter forwarded unchanged to `self._storage.place_hold(...)` / `self._storage.confirm_hold(...)` — same forwarding idiom already used for `payload` in `confirm_hold`.

**Imports pattern** (lines 8-24) — add `BookingNotFoundError` (not currently imported; only `OutsideHoursError`/`ResourceNotFoundError` are) if the facade itself needs to reference it (it likely doesn't — errors bubble from storage), otherwise no import change needed here besides `contracts` if `BookingStatus` needs referencing at facade level (unlikely, per architecture map: cancellation logic lives in storage tier).

---

### `src/availability_engine/__init__.py` (config, re-export barrel)

**Analog:** entire existing file (lines 3-37).

```python
from availability_engine.errors import (
    CapacityExhaustedError,
    HoldExpiredError,
    HoldNotFoundError,
    ResourceNotFoundError,
)
...
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
    "ResourceNotFoundError",
    "SlotStatus",
    "StorageBackend",
    "Weekday",
]
```
Add `BookingNotFoundError`, `IdempotencyConflictError` to the `errors` import block; add `BookingStatus` to the `contracts` import block. Insert all three into `__all__` maintaining the existing alphabetical ordering convention (verify by re-reading the final list, not just appending).

---

## Shared Patterns

### Lock-guarded check-and-write (TOCTOU-safe critical section)
**Source:** `src/availability_engine/storage/memory.py:84-112` (`place_hold`)
**Apply to:** Idempotency check/store logic inside `place_hold`, `confirm_hold`; the new `cancel_booking` method.
**Rule:** Check state, execute the mutation, and write any derived record (idempotency record, cancelled status) all inside one `async with self._lock:` block with **no intervening `await`**. This is the single most safety-critical pattern in this phase (Pitfall 1).

### Exception hierarchy shape
**Source:** `src/availability_engine/errors.py:57-64` (`HoldNotFoundError`) and module docstring (lines 3-5)
**Apply to:** `BookingNotFoundError`, `IdempotencyConflictError`
**Rule:** `reason_code` class attribute set to a pre-existing `ReasonCode` member (never widen the enum); constructor accepts only non-sensitive identifiers, never payload/args; message uses `!r` on the identifier.

### Closed enum reuse
**Source:** `src/availability_engine/contracts.py:153-163` (`ReasonCode`)
**Apply to:** Both new exceptions above — `NOT_FOUND` and `IDEMPOTENCY_CONFLICT` are already pre-seeded members; do not add new ones.

### Thin facade passthrough
**Source:** `src/availability_engine/engine.py:119-120` (`release_hold`)
**Apply to:** New `cancel_booking` facade method — one-line `await self._storage.<method>(...)`, no lock, no business logic (facade never takes a lock, per module docstring lines 3-4).

### StrEnum for status/reason fields
**Source:** `src/availability_engine/contracts.py:142-150` (`SlotStatus`)
**Apply to:** New `BookingStatus` enum (`CONFIRMED`/`CANCELLED`).

## No Analog Found

None — every touched file in this phase extends an already-verified in-repo idiom; no external-codebase or cross-project analog search was needed (confirmed by RESEARCH.md's own "Key insight": "Every piece this phase needs ... already has a working analog somewhere in this exact codebase from Phases 1–2").

## Metadata

**Analog search scope:** `src/availability_engine/` (all 6 files read directly this session: `storage/memory.py`, `storage/protocol.py`, `contracts.py`, `errors.py`, `engine.py`, `__init__.py`)
**Files scanned:** 6 (all files to be modified this phase; no new files)
**Pattern extraction date:** 2026-09-04
