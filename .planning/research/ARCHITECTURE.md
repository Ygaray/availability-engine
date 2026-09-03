# Architecture Research

**Domain:** Domain-agnostic async scheduling/availability engine (Python library)
**Researched:** 2026-09-02
**Confidence:** HIGH (established CS/DB patterns; SQLite-specific concurrency claims cross-checked via web search — MEDIUM-verified, noted inline)

## Standard Architecture

### System Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                         CONSUMER (chatbot etc.)                       │
│               awaits AvailabilityEngine methods only                  │
└───────────────────────────────┬────────────────────────────────────-─┘
                                 │  (contract: dataclasses in contracts.py)
┌────────────────────────────────▼───────────────────────────────────--─┐
│                       PUBLIC FACADE — engine.py                        │
│   AvailabilityEngine: get_availability() / place_hold() / confirm() /  │
│   release()  — orchestrates below, owns NO locking/atomicity itself    │
└───────┬───────────────────────────┬───────────────────────┬──────────-┘
        │                           │                       │
┌───────▼────────┐   ┌──────────────▼───────────┐  ┌────────▼─────────┐
│  TIME BOUNDARY  │   │      COMPUTE CORE         │  │  DOMAIN OBJECTS  │
│   time.py       │   │  core/intervals.py        │  │  contracts.py    │
│  IANA + DST →   │   │  core/availability.py     │  │  Resource, Slot, │
│  UTC Interval   │   │  core/grid.py             │  │  Hold, Booking,  │
│  (boundary-only,│   │  pure fns, no I/O, no tz  │  │  AvailabilityRes │
│   core never    │   │  operates only on UTC     │  │  (frozen, no     │
│   sees tz)      │   │  Interval value objects   │  │   behavior)      │
└─────────────────┘   └────────────────────────────┘  └───────────────-┘
                                 │
                                 │ (async calls — coarse, atomic ops only)
┌────────────────────────────────▼───────────────────────────────────--─┐
│                    STORAGE PROTOCOL — storage/protocol.py               │
│   typing.Protocol: get_resource, get_active_entries, place_hold,       │
│   confirm_hold, release_hold, expire_holds — each call = one atomic    │
│   operation; NO transaction object exposed across this boundary        │
└───────┬─────────────────────────────────────────────┬────────────────-┘
        │                                              │
┌───────▼─────────────┐                    ┌───────────▼──────────────┐
│  InMemoryStore        │                    │  SQLStore                 │
│  storage/memory.py    │                    │  storage/sql/*.py         │
│  dict + asyncio.Lock  │                    │  SQLAlchemy Core AsyncEng │
│  reference impl + test│                    │  same SQL templates over  │
│  double               │                    │  SQLite (aiosqlite) and   │
│                        │                    │  Postgres (asyncpg)       │
└───────────────────────┘                    └───────────────────────---┘
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| Domain/contract objects (`contracts.py`) | Immutable data shapes for inputs/outputs — the actual "contract-first" surface a consumer codes against | Frozen `@dataclass(slots=True, frozen=True)`; no behavior, no I/O |
| Time boundary (`time.py`) | Converts per-resource IANA local wall-clock hours → concrete UTC `Interval`s, per calendar date | `zoneinfo.ZoneInfo` + `datetime`; called only at the facade edge |
| Compute core (`core/`) | Pure interval algebra + capacity-aware sweep-line + grid overlay; answers "what's free" given already-UTC inputs | Plain functions/classes, zero I/O, zero tz-awareness, 100% unit-testable |
| Storage protocol (`storage/protocol.py`) | Defines the atomic operations a backend MUST provide; the seam where atomicity is guaranteed | `typing.Protocol` (structural, `@runtime_checkable`) |
| Storage impls (`storage/memory.py`, `storage/sql/`) | Satisfy the protocol; own all locking/transactional detail | `asyncio.Lock` (memory) / single conditional SQL statement (SQL) |
| Public facade (`engine.py`) | Orchestrates domain + time + core + storage into one async API; the only thing the consumer imports and calls | Thin coordinating class, no locking logic of its own |

## Recommended Project Structure

```
src/
└── availability_engine/
    ├── __init__.py              # exports: AvailabilityEngine + everything in contracts.py
    ├── contracts.py             # Resource, Interval, Hold, Booking, Slot, AvailabilityResult (the contract-first surface)
    ├── errors.py                # CapacityExhaustedError, HoldExpiredError, HoldNotFoundError, InvalidTimezoneError
    ├── time.py                  # localize_operating_hours(), to_utc()/require_utc() guards
    ├── core/
    │   ├── intervals.py         # half-open Interval value object + merge/subtract/intersect
    │   ├── availability.py      # sweep-line, capacity-aware: operating_hours - (buffers ∪ holds ∪ bookings)
    │   └── grid.py              # fixed-duration slot overlay on top of core.availability fragments
    ├── storage/
    │   ├── protocol.py          # StorageBackend(Protocol) — the async contract
    │   ├── memory.py            # InMemoryStore(StorageBackend)
    │   └── sql/
    │       ├── schema.py        # SQLAlchemy Core Table defs, shared by both dialects
    │       ├── backend.py       # SQLStore(StorageBackend) wrapping AsyncEngine
    │       └── statements.py    # the atomic INSERT/UPDATE statement builders (the crux logic)
    └── engine.py                 # AvailabilityEngine facade

tests/
├── storage/
│   └── contract_suite.py        # ONE shared async test suite, parametrized over
│                                 # InMemoryStore / SQLStore(sqlite) / SQLStore(postgres)
├── core/
│   ├── test_intervals.py
│   └── test_availability.py     # capacity-aware sweep-line, buffer edge cases
└── test_time_boundary.py        # DST transition dates, ambiguous/nonexistent local times
```

### Structure Rationale

- **`contracts.py` is deliberately its own module**, importable with zero side effects (no storage/tz dependencies pulled in) — this is what the consumer git-tag-pins against on day one, before any real logic exists.
- **`core/` has no imports from `storage/` or `time.py`'s tz machinery** — this is the enforcement mechanism for "core stays tz-agnostic and I/O-free," not just a convention. A core module importing `zoneinfo` or an async DB driver is a structural violation to catch in review.
- **`storage/sql/statements.py` isolated from `storage/sql/backend.py`** — keeps the one genuinely tricky piece of SQL (the atomic conditional insert) in a single small, heavily-tested file, separate from connection/engine plumbing.
- **One `contract_suite.py` run against all backends** — this is the concrete mechanism that proves InMemoryStore and SQLStore are truly interchangeable, and that the consumer's own fake (built against the same Protocol) will behave the same way.

## Architectural Patterns

### Pattern 1: Coarse-grained, atomic-by-construction Storage Protocol

**What:** The `StorageBackend` Protocol exposes only whole-operation methods (`place_hold`, `confirm_hold`, `release_hold`) — never primitives like `get_active_count` + `insert` that a caller could compose with a race window in between.

**When to use:** Any time atomicity must live in the backend while the engine stays backend-agnostic. This is the core structural answer to "how does atomicity live in the backend but the engine stays backend-agnostic."

**Trade-offs:** Slightly less flexible protocol (can't mix-and-match sub-steps), but it's the only way to make "atomic" a property the Protocol can actually guarantee rather than something callers must remember to enforce.

**Example:**
```python
from typing import Protocol, runtime_checkable
from datetime import datetime

@runtime_checkable
class StorageBackend(Protocol):
    async def get_resource(self, resource_id: str) -> Resource | None: ...

    async def get_active_entries(
        self, resource_id: str, window: Interval
    ) -> list[Hold | Booking]: ...

    async def place_hold(
        self, resource_id: str, slot: Interval, capacity: int,
        ttl_seconds: int, payload: object | None = None,
    ) -> Hold:
        """Atomically insert iff active-hold+booking count < capacity for this slot.
        Raises CapacityExhaustedError otherwise. Single round trip; no separate
        read-then-write in caller code."""

    async def confirm_hold(self, hold_id: str, payload: object | None = None) -> Booking:
        """Atomically transition hold -> booking iff still active and unexpired.
        Raises HoldExpiredError / HoldNotFoundError otherwise."""

    async def release_hold(self, hold_id: str) -> None:
        """Idempotent explicit release."""

    async def expire_holds(self, before: datetime, resource_id: str | None = None) -> int:
        """Best-effort GC of expired rows. Never load-bearing for correctness —
        correctness comes from the expires_at predicate other methods already apply."""
```

Deliberately no `transaction()` context manager in v1 — every method IS its own transaction. Add one later only if a real multi-step orchestration need appears; don't design it in speculatively.

### Pattern 2: Conditional write instead of explicit row lock (the SQLite+Postgres portability trick)

**What:** Instead of `SELECT ... FOR UPDATE` then `INSERT` (two round trips, needs row-level locking), embed the capacity check as a `WHERE`/subquery clause **inside** the single write statement. The statement's own atomicity (guaranteed by every SQL engine, including SQLite) is the lock.

**When to use:** Any "atomic conditional insert if capacity remains" requirement that must be portable across a database with real row-level locking (Postgres) and one without it (SQLite has database-level, not row-level, locking — confirmed via web search: SQLite doesn't support `SELECT ... FOR UPDATE`, and `with_for_update()` renders as a no-op on the SQLite dialect).

**Trade-offs:** Slightly less idiomatic-looking SQL than `FOR UPDATE`, but it's the one pattern that produces byte-identical semantics on both backends without dialect-specific branches in this library's Python code.

**Example (SQLAlchemy Core, dialect-agnostic):**
```python
from sqlalchemy import select, func, insert, and_, or_

active_count = (
    select(func.count())
    .select_from(holds_and_bookings_view)
    .where(
        holds_and_bookings_view.c.resource_id == resource_id,
        holds_and_bookings_view.c.slot_start == slot.start,
        or_(
            holds_and_bookings_view.c.status == "confirmed",
            and_(
                holds_and_bookings_view.c.status == "active",
                holds_and_bookings_view.c.expires_at > now,
            ),
        ),
    )
    .scalar_subquery()
)

stmt = (
    insert(holds_table)
    .from_select(
        ["id", "resource_id", "slot_start", "slot_end", "status", "expires_at"],
        select(
            bindparam("id"), bindparam("resource_id"),
            bindparam("slot_start"), bindparam("slot_end"),
            literal("active"), bindparam("expires_at"),
        ).where(active_count < capacity),
    )
)
result = await conn.execute(stmt, params)
if result.rowcount == 0:
    raise CapacityExhaustedError(resource_id, slot)
```

This is a single statement: the DB either inserts a row or inserts nothing, with no window where another connection can observe a stale count. `confirm_hold` uses the same idea with `UPDATE ... WHERE id = :id AND status = 'active' AND expires_at > :now`, checking `rowcount == 1`.

**Optional Postgres-only enhancement:** under heavy contention you *may* additionally wrap the statement in `SELECT ... FOR UPDATE` on a per-slot row to serialize contenders and reduce wasted retries — but this is an internal optimization behind the same Protocol method, invisible to the engine, and not required for correctness. Don't build it until a benchmark says you need it.

### Pattern 3: Sweep-line capacity accounting as the one generalized availability primitive

**What:** Model every active hold/booking as a `(+1 at start, -1 at end+buffer)` event pair. Sort all events for the query window, sweep left to right accumulating a running "in-use count," and a moment is available iff `count < capacity`. Intersect the resulting "under-capacity" sub-intervals with `operating_hours`. Fixed-grid slots (v1) are then a thin overlay: walk the free fragments in `slot_duration` steps and emit a slot only where a full `slot_duration` fits.

**When to use:** This is the answer to "capacity-aware, so grid-now/continuous-later share one core." Binary interval-subtraction (`free = hours - busy`) only works for `capacity == 1`; sweep-line count generalizes it for free (capacity 1 degenerates to the same subtraction result), so build it this way from day one rather than special-casing capacity 1 now and rewriting for capacity > 1 later. The project's own requirements already ask for capacity ≥ 1 in v1, so this isn't optional future-proofing — it's required now.

**Trade-offs:** Marginally more code than plain interval subtraction, but it's the same amount of code whether capacity is 1 or 50, and it's the same core function whether the caller wants a fixed grid or continuous windows — grid vs continuous is purely a decision made in `core/grid.py`, one layer above.

**Example:**
```python
def free_fragments(
    operating_hours: list[Interval], busy: list[Interval], capacity: int,
) -> list[Interval]:
    events = sorted(
        [(iv.start, +1) for iv in busy] + [(iv.end, -1) for iv in busy]
    )
    under_capacity: list[Interval] = []
    count = 0
    cursor = None
    for ts, delta in events:
        if count < capacity and cursor is not None:
            under_capacity.append(Interval(cursor, ts))
        count += delta
        cursor = ts if count < capacity else None
    # ... intersect under_capacity with operating_hours (standard interval intersection)
    return intersect_all(operating_hours, under_capacity)

def grid_slots(fragments: list[Interval], slot_duration: timedelta) -> list[Interval]:
    slots = []
    for frag in fragments:
        cursor = frag.start
        while cursor + slot_duration <= frag.end:
            slots.append(Interval(cursor, cursor + slot_duration))
            cursor += slot_duration
    return slots

def continuous_windows(fragments: list[Interval]) -> list[Interval]:
    return fragments  # v2+: no grid overlay, return fragments directly
```

Buffers are applied by extending each busy interval's effective end by the resource's buffer before generating events — a one-line change to event construction, not a change to the sweep algorithm.

## Data Flow

### Read flow — `get_availability(resource_id, date_range)`

```
consumer.get_availability(resource_id, range)
    ↓
engine.py: load Resource via storage.get_resource()
    ↓
engine.py: fetch active holds+bookings in range via storage.get_active_entries()
    (storage applies the expires_at > now filter here — lazy expiry happens
     as part of this read, no separate expire step)
    ↓
time.py: localize_operating_hours(resource, range) → UTC Interval[] per day
    ↓
core/availability.py: sweep-line(operating_hours, busy=holds+bookings, capacity)
    → free Interval[]
    ↓
core/grid.py: grid_slots(free, resource.slot_duration)   [v1: always applied]
    ↓
engine.py: wrap into AvailabilityResult (contracts.py dataclass) — UTC datetimes,
    no tz conversion for the consumer's benefit (that's their concern)
    ↓
return to consumer
```

### Write flow — `place_hold(resource_id, slot)` → `confirm(hold_id)`

```
consumer.place_hold(resource_id, slot)
    ↓
engine.py: load Resource via storage.get_resource()  (need its capacity + validate slot aligns to grid)
    ↓
engine.py: storage.place_hold(resource_id, slot, capacity, ttl, payload)
    ↓ (single atomic statement inside the backend — Pattern 2 above)
storage/sql/statements.py: INSERT ... SELECT ... WHERE active_count < capacity
    ↓
rowcount == 1 → Hold object returned          rowcount == 0 → CapacityExhaustedError
    ↓
consumer.confirm(hold_id, payload)
    ↓
storage.confirm_hold(hold_id, payload)
    ↓ (single atomic statement)
UPDATE holds SET status='confirmed' WHERE id=:id AND status='active' AND expires_at > :now
    ↓
rowcount == 1 → Booking object returned       rowcount == 0 → HoldExpiredError
```

Note the engine never sees or manages a transaction object anywhere in this flow — every arrow crossing the storage boundary is exactly one atomic call.

### Key Data Flows

1. **Timezone conversion happens exactly once, at the facade boundary, per concrete date range** — never cached indefinitely, never repeated inside the core. This is what makes DST correctness tractable: each date's local→UTC mapping is computed fresh against that date's actual offset.
2. **Lazy expiry is a read-time/write-time predicate, not a state transition** — no code path ever "marks a hold expired." Every query that cares about active holds includes `expires_at > :now` in its own WHERE clause; an expired hold simply stops being counted, which is indistinguishable from having been deleted, without requiring a delete.

## Time Handling Architecture

- **Internal representation:** every `datetime` inside `core/`, `storage/`, and the wire contract is timezone-aware UTC. Naive datetimes are a bug — validate and reject them at every public entry point (`require_utc(dt)` guard raising `ValueError`).
- **Resource configuration:** `Resource.timezone: str` (IANA name) + per-day operating hours expressed as **local wall-clock `time` objects** (how a human configures a resource — "9am–5pm"), not pre-converted UTC. This is the only place local time appears in stored data.
- **Boundary conversion:** `time.py::localize_operating_hours(resource, date_range) -> list[Interval]` is the single function that turns local wall-clock + IANA zone + a concrete calendar date into a UTC `Interval`. It is called by `engine.py` right before invoking `core/availability.py`, and nowhere else — the core package has no `zoneinfo` import at all, which is both a design principle and an enforceable lint/import-boundary rule.
- **DST correctness:** because conversion is per-date (not memoized globally), a resource's "9am–5pm" on either side of a DST transition correctly resolves to different UTC offsets on each date. Flag as an explicit edge case to test: the "spring forward" day where a local wall-clock hour doesn't exist, and the "fall back" day where one is ambiguous (occurs twice) — use `zoneinfo`'s `fold` attribute deliberately (document the chosen default, e.g. `fold=0`) rather than leaving Python's default behavior implicit and undocumented.
- **Output boundary:** the structured `AvailabilityResult` contract carries UTC datetimes only (ISO 8601 with explicit offset/`Z`). Localizing for display is the consumer's job — the engine doesn't know the end user's locale, only the resource's operating zone. This keeps the contract stable regardless of which humans, in which timezones, end up querying it.

## Concurrency Model

- Everything public is `async def`; the facade and Protocol are async top to bottom, matching an async consumer (chatbot backend).
- **The engine performs no locking.** All atomicity lives in storage impls, reached only through the coarse Protocol methods (Pattern 1). This is a structural, not just documented, boundary: if a race condition can only be prevented by code running in `engine.py`, the Protocol is mis-designed.
- **InMemoryStore:** a single `asyncio.Lock` guarding the whole store is sufficient — it's a single-process, test/dev-scoped implementation; per-resource locks are a possible refinement but add complexity the test suite doesn't need.
- **SQLStore:** correctness comes entirely from the database's own single-statement atomicity (Pattern 2); no Python-level lock is needed or should be added, since it wouldn't hold across multiple OS processes anyway.
- **SQLite reality check (web-search verified, MEDIUM confidence):** SQLite allows exactly one writer at a time even in WAL mode — WAL only lets readers proceed concurrently with a writer, it does **not** enable concurrent writers. A second `place_hold` attempt against SQLite while one is in flight will block (or raise `SQLITE_BUSY` without a sufficient `busy_timeout`) until the first transaction completes, then proceed. Configure `PRAGMA journal_mode=WAL` and a generous `PRAGMA busy_timeout` (e.g. 5000ms) on every SQLite connection, and use a single serialized connection/pool (`NullPool` or `pool_size=1`) rather than a real connection pool, since a pool can't buy real write concurrency SQLite doesn't have anyway.
- **What "one SQL impl spanning SQLite + Postgres" actually means:** it is the same Python code and the same SQL statement templates (SQLAlchemy Core handles the minor dialect syntax differences) — not the same concurrency ceiling. Postgres allows genuinely concurrent writers via row-level MVCC (different resources'/slots' rows don't block each other); SQLite serializes ALL writes globally regardless of which rows they touch. Both are equally **correct** — no double-booking under concurrent load in either — because correctness is a property of the atomic statement (Pattern 2), not of how many writers can proceed in parallel. Document SQLite explicitly as "correct, lower throughput ceiling; fine for local dev and low/medium-traffic prod," matching the project's own SQLite-for-dev / Postgres-for-prod framing.

## Anti-Patterns

### Anti-Pattern 1: Read-then-write capacity check in application code

**What people do:** `count = await storage.count_active(resource_id, slot); if count < capacity: await storage.insert_hold(...)`.

**Why it's wrong:** Classic TOCTOU race — two concurrent callers can both pass the count check before either inserts, double-booking the last unit of capacity. This is true regardless of async/await; it's a logical race, not a threading one.

**Do this instead:** Push the check into the WHERE clause of the write itself (Pattern 2), so the check and the write are the same atomic operation.

### Anti-Pattern 2: A background sweeper task for hold expiry

**What people do:** Spin up an `asyncio.Task` or scheduled job inside the library that periodically deletes expired holds.

**Why it's wrong:** A library shouldn't own a runtime lifecycle — who starts/stops it, what happens across multiple worker processes, what happens if it crashes silently. This is an explicit out-of-scope decision for this project.

**Do this instead:** Treat "expired" as a query predicate (`expires_at > now`) applied everywhere active holds are read or capacity is checked (Pattern in Data Flow). Expose `expire_holds()` as an optional, consumer-triggered GC call for table hygiene — never load-bearing for correctness.

### Anti-Pattern 3: Letting the Storage Protocol leak an ORM's session/model objects

**What people do:** `StorageBackend.place_hold()` returns a SQLAlchemy ORM instance, or accepts a `Session` parameter.

**Why it's wrong:** Couples the Protocol to one backend's object model, defeats the point of a backend-agnostic contract, and makes `InMemoryStore` awkward to implement (it has no session to return an instance from).

**Do this instead:** Protocol methods only ever accept/return this library's own frozen dataclasses (`contracts.py`). SQL-specific rows are converted to/from those dataclasses entirely inside `storage/sql/`.

### Anti-Pattern 4: Treating capacity > 1 as N repeated binary interval-subtractions

**What people do:** Loop capacity times doing plain `free = hours - busy` per "unit."

**Why it's wrong:** Doesn't generalize cleanly, produces O(capacity) unclear code, and re-implements what the sweep-line model already gives you correctly and generally.

**Do this instead:** Use the sweep-line event-count primitive (Pattern 3) as the one algorithm for all capacity values, including capacity 1.

### Anti-Pattern 5: Caching a timezone's UTC offset instead of converting per date

**What people do:** Compute a resource's UTC offset once (e.g. at startup or resource-load time) and reuse it for every date's availability computation.

**Why it's wrong:** Silently produces wrong results for any date on the other side of a DST transition from when the offset was cached — a scheduling engine's worst possible failure mode because it's silent, not a crash.

**Do this instead:** Always resolve local→UTC per concrete calendar date via `zoneinfo`, at the boundary, for the specific dates being queried.

## Scaling Considerations

This is a library, not a service — "scaling" here means storage-backend choice and schema/indexing, not the library scaling itself.

| Concern | Low volume (dev / small prod) | Medium/high volume prod | Very high QPS |
|---------|-------------------------------|--------------------------|----------------|
| Storage backend | SQLite + WAL — single-writer ceiling not yet a bottleneck | Postgres — row-level MVCC lets unrelated resources' writes proceed concurrently | Postgres, tuned connection pool sized to deploy; consider the optional `FOR UPDATE` refinement (Pattern 2) only if benchmarks show contention |
| Indexing | Not critical at this scale | Composite index on `(resource_id, slot_start, status)` on both holds and bookings tables — required for the capacity-check subquery to stay fast | Same index, monitored under real query plans |
| Hold table growth | Irrelevant at low volume | Call `expire_holds()` on the consumer's own schedule (their cron, not this library's) to bound row growth | Same, tuned frequency |

### Scaling Priorities

1. **First bottleneck:** SQLite's single-writer serialization under concurrent `place_hold` calls in a busy prod deployment — the documented mitigation is "move to Postgres," not any code change in this library, since the same SQL statements already work against both.
2. **Second bottleneck:** Missing/incorrect indexes on `(resource_id, slot_start, status)` making the capacity-check subquery a full scan as the holds/bookings tables grow — call this out as a required schema decision in the phase that builds `storage/sql/schema.py`, not an afterthought.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| SQLite (via `aiosqlite`) | SQLAlchemy Core `AsyncEngine` with `sqlite+aiosqlite://` | Set `PRAGMA journal_mode=WAL` + `PRAGMA busy_timeout` on connect; use a single serialized connection, not a real pool |
| PostgreSQL (via `asyncpg`) | SQLAlchemy Core `AsyncEngine` with `postgresql+asyncpg://` | Normal pooled connections; same statement templates as SQLite, dialect differences absorbed by SQLAlchemy |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| Consumer ↔ `engine.py` | Direct async method calls, `contracts.py` dataclasses in/out | This is the entire public API surface and the contract-first artifact |
| `engine.py` ↔ `core/` | Direct function calls, UTC `Interval`/domain objects only | No I/O crosses this boundary in either direction |
| `engine.py` ↔ `time.py` | Direct function calls at the facade edge only | `core/` never imports `time.py`'s tz machinery |
| `engine.py` ↔ `storage/protocol.py` | `await` on Protocol methods, coarse/atomic operations only | This is the pluggable seam; `engine.py` is written against the Protocol type, never a concrete backend |
| `storage/memory.py` / `storage/sql/*` ↔ `storage/protocol.py` | Structural typing (`Protocol`, `@runtime_checkable`) — no inheritance required | Lets the consumer's own test fake satisfy the same Protocol without importing this library's base classes |

## Sources

- [SQLAlchemy: SQLite doesn't support SELECT FOR UPDATE / with_lockmode() is a no-op on SQLite dialect](https://groups.google.com/g/sqlalchemy/c/RIBdLP_s6hk) — MEDIUM confidence (community discussion, corroborated by SQLAlchemy dialect docs behavior)
- [SQLAlchemy `with_for_update()` — works on Postgres/MySQL, not SQLite](https://testdriven.io/tips/5ce50ece-eaeb-496f-8339-c871c00781c4/) — MEDIUM confidence
- [SQLite WAL mode: multiple readers + single writer only, no concurrent writers](https://sqlite.org/forum/info/b4e8b29ae409cd198652c6b7e70b53b702f269e67e1d2573d627feeba37bbf85) — MEDIUM confidence, corroborates SQLite official documentation behavior
- [SQLite concurrent writes and "database is locked" errors — WAL/busy_timeout practical guidance](https://tenthousandmeters.com/blog/sqlite-concurrent-writes-and-database-is-locked-errors/) — MEDIUM confidence
- [Single-writer database architecture with SQLite](https://www.bugsink.com/blog/database-transactions/) — MEDIUM confidence
- Interval algebra (half-open intervals, sweep-line event counting for interval scheduling/capacity problems), `typing.Protocol` for structural backend interfaces, and `zoneinfo`-based per-date DST-correct conversion are standard, stable Python/CS patterns — HIGH confidence from established practice, not narrowly source-dependent.

---
*Architecture research for: domain-agnostic async availability/scheduling engine*
*Researched: 2026-09-02*
