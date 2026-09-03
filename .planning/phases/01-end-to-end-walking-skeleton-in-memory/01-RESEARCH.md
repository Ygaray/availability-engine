# Phase 1: End-to-End Walking Skeleton (In-Memory) - Research

**Researched:** 2026-09-03
**Domain:** Python async domain-agnostic scheduling engine — contract-first walking skeleton (Resource → slot grid → availability → hold/confirm/release), in-memory backend only
**Confidence:** MEDIUM-HIGH (architecture and pitfalls are HIGH confidence from prior project-level research; phase-specific implementation details — Pydantic validator patterns, exact version pins, Protocol shape — verified this session)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01 [contract-types]:** Pydantic v2 at the public output/input boundary (gives the parallel consumer an exportable JSON schema to stub against) + `@dataclass(frozen=True, slots=True)` for engine-internal value objects (`Slot`, interval endpoints, internal `Hold` state). **Reversibility:** one-way — the consumer's stub pins to the published contract shape; changing the boundary type system after the pin breaks the consumer.
- **D-02 [payload]:** The opaque consumer payload is a JSON-serializable `dict`, attached at confirm and round-tripped verbatim on the `Booking` — composes cleanly with the Pydantic-serialized output contract.
- **D-03 [hours-shape]:** A Resource's per-weekday operating hours are a list-of-half-open-intervals per weekday (already permits overnight/split shifts), chosen now to physically accommodate overnight/split hours even though correct midnight-crossing generation is deferred to Phase 2 — avoids a breaking `Resource` input change after the consumer pins. **Reversibility:** one-way — a published `Resource` input shape the consumer pins to.
- **D-04 [protocol-signatures]:** Freeze forward-compatible `StorageBackend` Protocol and `AvailabilityEngine` facade signatures now; reserve payload/ttl params, and let Phase 2/3 additions (reason codes, idempotency key, `expire_holds`) arrive as defaulted kwargs or new methods — never as changed existing signatures, so the SQL backend and the consumer stub don't break. **Reversibility:** costly — later phases and the consumer stub bind to these signatures.
- **D-05 [tooling]:** Enforce strict `ruff` + `mypy --strict` on `src/` from commit 1 — catches contract drift and naive-datetime leaks before they accumulate across four phases; retrofitting strict typing late is a large cleanup.
- **D-06 [versions]:** Re-verify exact PyPI version pins against PyPI at implementation time (Pydantic 2.13.x, pytest-asyncio 0.24.x+, ruff 0.9.x+, mypy 1.13.x+) rather than pinning blindly from the research snapshot; defer the SQL/testcontainers stack to Phase 4.

### Claude's Discretion

Internal module layout, exact `Slot`/`Interval` field names, and in-memory store internals are open provided they honor the frozen public contract above.

### Deferred Ideas (OUT OF SCOPE)

- Correct midnight-crossing slot generation → Phase 2 (`midnight-hours`).
- DST-transition representation → Phase 2 (`dst-contract`).
- Idempotency key + reason codes as defaulted params/new methods → Phase 3.
- SQL backend + version pins for the SQL/testcontainers stack → Phase 4.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MODEL-01 | Consumer can define a Resource with a capacity of ≥ 1 concurrent bookings | `Resource` dataclass/Pydantic model shape below — `capacity: int` with `Field(ge=1)` |
| MODEL-02 | Consumer can set a Resource's per-day operating hours (per weekday), expressed in local wall-clock time | `OperatingHours` shape (D-03): `dict[Weekday, list[LocalInterval]]`, local `time` objects, not pre-converted UTC |
| MODEL-03 | Consumer can set a Resource's buffer/reset time enforced between consecutive sessions | `Resource.buffer: timedelta` field; applied at grid/availability boundary only (not in this phase's grid overlay — v1 grid can be buffer-agnostic per Claude's Discretion, but the field must exist per contract-freeze concern) |
| MODEL-04 | Consumer can assign a Resource an IANA timezone that governs its operating hours and DST | `Resource.timezone: str`, validated as a real IANA key via `zoneinfo.ZoneInfo(value)` in a Pydantic validator |
| MODEL-05 | All domain value objects are immutable and use half-open `[start, end)` time intervals | Frozen dataclasses (`frozen=True, slots=True`) for internal `Interval`, `Slot`, `Hold`; Pydantic `model_config = ConfigDict(frozen=True)` for boundary types |
| GRID-01 | Engine generates a fixed-duration slot grid for a Resource from operating hours + slot length + buffer | `core/grid.py::grid_slots()` pattern below |
| GRID-04 | All engine inputs/outputs at the public boundary are UTC-aware datetimes; naive datetimes rejected | Pydantic `AwareDatetime` + custom validator enforcing UTC offset, at every boundary type |
| AVAIL-01 | Consumer can query a Resource's availability over a date range and receive structured available/booked windows | `AvailabilityResult` Pydantic model — see Code Examples |
| STORE-01 | Coarse-grained async storage protocol, each method one atomic operation | `StorageBackend(Protocol)` — see Code Examples |
| STORE-02 | In-memory storage implementation ships as reference/test backend | `InMemoryStore` — dict + single `asyncio.Lock` |
| HOLD-01 | Place a short-lived atomic hold on a slot with a TTL; rejected if capacity exhausted | `place_hold()` signature — see Code Examples |
| HOLD-03 | Confirm an active, unexpired hold into a Booking with opaque payload round-trip | `confirm_hold()` signature |
| HOLD-04 | Explicitly release a hold, freeing capacity immediately | `release_hold()` signature |
</phase_requirements>

## Summary

Phase 1 is a **walking skeleton**, not a full horizontal layer — the goal is one real, working vertical path (define Resource → generate grid → query availability → place/confirm/release hold) through every architectural tier, using the in-memory backend only. The project-level research (`STACK.md`, `ARCHITECTURE.md`, `PITFALLS.md`) already fully covers the target architecture; this phase's research task is narrower: nail the **exact types and signatures** that get frozen at the D-01/D-03/D-04 contract boundary, since those are one-way decisions the parallel consumer pins against.

Three things matter most for planning this phase correctly. First, the Pydantic v2 boundary types must reject naive datetimes using the built-in `AwareDatetime` annotation plus a custom validator that also enforces UTC (not just "any" timezone) — `AwareDatetime` alone accepts non-UTC aware datetimes, which the UTC-internal constraint forbids. Second, the `StorageBackend` Protocol must be written coarse-grained and forward-compatible from the first line: `place_hold`/`confirm_hold` should accept `payload: dict | None = None` and `ttl_seconds: int` now (even though HOLD-03 payload is scoped to confirm per D-02 in the roadmap — reconcile by accepting `payload` at confirm per the requirement, and reserve an idempotency-key kwarg for Phase 3 as a `str | None = None` default so the signature never needs to change shape later, only gain new defaulted params). Third, version pins have moved meaningfully since the milestone-level `STACK.md` snapshot: `pytest-asyncio` is now on the 1.x line (not 0.24.x), which changes fixture-scoping syntax (`event_loop` fixture removed) — this is a testing-infrastructure detail the plan's Wave 0 must account for.

**Primary recommendation:** Freeze `contracts.py` (Pydantic v2 boundary types: `Resource`, `AvailabilityResult`, `Slot` (public view), `Hold`, `Booking`) and `storage/protocol.py` (`StorageBackend` Protocol) as the first two files written in this phase, before any grid/availability logic — every other file in the phase depends on these shapes being stable, and both are one-way decisions per D-01/D-04.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Resource/Interval/Hold/Booking domain types | Domain/Contract layer (`contracts.py`) | — | Pure data shapes; the contract-first artifact the consumer pins to (D-01) |
| Local wall-clock → UTC conversion | Time boundary (`time.py`) | Public Facade (`engine.py`, calls it) | Only place `zoneinfo` is imported; must never leak into `core/` (structural rule from ARCHITECTURE.md) |
| Slot grid generation, interval math | Compute core (`core/`) | — | Pure functions, zero I/O, zero tz-awareness — operates only on already-UTC `Interval` objects |
| Availability computation (sweep-line stub for v1 capacity handling) | Compute core (`core/availability.py`) | — | v1 needs only enough of this to answer AVAIL-01; full capacity-aware sweep-line hardening is Phase 2 (AVAIL-02) but the primitive should be built once, correctly, now per ARCHITECTURE.md Pattern 3 |
| Hold/confirm/release atomicity | Storage backend (`storage/memory.py`) | Public Facade (orchestrates, owns no locking) | Atomicity must live in the backend behind the Protocol — the engine facade never takes a lock itself (STORE-01 structural requirement) |
| Public async API surface | Public Facade (`engine.py`) | — | The only thing the consumer imports; thin orchestration, no business logic duplicated here |
| Naive-datetime rejection | Domain/Contract layer (Pydantic validators) | Time boundary (`require_utc()` guard for internal call sites not going through Pydantic) | GRID-04 requires rejection at every public entry point, not just the Pydantic-typed ones — internal functions taking raw `datetime` need the same guard |

## Standard Stack

### Core (already locked — no re-litigation; version pins re-verified this session)

| Library | Version (verified 2026-09-03) | Purpose | Provenance |
|---------|---------|---------|--------------|
| Python | 3.12+ | Runtime | Locked in CLAUDE.md |
| Pydantic | **2.13.5** | Public boundary types (`Resource`, `Hold`, `Booking`, `AvailabilityResult`) | `[VERIFIED: PyPI registry — pypi.org/pypi/pydantic/json, "version": "2.13.5", published 2026-08-28]` — matches D-06's expected 2.13.x line |
| `dataclasses` (stdlib, `frozen=True, slots=True`) | stdlib | Internal value objects (`Interval`, internal `Slot`, internal `Hold` state) | `[VERIFIED: python docs — dataclasses module, stdlib since 3.7, slots param since 3.10]` |
| `typing.Protocol` (stdlib) + `typing.runtime_checkable` | stdlib | `StorageBackend` async structural interface | `[VERIFIED: python docs — typing module]` |
| `zoneinfo` (stdlib) | stdlib | IANA timezone resolution at the boundary only | `[VERIFIED: python docs — zoneinfo, stdlib since 3.9]` |

### Supporting / Dev-Test (Phase 1 scope)

| Library | Version (verified 2026-09-03) | Purpose | Provenance |
|---------|---------|---------|-------------|
| pytest | **9.1.1** | Test runner | `[VERIFIED: PyPI registry — pypi.org/pypi/pytest/json, "version": "9.1.1", published 2026-06-19]` — a major-version jump past the milestone research's assumed 8.x baseline |
| pytest-asyncio | **1.4.0** | Async test functions/fixtures | `[VERIFIED: PyPI registry — pypi.org/pypi/pytest-asyncio/json, "version": "1.4.0", published 2026-05-26]` — **major-version jump past D-06's assumed 0.24.x**; see Pitfall/Note below, this changes fixture syntax |
| ruff | **0.16.6** | Lint + format | `[VERIFIED: PyPI registry — pypi.org/pypi/ruff/json, "version": "0.16.6", published 2026-09-03]` |
| mypy | **2.3.1** | Static typing, `--strict` on `src/` | `[VERIFIED: PyPI registry — pypi.org/pypi/mypy/json, "version": "2.3.1", published 2026-08-15]` — **major-version jump past D-06's assumed 1.13.x**; mypy crossed 2.0 since the milestone research snapshot. `[ASSUMED]` no breaking `--strict`-flag semantics change for this project's usage (not independently verified this session — flag at Wave 0 for a quick `mypy --strict` smoke run before committing to the pin)

**Version drift note:** All three test/lint tools (pytest, pytest-asyncio, mypy) have moved a full major version past what the milestone-level `STACK.md`/decision-map snapshot assumed. This is exactly the scenario D-06 anticipated ("re-verify exact pins against PyPI at implementation time... snapshot versions may lag") — the plan should pin these exact verified versions rather than the ranges written in `STACK.md`, and treat the pytest-asyncio 0.x→1.x jump as a real breaking-change surface (see Common Pitfalls).

**Installation:**
```bash
uv add pydantic
uv add --dev pytest pytest-asyncio ruff mypy
```

## Package Legitimacy Audit

All five packages below are pre-approved in `.planning/APPROVED-DEPS.md` for Phase 1 (verdict `SUS`, approved 2026-09-03) — the planner does not need a `checkpoint:human-verify` task for these specific packages. Re-ran the legitimacy check this session to confirm current signals; `SUS` is driven entirely by `too-new`/`unknown-downloads` heuristics that misfire on mature packages whose latest patch/minor was published very recently — not an actual legitimacy concern (all five have long-lived, well-known GitHub source repos and, where measurable, extremely high weekly downloads).

| Package | Registry | Age (latest release) | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| pydantic | pypi | published 2026-08-28 | 179,434,598/wk | github.com/pydantic/pydantic | SUS (`too-new`) | Approved (pre-approved, APPROVED-DEPS.md) |
| ruff | pypi | published 2026-09-03 | unknown (astral.sh docs, not PyPI stats) | docs.astral.sh/ruff (github.com/astral-sh/ruff) | SUS (`too-new`, `unknown-downloads`) | Approved (pre-approved) |
| mypy | pypi | published 2026-08-15 | unknown | mypy-lang.org (github.com/python/mypy) | SUS (`too-new`, `unknown-downloads`) | Approved (pre-approved) |
| pytest | pypi | published 2026-06-19 | unknown | github.com/pytest-dev/pytest | SUS (`unknown-downloads`) | Approved (pre-approved) |
| pytest-asyncio | pypi | published 2026-05-26 | unknown | github.com/pytest-dev/pytest-asyncio | SUS (`unknown-downloads`) | Approved (pre-approved) |

**Packages removed due to `[SLOP]` verdict:** none.
**Packages flagged as suspicious `[SUS]`:** all five, per above — no additional checkpoint required since all five are already in `APPROVED-DEPS.md` for Phase 1; the discuss-phase human already cleared them. A package the planner introduces that is NOT in `APPROVED-DEPS.md` still must escalate to a human checkpoint per the standing rule (INC-2026-08-24-04).

## Architecture Patterns

(Full architecture already documented in `.planning/research/ARCHITECTURE.md` — this section only adds Phase-1-specific narrowing.)

### System Architecture Diagram (Phase 1 vertical slice)

```
consumer code
    │  (imports AvailabilityEngine, Resource, Interval — from contracts.py)
    ▼
engine.py :: AvailabilityEngine
    │
    ├─► define_resource(resource: Resource) ──────► storage.save_resource(resource)
    │
    ├─► get_availability(resource_id, date_range) ─► storage.get_resource(resource_id)
    │        │                                     ─► storage.get_active_entries(resource_id, window)
    │        ▼
    │   time.py::localize_operating_hours(resource, date_range)  [IANA local → UTC Interval[]]
    │        ▼
    │   core/availability.py :: free_fragments(hours, busy, capacity)   [sweep-line, capacity≥1]
    │        ▼
    │   core/grid.py :: grid_slots(fragments, slot_duration)            [fixed-duration overlay]
    │        ▼
    │   wrap into AvailabilityResult (Pydantic) ──► return to consumer
    │
    ├─► place_hold(resource_id, slot, ttl_seconds) ─► storage.place_hold(...)  [atomic; asyncio.Lock in memory]
    │        rowcount/count check inside the lock → Hold | raise CapacityExhaustedError
    │
    ├─► confirm_hold(hold_id, payload: dict) ───────► storage.confirm_hold(hold_id, payload)
    │        atomic status flip active→confirmed, still-valid check → Booking | raise HoldExpiredError/HoldNotFoundError
    │
    └─► release_hold(hold_id) ──────────────────────► storage.release_hold(hold_id)   [idempotent]
```

A reader can trace the primary use case (define resource → query availability → hold → confirm) top to bottom through this diagram; every arrow crossing into `storage.*` is exactly one atomic Protocol call, per STORE-01.

### Recommended Project Structure (Phase 1 scope only)

```
src/
└── availability_engine/
    ├── __init__.py              # exports: AvailabilityEngine + contracts.py public names
    ├── contracts.py             # Resource, Interval (public), Slot, Hold, Booking, AvailabilityResult — Pydantic v2
    ├── errors.py                # CapacityExhaustedError, HoldExpiredError, HoldNotFoundError (minimal set for Phase 1)
    ├── time.py                  # localize_operating_hours(), require_utc() guard
    ├── core/
    │   ├── intervals.py         # internal half-open Interval (frozen dataclass) + overlap/merge
    │   ├── availability.py      # sweep-line free_fragments() — build correctly now, harden capacity>1 edge cases in Phase 2
    │   └── grid.py              # grid_slots() fixed-duration overlay
    ├── storage/
    │   ├── protocol.py          # StorageBackend(Protocol) — async, coarse-grained
    │   └── memory.py            # InMemoryStore(StorageBackend)
    └── engine.py                 # AvailabilityEngine facade

tests/
├── storage/
│   └── contract_suite.py        # shared async test suite — parametrized now over InMemoryStore only;
│                                 # designed so Phase 4 adds SQLStore params without rewriting tests
├── core/
│   ├── test_intervals.py
│   └── test_availability.py
└── test_time_boundary.py        # basic non-DST-transition IANA conversion tests (DST fixtures deferred to Phase 2)
```

### Pattern 1: Pydantic v2 boundary type rejecting naive datetimes, enforcing UTC

**What:** Use `AwareDatetime` (Pydantic's built-in type) combined with an `AfterValidator` that additionally checks the offset is exactly UTC — `AwareDatetime` alone accepts *any* aware datetime (e.g. `+05:00`), which is insufficient for the "UTC-internal" constraint.

**When to use:** Every public boundary field carrying a `datetime` (`Slot.start`, `Slot.end`, `Hold.expires_at`, `AvailabilityResult` window bounds).

**Example:**
```python
# Source: Pydantic v2 official docs (AwareDatetime type) + community-verified validator pattern
# [CITED: docs.pydantic.dev/latest/api/types/#pydantic.types.AwareDatetime]
from datetime import datetime, timezone
from typing import Annotated
from pydantic import AfterValidator, BaseModel, ConfigDict

def _require_utc(value: datetime) -> datetime:
    # AwareDatetime already guarantees tzinfo is set (raises "timezone_aware"
    # ValidationError otherwise) — this validator narrows further to UTC only.
    if value.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError("datetime must be UTC (offset 00:00)")
    return value

UtcDatetime = Annotated[datetime, AfterValidator(_require_utc)]
# Pydantic's AwareDatetime is itself Annotated[datetime, AwareDatetime-metadata];
# compose as: Annotated[AwareDatetime, AfterValidator(_require_utc)]

class Slot(BaseModel):
    model_config = ConfigDict(frozen=True)
    start: UtcDatetime
    end: UtcDatetime
    resource_id: str
```

**Known gotcha (verified via web search, `[CITED: github.com/pydantic/pydantic/issues/8859]`):** Pydantic 2.6+ accepts bare `"YYYY-MM-DD"` strings for `AwareDatetime`-typed fields without raising, even though such a string carries no timezone information — if the phase's plan includes JSON-input parsing (e.g. consumer sends ISO strings), add an explicit test asserting a date-only string is rejected, since the built-in type alone will not catch it.

### Pattern 2: Coarse-grained async `StorageBackend` Protocol, frozen forward-compatibly (Phase 1 scope)

**What:** Same shape as `ARCHITECTURE.md`'s Pattern 1, narrowed to exactly what Phase 1 needs, with Phase 2/3 params pre-reserved as defaulted kwargs per D-04 so the signature never has to change shape.

**Example:**
```python
# Source: adapted from .planning/research/ARCHITECTURE.md Pattern 1 (project-level research, HIGH confidence)
from typing import Protocol, runtime_checkable
from datetime import datetime

@runtime_checkable
class StorageBackend(Protocol):
    async def save_resource(self, resource: "Resource") -> None: ...

    async def get_resource(self, resource_id: str) -> "Resource | None": ...

    async def get_active_entries(
        self, resource_id: str, window: "Interval"
    ) -> list["Hold | Booking"]: ...

    async def place_hold(
        self,
        resource_id: str,
        slot: "Interval",
        capacity: int,
        ttl_seconds: int,
        payload: dict | None = None,          # reserved now; Phase 1 may pass None always
        idempotency_key: str | None = None,   # reserved for Phase 3 — never remove/rename
    ) -> "Hold":
        """Atomically insert iff active count < capacity for this slot.
        Raises CapacityExhaustedError otherwise."""

    async def confirm_hold(
        self,
        hold_id: str,
        payload: dict | None = None,
        idempotency_key: str | None = None,   # reserved for Phase 3
    ) -> "Booking":
        """Atomically transition hold -> booking iff still active and unexpired.
        Raises HoldExpiredError / HoldNotFoundError otherwise."""

    async def release_hold(self, hold_id: str) -> None:
        """Idempotent explicit release."""
```

**Reconciling D-02/D-04 for HOLD-03:** the roadmap's `HOLD-03` says "confirm... attaching an opaque consumer payload" — so `payload` belongs on `confirm_hold`, not `place_hold`, for Phase 1's actual call path. Reserve it on `place_hold` too (default `None`) only because D-04 says reserve params defensively; do not require Phase 1's `AvailabilityEngine.place_hold()` facade method to expose a `payload` parameter to the consumer if it's unused — keep the *facade's* public signature exactly as narrow as Phase 1 needs, and only the Protocol (internal, storage-facing) carries the extra reserved params. This avoids over-promising a facade-level payload-at-hold-time capability that was never a requirement.

### Pattern 3: `asyncio.Lock`-guarded dict-of-lists in-memory store

**What:** A single `asyncio.Lock` around the whole store's mutating operations (`place_hold`, `confirm_hold`, `release_hold`), matching `ARCHITECTURE.md`'s guidance that per-resource locks are an unneeded refinement for a test/dev-scoped backend.

**Example:**
```python
# Source: adapted from .planning/research/ARCHITECTURE.md Concurrency Model section (HIGH confidence)
import asyncio
from dataclasses import dataclass, field

@dataclass
class InMemoryStore:
    _resources: dict[str, "Resource"] = field(default_factory=dict)
    _holds: dict[str, "Hold"] = field(default_factory=dict)      # keyed by hold_id
    _bookings: dict[str, "Booking"] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def place_hold(self, resource_id, slot, capacity, ttl_seconds, payload=None, idempotency_key=None):
        async with self._lock:
            active = self._count_active(resource_id, slot)   # reads self._holds + self._bookings
            if active >= capacity:
                raise CapacityExhaustedError(resource_id, slot)
            hold = Hold(...)  # frozen dataclass, generate id, expires_at = now + ttl
            self._holds[hold.id] = hold
            return hold
```

This is the in-memory analog of ARCHITECTURE.md's Pattern 2 (SQL conditional-write) — the check-and-write happen inside the same critical section, closing the TOCTOU window (Pitfall 1) even though asyncio is single-threaded (the lock's real job here is guarding against interleaving across `await` points inside `_count_active`, not true parallelism).

### Anti-Patterns to Avoid (Phase-1-specific reminders from project pitfalls research)

- **Checking capacity outside the lock, writing inside it:** even in a single-process asyncio store, if `_count_active()` awaits anything (it shouldn't — it's pure dict reads — but a future refactor could add one), a second coroutine could interleave between the check and the write. Keep the entire check-and-write inside one `async with self._lock:` block with no `await` calls other than ones that don't yield control mid-check (Pitfall 1 applies even to in-memory correctness-of-contract, though the real proof is Phase 4's Postgres test).
- **`datetime.now()` or `datetime.utcnow()` anywhere in this phase's code:** always `datetime.now(timezone.utc)` (Pitfall 6). `datetime.utcnow()` is naive and deprecated.
- **Letting the `StorageBackend` Protocol leak `dict`-store internals** (e.g. returning the raw internal dict, or a mutable reference to a stored dataclass instead of the frozen value) — every getter must return the frozen `contracts.py` type (Pitfall 12).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Aware/naive datetime rejection | A custom `isinstance(dt.tzinfo, ...)` checker duplicated at every function boundary | Pydantic v2 `AwareDatetime` + one shared `AfterValidator` (Pattern 1) at the `contracts.py` layer; a single `require_utc()` guard function for any raw-datetime internal call sites not already Pydantic-typed | One shared implementation is auditable in one place; duplicated ad hoc checks are exactly how Pitfall 6 (naive/aware mixing) slips through in one forgotten call site |
| IANA timezone validation | Hand-rolled regex/allowlist of timezone strings | `zoneinfo.ZoneInfo(value)` inside a Pydantic validator — invalid IANA names raise `ZoneInfoNotFoundError` naturally | stdlib already has the full, current IANA database (with the `tzdata` package as an explicit fallback for minimal environments, deferred formally to Phase 2 per the decision map, but nothing prevents adding it now if `zoneinfo.available_timezones()` is empty on a dev machine) |
| Structural async-backend interface | An `ABC` requiring every backend to inherit from a shared base class | `typing.Protocol` + `@runtime_checkable` | Matches the D-04/locked "storage protocol" decision; lets a future SQL backend (Phase 4) or a consumer's own test fake satisfy the interface without inheritance |

**Key insight:** every "don't hand-roll" item in this phase reduces to the same principle already established at the project level (ARCHITECTURE.md/PITFALLS.md): put each correctness-critical check in exactly one shared function/type, never duplicated per call site.

## Common Pitfalls

### Pitfall: pytest-asyncio 1.x fixture/marker syntax differs from the 0.24.x line assumed in `STACK.md`

**What goes wrong:** Code or config written against pytest-asyncio 0.2x patterns (e.g. relying on the `event_loop` fixture, or `pytest.mark.asyncio(scope="module")`) breaks on 1.4.0 — `event_loop` fixture and `asyncio_event_loop` mark are removed.

**Why it happens:** The milestone-level `STACK.md` research snapshot (dated 2026-09-02) assumed the 0.24.x line; the actual current PyPI release is 1.4.0, a full major version ahead, published 2026-05-26 — this drift already happened before the STACK.md snapshot was even taken, meaning `STACK.md`'s version claim was stale at authoring time, not just aged since.

**How to avoid:** Pin `pytest-asyncio==1.4.0` (or whatever the plan verifies at execution time) explicitly, use `asyncio_mode = "auto"` in `pyproject.toml`'s `[tool.pytest.ini_options]` (unaffected by the 1.x changes), and for any fixture needing a specific loop scope, use `@pytest_asyncio.fixture(loop_scope="...")` — not the removed `event_loop` fixture pattern. Confirm this works with a single canary async test in Wave 0 before writing the rest of the suite.

**Warning signs:** Any test-writing task that copies an `event_loop` fixture override pattern from older tutorials/StackOverflow answers.

### Pitfall: mypy crossed a major version (1.13.x assumed → 2.3.1 actual)

**What goes wrong:** `mypy --strict` behavior or CLI flags could differ across a major version bump in ways this session did not independently verify (mypy 2.0's changelog was not read this session — `[ASSUMED]` no relevant breaking change for this project's `--strict` usage).

**How to avoid:** Run `mypy --strict src/` as an early Wave 0 smoke check against a trivial file before committing the codebase's typing style to it — cheap insurance against an unverified major-version assumption becoming a Wave-3 surprise.

**Warning signs:** `mypy --strict` producing errors on code patterns that worked under mypy 1.x (e.g. changed defaults around `--strict-equality` or plugin behavior) — verify at Wave 0, not after most of the phase's typed code exists.

### Pitfall: over-scoping Phase 1's `core/availability.py` into Phase 2's capacity-hardening work

**What goes wrong:** Because AVAIL-01 only requires "a structured available/booked result," it's tempting to fully build the sweep-line capacity accounting (AVAIL-02, explicitly Phase 2's requirement) in this phase, scope-creeping the walking skeleton into a horizontal build.

**Why it happens:** `ARCHITECTURE.md`'s Pattern 3 (sweep-line) is presented as "the one generalized primitive, build it right from day one" — correct architectural guidance, but the *capacity-K correctness proof* (a slot with J active holds reports exactly K−J remaining, property-tested) is explicitly Phase 2/AVAIL-02's success criterion, not Phase 1's.

**How to avoid:** Build the sweep-line primitive's *shape* now (since retrofitting the algorithm family later is more expensive than building it once, per ARCHITECTURE.md), but Phase 1's own verification only needs to prove the walking-skeleton path: define resource → grid → availability → hold/confirm/release works end to end for capacity ≥ 1 in the straightforward case. Defer property-based/edge-case capacity-K hardening tests to Phase 2 explicitly, so Phase 1's plan doesn't inherit Phase 2's Nyquist validation burden.

**Warning signs:** A Phase 1 plan task list that includes hypothesis-based property tests for capacity-K correctness — that's Phase 2 scope (`AVAIL-02` in the traceability table), not Phase 1's (`AVAIL-01` only).

## Code Examples

### Resource contract (Pydantic v2, honoring D-01/D-03/D-04)

```python
# Source: synthesized from D-01 (contract-types), D-03 (hours-shape), D-04-adjacent MODEL-* requirements
from datetime import time, timedelta
from enum import IntEnum
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, field_validator
import zoneinfo

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
    midnight-crossing GENERATION is deferred to Phase 2."""
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
    capacity: Annotated[int, Field(ge=1)]                       # MODEL-01
    operating_hours: dict[Weekday, list[LocalInterval]]          # MODEL-02, D-03
    buffer: timedelta = Field(default=timedelta(0))              # MODEL-03
    timezone: str                                                # MODEL-04

    @field_validator("timezone")
    @classmethod
    def _validate_iana(cls, v: str) -> str:
        try:
            zoneinfo.ZoneInfo(v)
        except zoneinfo.ZoneInfoNotFoundError as exc:
            raise ValueError(f"not a valid IANA timezone: {v!r}") from exc
        return v
```

### Facade signatures (Phase 1 scope — the consumer-visible surface)

```python
# Source: synthesized from ARCHITECTURE.md's engine.py facade pattern + D-04 forward-compat rule
class AvailabilityEngine:
    def __init__(self, storage: StorageBackend) -> None: ...

    async def define_resource(self, resource: Resource) -> None: ...

    async def get_availability(
        self, resource_id: str, start: UtcDatetime, end: UtcDatetime
    ) -> AvailabilityResult: ...

    async def place_hold(
        self, resource_id: str, slot_start: UtcDatetime, slot_end: UtcDatetime,
        ttl_seconds: int,
    ) -> Hold: ...

    async def confirm_hold(self, hold_id: str, payload: dict) -> Booking: ...

    async def release_hold(self, hold_id: str) -> None: ...
```

### `AvailabilityResult` output contract (AVAIL-01 shape)

```python
# Source: synthesized from D-01 + .planning/research/FEATURES.md "Output Contract" design notes
# (slot-list mode only in Phase 1 — free/busy merged-window mode is a v2/differentiator, out of scope)
from enum import Enum

class SlotStatus(str, Enum):
    AVAILABLE = "available"
    BOOKED = "booked"
    # NOTE: Phase 2 (AVAIL-02) needs the two-list available/booked split with an
    # explicit capacity_remaining int per FEATURES.md's capacity-shape gray area
    # (resolved in v1.0-DECISION-MAP.md Phase 2). Phase 1 may ship a single flat
    # list with a `status` field per slot as the walking-skeleton minimum, since
    # AVAIL-01 only requires "structured available/booked windows" — but choose
    # field names now that Phase 2 can extend additively (add capacity_remaining
    # as a new field) rather than restructure.

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

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| pytest-asyncio `event_loop` fixture override for custom loop scoping | `@pytest_asyncio.fixture(loop_scope="...")` / `pytest.mark.asyncio(loop_scope=...)` | pytest-asyncio 1.0 (this session confirms 1.4.0 is current, `[CITED: pytest-asyncio.readthedocs.io/en/stable/reference/changelog.html]`) | Any test-writing task referencing older async-fixture tutorials needs the updated syntax |
| `Pydantic v1` validators (`@validator`) | `field_validator` / `AfterValidator` (Pydantic v2, `Annotated`-based) | Already assumed throughout (D-01 locks Pydantic v2) | N/A — just confirming the v2-only API surface is what this research uses |

**Deprecated/outdated:** `datetime.utcnow()` — deprecated in Python 3.12+, returns a naive datetime; use `datetime.now(timezone.utc)` everywhere in this codebase (Pitfall 6, project-level PITFALLS.md).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | mypy 2.x's `--strict` flag has no breaking behavioral change relevant to this project's typing style vs. the 1.13.x line originally assumed | Standard Stack / Common Pitfalls | LOW-MEDIUM — would surface immediately as CI/lint failures in Wave 0's smoke check, cheap to catch early, not a silent correctness risk |
| A2 | Phase 1's `Resource.buffer` field can exist in the schema without being applied in `core/grid.py`'s slot overlay this phase (buffer enforcement deferred in spirit, though MODEL-03 requires the field to exist) | Phase Requirements / Architectural Responsibility Map | LOW — if the planner instead requires buffer to be functionally applied in Phase 1, that's a stricter reading of MODEL-03 than assumed here; confirm with the user/planner whether "set a buffer" (schema) or "buffer is enforced" (behavior) is the actual bar for this phase's success criteria |
| A3 | `place_hold`'s facade-level public signature does not need a `payload` parameter in Phase 1 (only `confirm_hold` does, per HOLD-03's wording), even though the Protocol layer reserves one defensively per D-04 | Architecture Patterns / Pattern 2 | LOW — if wrong, adding `payload` to the facade's `place_hold` later is additive (a new defaulted kwarg), not breaking, so the cost of being wrong here is small |

**If this table is empty:** N/A — see entries above; none of these bear on the frozen one-way contract shapes (D-01/D-03/D-04 fields themselves), only on secondary implementation choices the planner should confirm.

## Open Questions

1. **Does `Resource.buffer` need to be functionally applied in Phase 1's grid generation, or only present as a schema field?**
   - What we know: MODEL-03 requirement text is "Consumer can set a Resource's buffer/reset time enforced between consecutive sessions" — the word "enforced" suggests behavior, not just a settable field.
   - What's unclear: Phase 1's success criteria (ROADMAP.md) mention "generates a fixed-duration slot grid derived from the resource's operating hours + slot length + buffer" — this reads as buffer IS applied in Phase 1's grid generation, contradicting Assumption A2 above.
   - Recommendation: **Treat buffer as functionally applied in Phase 1's grid generation** (per ROADMAP.md success criterion #2, which explicitly lists "+ buffer" in the grid derivation) — this overrides Assumption A2; the planner should include a buffer-application task, using the "effective occupied interval" pattern from PITFALLS.md Pitfall 10 (buffer owned by the preceding booking's trailing edge) even in this simplified Phase 1 form.

2. **What is Phase 1's exact `Interval`/`Slot` field naming — is there a project convention already?**
   - What we know: No source code exists yet (confirmed in CONTEXT.md `<code_context>`); `ARCHITECTURE.md` suggests `Interval(start, end)` and `Slot` as separate types, but exact field names are explicitly Claude's Discretion per CONTEXT.md.
   - What's unclear: Nothing blocking — this is intentionally open per the CONTEXT.md discretion note.
   - Recommendation: Use `start`/`end` (not `begin`/`finish` or similar) for consistency with the half-open-interval literature cited throughout project research, and keep the internal `core.intervals.Interval` and the public `contracts.PublicSlot` as distinct types from the start (per ARCHITECTURE.md's Anti-Pattern 3 — never let one leak into the other's role).

## Environment Availability

No external service/tool dependencies for this phase — pure Python library code, in-memory backend only, no database, no Docker, no network calls. `uv` (package manager) and Python 3.12+ are assumed already available in the dev environment per the locked stack; not re-verified this session since they are prerequisites for even starting any phase of this project, not phase-1-specific.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"` in `pyproject.toml`) |
| Config file | none yet — Wave 0 creates `pyproject.toml`'s `[tool.pytest.ini_options]` block |
| Quick run command | `uv run pytest tests/ -x -q` |
| Full suite command | `uv run pytest tests/ -v` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MODEL-01 | Resource rejects capacity < 1 | unit | `pytest tests/test_contracts.py::test_resource_capacity_ge_1 -x` | ❌ Wave 0 |
| MODEL-02 | Resource accepts per-weekday list-of-intervals hours | unit | `pytest tests/test_contracts.py::test_resource_operating_hours_shape -x` | ❌ Wave 0 |
| MODEL-03 | Resource buffer field present, applied in grid generation | unit | `pytest tests/core/test_grid.py::test_buffer_applied -x` | ❌ Wave 0 |
| MODEL-04 | Resource rejects non-IANA timezone string | unit | `pytest tests/test_contracts.py::test_resource_timezone_validation -x` | ❌ Wave 0 |
| MODEL-05 | Interval/Slot/Hold immutable, half-open | unit | `pytest tests/core/test_intervals.py::test_frozen_and_half_open -x` | ❌ Wave 0 |
| GRID-01 | Grid generation from hours+slot_length+buffer produces expected slots | unit | `pytest tests/core/test_grid.py::test_grid_slots_basic -x` | ❌ Wave 0 |
| GRID-04 | Naive datetime input raises ValidationError at every boundary type | unit | `pytest tests/test_contracts.py::test_naive_datetime_rejected -x` | ❌ Wave 0 |
| AVAIL-01 | `get_availability()` returns structured available/booked slots | integration | `pytest tests/test_engine.py::test_get_availability_end_to_end -x` | ❌ Wave 0 |
| STORE-01 | `StorageBackend` Protocol satisfied structurally by `InMemoryStore` | unit | `pytest tests/storage/test_protocol_conformance.py::test_inmemory_satisfies_protocol -x` | ❌ Wave 0 |
| STORE-02 | `InMemoryStore` CRUD round-trips resource/hold/booking | unit | `pytest tests/storage/contract_suite.py -x` (parametrized, in-memory only) | ❌ Wave 0 |
| HOLD-01 | `place_hold` rejects when capacity exhausted | unit | `pytest tests/test_engine.py::test_place_hold_capacity_exhausted -x` | ❌ Wave 0 |
| HOLD-03 | `confirm_hold` round-trips opaque payload untouched | unit | `pytest tests/test_engine.py::test_confirm_hold_payload_roundtrip -x` | ❌ Wave 0 |
| HOLD-04 | `release_hold` frees capacity immediately, is idempotent | unit | `pytest tests/test_engine.py::test_release_hold_frees_capacity -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `uv run pytest tests/ -x -q` (quick run)
- **Per wave merge:** `uv run pytest tests/ -v` (full suite)
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `pyproject.toml` — `[tool.pytest.ini_options]` with `asyncio_mode = "auto"`, plus `[project]`/`[tool.hatch.build]` scaffolding
- [ ] `tests/conftest.py` — shared fixtures (an `InMemoryStore` fixture, a sample `Resource` fixture)
- [ ] `tests/storage/contract_suite.py` — the shared parametrized suite skeleton (parametrize over `[InMemoryStore]` only in Phase 1; designed so Phase 4 adds `SQLStore` params without rewriting existing test bodies)
- [ ] Framework install: `uv add --dev pytest==9.1.1 pytest-asyncio==1.4.0 ruff==0.16.6 mypy==2.3.1` (exact pins per D-06's re-verify-at-implementation-time instruction) — **confirm these exact pins are still current immediately before running this command**, since PyPI publishes continuously and this session's snapshot is from 2026-09-03
- [ ] Canary test: one trivial `async def test_canary(): assert True` under `pytest.mark.asyncio` to confirm pytest-asyncio 1.4.0's config works before writing real async tests

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | No | This is a library with no authentication surface of its own — auth is a consumer concern (explicitly out of scope per REQUIREMENTS.md "Out of Scope") |
| V3 Session Management | No | No sessions; holds are not sessions |
| V4 Access Control | No | No access-control surface — the engine has no notion of "who" (opaque payload only) |
| V5 Input Validation | Yes | Pydantic v2 at every public boundary type (D-01) — rejects naive datetimes, non-IANA timezones, capacity < 1, malformed operating-hours shapes, all via typed validators rather than ad hoc checks |
| V6 Cryptography | No | No cryptographic operations in this phase — no secrets, no signing, no encryption surface |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|----------------------|
| Malformed/malicious `dict` payload injected at `confirm_hold`, later reflected into logs or error messages | Information Disclosure | Per PITFALLS.md's Security Mistakes table: treat the opaque payload as fully opaque even in logging/error paths — log only its presence/size/type, never its contents. Apply this from Phase 1 since `confirm_hold` ships this phase (HOLD-03) |
| Naive/malformed datetime input crossing the trust boundary from an untrusted consumer | Tampering (implicit — a caller manipulating what "now" means) | Pydantic `AwareDatetime` + UTC-enforcement validator at every input boundary (GRID-04) rejects the input outright rather than silently coercing it — this is itself the mitigation, not a separate control |
| A future SQL/driver exception (not yet applicable in Phase 1, but worth establishing the pattern now) leaking implementation details through the public API | Information Disclosure | Not yet in scope (in-memory only this phase, no DB), but establish the `errors.py` domain-exception convention now (`CapacityExhaustedError`, `HoldExpiredError`, `HoldNotFoundError`) so Phase 4's SQL backend has an existing pattern to wrap driver exceptions into, per PITFALLS.md Pitfall 12/Security Mistakes |

## Sources

### Primary (HIGH confidence)
- `[VERIFIED: PyPI registry]` — direct `curl https://pypi.org/pypi/<package>/json` queries against the authoritative PyPI JSON API for pydantic, ruff, mypy, pytest, pytest-asyncio — exact current versions and publish dates, 2026-09-03
- `.planning/research/ARCHITECTURE.md` — project-level architecture research (HIGH confidence, established CS/DB patterns)
- `.planning/research/PITFALLS.md` — project-level pitfalls research (MEDIUM-HIGH, cross-checked)
- Python stdlib docs (`datetime`, `zoneinfo`, `typing.Protocol`, `dataclasses`) — training-knowledge-level, standard and stable APIs, not independently re-fetched this session

### Secondary (MEDIUM confidence)
- WebSearch: "Pydantic v2 field_validator reject naive datetime require UTC AwareDatetime" — cross-referenced GitHub issues (pydantic/pydantic#8859, #6843) confirming `AwareDatetime`'s `timezone_aware` error behavior and the date-only-string gotcha
- WebSearch: "pytest-asyncio 1.0 migration guide asyncio_mode breaking changes" — pytest-asyncio official changelog (readthedocs.io) confirming 1.4.0 is current and documenting the `event_loop` fixture removal

### Tertiary (LOW confidence)
- None used as load-bearing claims in this document — the mypy 2.x behavioral-compatibility assumption (A1) is flagged explicitly in the Assumptions Log rather than presented as verified.

## Metadata

**Confidence breakdown:**
- Standard stack (version pins): HIGH — verified directly against PyPI's authoritative JSON API this session
- Architecture (Protocol/contract shapes): HIGH — directly extends already-HIGH-confidence project-level ARCHITECTURE.md, narrowed to Phase 1 scope
- Pydantic validator patterns: MEDIUM — cross-referenced via WebSearch against GitHub issues, not fetched from live official docs (no Context7/docs MCP tool available this session)
- Pitfalls: HIGH — inherits project-level PITFALLS.md (MEDIUM-HIGH) plus phase-specific version-drift findings verified this session

**Research date:** 2026-09-03
**Valid until:** 2026-10-03 (30 days — stable domain, but re-verify exact version pins again immediately before `pyproject.toml` is written, since pytest/pytest-asyncio/mypy all show active release cadence)
