# Phase 2: Capacity & Time Correctness - Pattern Map

**Mapped:** 2026-09-03
**Files analyzed:** 9 (5 modified production, 4+ new test files)
**Analogs found:** 9 / 9 — every file being touched is modified in place (Phase 1 wrote all of them); "analog" here means the file's OWN current content is the base to extend, since Phase 2 is a hardening/restructuring phase, not a new-module phase.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `src/availability_engine/contracts.py` | model (Pydantic contract) | transform (schema restructure) | itself (Phase 1 version, lines 91-113) | exact — in-place restructure |
| `src/availability_engine/errors.py` | model (exception hierarchy) | request-response (raised across facade) | itself (Phase 1 version, full file) | exact — in-place extend |
| `src/availability_engine/time.py` | utility (boundary conversion) | transform (local→UTC) | itself (`localize_operating_hours`, lines 29-64) | exact — one-line fix in place |
| `src/availability_engine/storage/memory.py` | service/storage (StorageBackend impl) | CRUD | itself (`get_active_entries`/`_count_active`, lines 37-69) | exact — collapse duplication in place |
| `src/availability_engine/engine.py` | service (facade) | request-response | itself (`get_availability`/`place_hold`, lines 34-100) | exact — in-place extend |
| `tests/core/test_availability.py` (NEW) | test (hypothesis property) | transform | `tests/core/test_grid.py` (structure) + `core/availability.py` (subject) | role-match |
| `tests/core/test_grid_dst.py` (NEW) | test (fixture) | transform | `tests/core/test_grid.py` (full file, structure/style) | exact style-match |
| `tests/core/test_time_boundary.py` (NEW) | test (fixture) | transform | `tests/core/test_grid.py` (structure/style) | exact style-match |
| `tests/test_contract_conformance.py` (NEW) | test (golden-file) | transform | `tests/test_contracts.py` (Pydantic contract testing conventions) | role-match |
| `tests/test_engine.py` (EXTENDED) | test (integration) | request-response | itself (`test_get_availability_end_to_end`, lines 25-50) | exact — extend in place |

## Pattern Assignments

### `src/availability_engine/contracts.py` (model, transform)

**Analog:** itself, current `SlotStatus`/`PublicSlot`/`AvailabilityResult` block (lines 91-113)

**Current shape to replace** (lines 91-113):
```python
class SlotStatus(StrEnum):
    AVAILABLE = "available"
    BOOKED = "booked"

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
```

**Project StrEnum idiom to copy** (this is how `Weekday`/`SlotStatus` are declared — reuse exactly for the new `ReasonCode`, lines 34-42 and 91-93):
```python
class Weekday(IntEnum):
    MONDAY = 0
    ...
```
→ `ReasonCode` should be a `StrEnum` following the same flat-members style, per RESEARCH.md Pattern 4.

**`model_config = ConfigDict(frozen=True)` pattern** — every existing Pydantic model in this file uses this; new/restructured models (`PublicSlot`, `AvailabilityResult`) must keep it (lines 52, 62, 102, 110, 116, 125).

**Target restructure** (from RESEARCH.md Pattern 1, verified against actual field names):
```python
class PublicSlot(BaseModel):
    model_config = ConfigDict(frozen=True)
    start: UtcDatetime
    end: UtcDatetime
    resource_id: str
    capacity: Annotated[int, Field(ge=1)]
    remaining: Annotated[int, Field(ge=0)]

class AvailabilityResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    resource_id: str
    available: list[PublicSlot]
    booked: list[PublicSlot]
```
Note: `Field(ge=1)` / `Field(ge=timedelta(0))` constrained-field idiom already used for `Resource.capacity` (line 64) and `Resource.buffer` (line 69) — copy that same `Annotated[..., Field(...)]` style for the new `capacity`/`remaining` fields.

---

### `src/availability_engine/errors.py` (model, request-response)

**Analog:** itself, full file (44 lines) — every exception follows one identical shape.

**Existing exception shape to copy for `OutsideHoursError`** (lines 13-19, `CapacityExhaustedError` — closest existing analog since it also takes `(resource_id, slot: Interval)`):
```python
class CapacityExhaustedError(Exception):
    """Raised when a hold is requested but the resource's capacity is full."""

    def __init__(self, resource_id: str, slot: Interval) -> None:
        self.resource_id = resource_id
        self.slot = slot
        super().__init__(f"capacity exhausted for resource {resource_id!r}")
```
`OutsideHoursError(resource_id, slot)` should mirror this exactly, changing only the docstring/message.

**Convention to preserve:** docstring at top of file (lines 1-6) states constructors accept "only non-sensitive identifiers" and never a payload — do not add a `payload` param to any new exception.

**New base-class pattern (from RESEARCH.md Pattern 4, not yet in codebase):**
```python
class AvailabilityEngineError(Exception):
    reason_code: ReasonCode

class CapacityExhaustedError(AvailabilityEngineError):
    reason_code = ReasonCode.CAPACITY_EXHAUSTED
    def __init__(self, resource_id: str, slot: Interval) -> None: ...
```
All four existing exceptions (`CapacityExhaustedError`, `HoldExpiredError`, `HoldNotFoundError`, `ResourceNotFoundError`) need to be rebased onto `AvailabilityEngineError` and gain a `reason_code` class attribute; `OutsideHoursError` is added net-new following the same shape.

---

### `src/availability_engine/time.py` (utility, transform)

**Analog:** itself, `localize_operating_hours()` (lines 29-64) — the exact function to fix, no new file.

**Current buggy loop body** (lines 48-62):
```python
while current_date <= end_date:
    weekday = Weekday(current_date.weekday())
    for local_interval in resource.operating_hours.get(weekday, []):
        local_start = datetime.combine(
            current_date, local_interval.start, tzinfo=tz
        )
        local_end = datetime.combine(current_date, local_interval.end, tzinfo=tz)
        utc_interval = Interval(
            start=local_start.astimezone(UTC),
            end=local_end.astimezone(UTC),
        )
        clipped = intersect(utc_interval, query_window)
        if clipped is not None:
            intervals.append(clipped)
    current_date += timedelta(days=1)
```

**Required fix** (verified line-precise in RESEARCH.md Pattern 2): compute a separate `end_date` per `local_interval` (not to be confused with the outer loop's `end_date` variable — rename or scope carefully) that is `current_date + timedelta(days=1)` iff `local_interval.end <= local_interval.start`, then `datetime.combine(that_date, local_interval.end, tzinfo=tz)`. Everything else in the function (the `.astimezone(UTC)` conversion, the `intersect()` clip) is unchanged — the fix is confined to the `local_end` construction line.

**Do not touch:** `core/grid.py` (`grid_slots`) — confirmed DST-safe by construction; RESEARCH.md's explicit anti-pattern is adding DST branches there.

**Module docstring note (lines 6-8) is now stale** and should be updated once Phase 2 lands — it currently says "Midnight-crossing... explicitly deferred to Phase 2 — do not handle them here," which will no longer be true.

---

### `src/availability_engine/storage/memory.py` (service/storage, CRUD)

**Analog:** itself — `get_active_entries()` (lines 37-53) is the analog `_count_active()` (lines 55-69) must be collapsed into.

**Current duplicated pair:**
```python
async def get_active_entries(self, resource_id: str, window: Interval) -> list[Hold | Booking]:
    entries: list[Hold | Booking] = []
    for hold in self._holds.values():
        if hold.resource_id != resource_id:
            continue
        hold_interval = Interval(start=hold.slot_start, end=hold.slot_end)
        if overlaps(hold_interval, window):
            entries.append(hold)
    for booking in self._bookings.values():
        if booking.resource_id != resource_id:
            continue
        booking_interval = Interval(start=booking.slot_start, end=booking.slot_end)
        if overlaps(booking_interval, window):
            entries.append(booking)
    return entries

def _count_active(self, resource_id: str, slot: Interval) -> int:
    # same overlap-scan logic, duplicated, and used only by place_hold
```

**Fix pattern (RESEARCH.md Pattern 3):** add `now = datetime.now(UTC)` and `if hold.expires_at <= now: continue` inside `get_active_entries`'s hold loop (bookings have no expiry — HOLD-06/cancel is Phase 3, do not add expiry filtering to the booking loop). Delete `_count_active` entirely; `place_hold` (lines 71-101, specifically line 90 `active = self._count_active(resource_id, slot)`) must call `await self.get_active_entries(resource_id, slot)` and use `len(active)` instead.

**Existing correct expiry predicate to reuse** (line 113, `confirm_hold`):
```python
if datetime.now(UTC) >= hold.expires_at:
    raise HoldExpiredError(hold_id)
```
i.e. active iff `expires_at > now` — this is the exact predicate `get_active_entries` must apply.

**Lock discipline to preserve:** `place_hold`'s `async with self._lock:` block (line 80) must still perform the check-and-write with no intervening real `await` suspension — calling `await self.get_active_entries(...)` from inside the lock is safe (RESEARCH.md verified: zero real I/O, no suspension point) but add a comment explaining this, matching the existing TOCTOU-avoidance comment style at lines 81-89.

---

### `src/availability_engine/engine.py` (service, request-response)

**Analog:** itself, `get_availability()` (lines 34-79) and `place_hold()` (lines 81-100).

**Current `get_availability` slot-assembly loop to restructure** (lines 61-79):
```python
slots: list[PublicSlot] = []
for fragment, remaining_capacity in fragments:
    status = (
        SlotStatus.BOOKED if remaining_capacity <= 0 else SlotStatus.AVAILABLE
    )
    slot_intervals = grid_slots(fragment, resource.slot_duration, resource.buffer)
    for slot_interval in slot_intervals:
        slots.append(
            PublicSlot(
                start=slot_interval.start,
                end=slot_interval.end,
                resource_id=resource_id,
                status=status,
            )
        )
return AvailabilityResult(resource_id=resource_id, slots=slots)
```
Replace with the two-list `available`/`booked` split per contracts.py's new shape (RESEARCH.md Pattern 1) — same loop shape, append to one of two lists instead of setting a `status` field, and pass `capacity=resource.capacity, remaining=remaining_capacity` into `PublicSlot(...)`.

**Existing validation-then-delegate style to copy for the new outside-hours check** (lines 88-96, `place_hold`'s existing `slot_end <= slot_start` guard):
```python
resource = await self._storage.get_resource(resource_id)
if resource is None:
    raise ResourceNotFoundError(resource_id)
if slot_end <= slot_start:
    raise ValueError(
        f"slot_end ({slot_end}) must be after slot_start ({slot_start})"
    )
```
Add the `OutsideHoursError` containment check in this same style, reusing `time_boundary.localize_operating_hours(resource, slot_start, slot_end)` (already imported as `time_boundary`, line 10) — do not write new hours-comparison logic.

**Import block to extend** (lines 8-24) — add `OutsideHoursError`, `ReasonCode` (if referenced directly) to the existing `from availability_engine.errors import ResourceNotFoundError` line (line 23) and `from availability_engine.contracts import (...)` block (lines 11-19) for the new/renamed contract symbols.

---

### `tests/core/test_grid_dst.py` (NEW test, fixture-based)

**Analog:** `tests/core/test_grid.py` (full file, 39 lines) — copy its module docstring convention (`"""... unit tests (...). No production code is modified by this file."""`), its `_FRAGMENT_START`/module-level constant style (lines 11-12), and its bare-`async def`-free, plain-function-per-scenario structure (Interval/grid_slots don't need async — same applies to `localize_operating_hours` and DST fixtures).

**Concrete fixture dates to hardcode** (verified in RESEARCH.md, do not re-derive): `America/New_York` spring-forward `2026-03-08`, fall-back `2026-11-01`; expected UTC spans: overnight 22:00→06:00 spans-spring-forward = 7h (not nominal 8h), spans-fall-back = 9h; midnight→4am spring-forward = 3h, fall-back = 5h.

---

### `tests/core/test_time_boundary.py` (NEW test, fixture-based)

**Analog:** `tests/core/test_grid.py` (structure/style) + the module under test is `time.py::localize_operating_hours`.

**Detection helpers to copy verbatim from RESEARCH.md Pattern 2** (write as test-local helpers or a small module-level fixture util, not production code unless the plan later decides otherwise):
```python
def _is_imaginary(dt: datetime, tz: ZoneInfo) -> bool:
    return dt.astimezone(UTC).astimezone(tz).replace(tzinfo=None) != dt.replace(tzinfo=None)

def _is_ambiguous(dt: datetime) -> bool:
    return dt.replace(fold=0).utcoffset() != dt.replace(fold=1).utcoffset()
```

---

### `tests/core/test_availability.py` (NEW test, hypothesis property-based)

**Analog:** `tests/core/test_grid.py` for file/module-docstring conventions; `core/availability.py::free_fragments` is the subject (already returns `(Interval, remaining_capacity)` pairs — do not modify it, only property-test it per RESEARCH.md's explicit anti-pattern warning against rewriting it).

**Concrete hypothesis test to copy** (from RESEARCH.md Code Examples, ready to adapt):
```python
from hypothesis import given, strategies as st
from availability_engine.core.availability import free_fragments
from availability_engine.core.intervals import Interval

@given(
    capacity=st.integers(min_value=1, max_value=5),
    busy_offsets=st.lists(st.tuples(st.integers(0, 55), st.integers(1, 60)), max_size=6),
)
def test_free_fragments_never_exceeds_capacity(capacity, busy_offsets):
    ...
    fragments = free_fragments(hours, busy, capacity)
    for _, remaining in fragments:
        assert 0 <= remaining <= capacity
```
Use `st.datetimes(timezones=st.timezones())` (zoneinfo-backed) if any DST-aware generation is needed here — never the deprecated `hypothesis.extra.pytz` strategy.

---

### `tests/test_contract_conformance.py` (NEW test, golden-file)

**Analog:** `tests/test_contracts.py` for Pydantic-contract-testing conventions in this repo (read for exact assertion/import style); golden-file mechanism from RESEARCH.md Pattern 5:
```python
import json
from pathlib import Path
from availability_engine.contracts import AvailabilityResult

GOLDEN_PATH = Path(__file__).parent / "golden" / "availability_result.schema.json"

def test_availability_result_schema_matches_golden() -> None:
    current_schema = AvailabilityResult.model_json_schema()
    golden_schema = json.loads(GOLDEN_PATH.read_text())
    assert current_schema == golden_schema, (...)
```
Golden file generated once via `model_json_schema()` and committed under `tests/golden/`.

---

### `tests/test_engine.py` (EXTENDED, request-response integration)

**Analog:** itself, `test_get_availability_end_to_end` (lines 21-50) — the exact style/fixture (`sample_resource` fixture from `conftest.py`, `WINDOW_START`/`WINDOW_END` module constants at lines 17-18) to extend.

**Breaking-change note:** line 30-31 (`assert result.slots` / `assert all(slot.status == SlotStatus.AVAILABLE ...)`) and line 50 (`confirmed_slot.status == SlotStatus.BOOKED`) reference the OLD flat `.slots`/`.status` shape being removed this phase — these assertions must be rewritten against `.available`/`.booked` and will break if left as-is. This existing test is itself evidence of exactly what call sites need updating for the contract restructure.

**Time-machine lazy-expiry test to add** (from RESEARCH.md Code Examples, ready to adapt — new test, no existing analog in this file since Phase 1 never exercised TTL expiry):
```python
import time_machine
from datetime import UTC, datetime, timedelta

async def test_expired_hold_stops_counting_against_capacity(store, sample_resource):
    resource = sample_resource.model_copy(update={"capacity": 1})
    ...
    with time_machine.travel(t0, tick=False):
        await store.place_hold(...)
        with pytest.raises(CapacityExhaustedError):
            await store.place_hold(...)
    with time_machine.travel(t0 + timedelta(seconds=61), tick=False):
        second_hold = await store.place_hold(...)  # no release_hold/confirm_hold call
        assert second_hold is not None
```
This test MUST fail against the current unmodified `InMemoryStore` before the Pattern 3 fix lands (RESEARCH.md Pitfall: "the active-entries expiry gap is a real, currently-shipping bug") — write/run it first to prove the gap, per RESEARCH.md's recommended sequencing.

## Shared Patterns

### `model_config = ConfigDict(frozen=True)` on every Pydantic model
**Source:** `src/availability_engine/contracts.py` (used on all 6 existing models: `LocalInterval` line 52, `Resource` line 62, `PublicSlot` line 102, `AvailabilityResult` line 110, `Hold` line 116, `Booking` line 125)
**Apply to:** the restructured `PublicSlot`/`AvailabilityResult` and any new contract model (`ReasonCode` is a `StrEnum`, not a `BaseModel`, so this doesn't apply to it).

### Constructor shape for domain exceptions: identifiers only, no payload
**Source:** `src/availability_engine/errors.py` (all 4 existing exceptions + file docstring lines 1-6)
**Apply to:** `OutsideHoursError` and the `AvailabilityEngineError` base — never accept/store a `payload` argument (Security Domain T-01-01).

### `zoneinfo` confined to `time.py` + `contracts.py` only
**Source:** `src/availability_engine/time.py` docstring (lines 1-4) and `contracts.py`'s `_validate_iana` (lines 81-88)
**Apply to:** all Phase 2 changes — `core/availability.py` and `core/grid.py` must remain zero-`zoneinfo`/zero-DST-aware code (explicit anti-pattern in RESEARCH.md).

### asyncio.Lock check-and-write with no intervening real `await`
**Source:** `src/availability_engine/storage/memory.py::place_hold` (lines 80-101, comment at 81-89)
**Apply to:** the modified `place_hold` that now calls `get_active_entries` inside the lock — preserve the existing comment style explaining why this doesn't reopen the TOCTOU window.

### Test file docstring + "no production code modified" convention
**Source:** `tests/core/test_grid.py` (lines 1-4)
**Apply to:** all new Phase 2 test files — one-line module docstring naming the requirement IDs covered (e.g. `GRID-02`, `AVAIL-03`), plus the "No production code is modified by this file" note where true.

## No Analog Found

None — every file in scope for Phase 2 is a modification of an existing Phase-1-authored file, or a new test file with a strong structural analog (`tests/core/test_grid.py`) already identified above.

## Metadata

**Analog search scope:** `src/availability_engine/` (contracts.py, errors.py, time.py, engine.py, storage/memory.py, core/*.py), `tests/` (all existing test files)
**Files scanned:** contracts.py, errors.py, time.py, engine.py, storage/memory.py, storage/protocol.py (referenced), core/availability.py (referenced via RESEARCH.md), core/grid.py, tests/core/test_grid.py, tests/test_engine.py, tests/test_contracts.py (referenced)
**Pattern extraction date:** 2026-09-03
**Primary source for concrete excerpts:** `.planning/phases/02-capacity-time-correctness/02-RESEARCH.md` (line-verified against live source this session) cross-checked directly against current file contents read in this pass.
