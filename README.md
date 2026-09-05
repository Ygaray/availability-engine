# availability-engine

A reusable, **domain-agnostic Python scheduling library** that models `resources × time-slots ×
holds` and emits structured `available` / `booked` outputs. It answers two questions safely and
deterministically — *"what's available?"* and *"can I take this slot, atomically?"* — while naming
**zero** domain concepts (no "room", "escape", "appointment"); the domain is injected by the
consumer.

This document is the **stable, documented product surface**: the async and sync engine facades,
the storage protocol, the output contract, the concurrency guarantees actually proven against real
Postgres, and the TZ/DST semantics actually proven against fixture-tested transition dates. Every
code example below is exercised by an automated test (`tests/test_readme_examples.py`) — this is
not a manual-read-through doc.

## Install

```bash
uv add "availability-engine @ git+https://github.com/Ygaray/availability-engine" --tag v0.1.0
```

Requires **Python 3.12+**. Consumed via git-tag pin, matching the reusable-ecosystem convention —
no PyPI publish for v1.

## Engine facade

The engine ships in two flavors over the same `StorageBackend` Protocol: an async facade
(`AvailabilityEngine`) for async consumers, and a thin synchronous bridge
(`SyncAvailabilityEngine`) for callers — including callers already inside their own running event
loop — that need a plain synchronous call sequence.

### Async: `AvailabilityEngine`

```python
from datetime import UTC, datetime, time, timedelta

from availability_engine import AvailabilityEngine, LocalInterval, Resource, Weekday
from availability_engine.storage.memory import InMemoryStore

engine = AvailabilityEngine(InMemoryStore())

resource = Resource(
    id="table-1",
    capacity=1,
    operating_hours={
        Weekday.MONDAY: [LocalInterval(start=time(9, 0), end=time(17, 0))],
    },
    buffer=timedelta(minutes=0),
    timezone="America/Chicago",
    slot_duration=timedelta(minutes=30),
)
await engine.define_resource(resource)

result = await engine.get_availability(
    "table-1",
    datetime(2026, 9, 7, 0, 0, tzinfo=UTC),
    datetime(2026, 9, 8, 0, 0, tzinfo=UTC),
)
slot = result.available[0]

hold = await engine.place_hold(resource.id, slot.start, slot.end, ttl_seconds=60)
booking = await engine.confirm_hold(hold.id, payload={"order_id": "abc-123"})
await engine.cancel_booking(booking.id)
```

### Sync: `SyncAvailabilityEngine`

`src/availability_engine/sync.py` runs the async engine on a dedicated background thread with its
own persistent event loop, dispatched via `asyncio.run_coroutine_threadsafe` — deliberately *not*
`asyncio.run()` per call, which raises `RuntimeError: asyncio.run() cannot be called from a running
event loop` the moment a caller invokes it from inside its own already-running loop. This makes
`SyncAvailabilityEngine` safe to call from any context, including from inside an `async def` caller
driven by an outer `asyncio.run()`.

```python
from datetime import UTC, datetime

from availability_engine import SyncAvailabilityEngine
from availability_engine.storage.memory import InMemoryStore

engine = SyncAvailabilityEngine(InMemoryStore())
engine.define_resource(resource)

result = engine.get_availability(
    "table-1",
    datetime(2026, 9, 7, 0, 0, tzinfo=UTC),
    datetime(2026, 9, 8, 0, 0, tzinfo=UTC),
)
slot = result.available[0]

hold = engine.place_hold(resource.id, slot.start, slot.end, ttl_seconds=60)
booking = engine.confirm_hold(hold.id, payload={"order_id": "abc-123"})
engine.cancel_booking(booking.id)

engine.close()  # stops the background thread; also a daemon thread, so
                # process exit is never blocked even if close() is skipped
```

Call `close()` at consumer shutdown. `SyncAvailabilityEngine` performs zero exception translation
or logging — every `AvailabilityEngine` exception propagates unchanged through the bridge.

## Storage protocol

`availability_engine.storage.protocol.StorageBackend` is a `typing.Protocol` with 7 async methods
(`save_resource`, `get_resource`, `get_active_entries`, `place_hold`, `confirm_hold`,
`release_hold`, `cancel_booking` — structural typing, no inheritance required). Two implementations
ship in this package:

- **`InMemoryStore`** (`availability_engine.storage.memory`) — for tests; an `asyncio.Lock`-guarded
  critical section is its in-memory analog of the SQL backend's dialect-aware locking.
- **`SQLStore`** (`availability_engine.storage.sql.store`) — production backend targeting both
  SQLite (`sqlite+aiosqlite`, local/dev) and Postgres (`postgresql+asyncpg`, prod) from one
  SQLAlchemy Core codebase.

Schema bootstrap for `SQLStore` goes through Alembic. The package ships its migrations
force-included into the wheel; resolve the packaged `script_location` with
`availability_engine.migrations.get_script_location()`:

```python
from alembic import command
from alembic.config import Config

from availability_engine.migrations import get_script_location

cfg = Config()
cfg.set_main_option("script_location", str(get_script_location()))
cfg.set_main_option("sqlalchemy.url", "<your real DB URL>")
command.upgrade(cfg, "head")
```

If working from a checkout of **this repo** (not an installed wheel), `cd` into it and run
`alembic upgrade head` directly — its `alembic.ini` has `script_location = alembic`, a path
resolved relative to the shell's current working directory. This CLI shortcut does **not** work
against an installed wheel (there is no repo checkout to `cd` into) — use the programmatic
`get_script_location()` path above for that case.

## Output contract

`get_availability(resource_id, start, end)` returns an `AvailabilityResult` — **two lists**, never
a flat list with a boolean flag:

- `available: list[PublicSlot]`
- `booked: list[PublicSlot]`

Each `PublicSlot` carries `capacity` and `remaining` as **counts** (never collapsed to a boolean) —
`remaining` is clamped to `0`, never negative, even if a resource's capacity is later reduced below
its currently active hold/booking count.

Write paths **raise** typed exceptions rather than returning a sentinel. Every exception is a
subclass of `AvailabilityEngineError` and carries a `.reason_code` drawn from the closed
`ReasonCode` StrEnum (`capacity_exhausted`, `outside_hours`, `hold_expired`, `not_found`,
`idempotency_conflict`) — a consumer can `except AvailabilityEngineError` broadly, or branch on
`.reason_code` without string-matching the exception class:

| Exception | `.reason_code` | Raised by |
|---|---|---|
| `CapacityExhaustedError` | `capacity_exhausted` | `place_hold` — resource at capacity for the requested slot |
| `OutsideHoursError` | `outside_hours` | `place_hold` — slot falls outside the resource's declared operating hours |
| `HoldExpiredError` | `hold_expired` | `confirm_hold` — hold's TTL has elapsed |
| `HoldNotFoundError` | `not_found` | `confirm_hold` — hold_id does not refer to a currently active hold |
| `BookingNotFoundError` | `not_found` | `cancel_booking` — unknown or already-cancelled booking_id (never a silent no-op) |
| `IdempotencyConflictError` | `idempotency_conflict` | `place_hold`/`confirm_hold` — an idempotency key was reused with materially different arguments/payload |
| `ResourceNotFoundError` | `not_found` | `get_availability`/`place_hold` — resource_id does not refer to a defined `Resource` |

No exception constructor accepts or stores a consumer payload — an exception message can never leak
`confirm_hold`'s opaque `payload` contents.

`place_hold`/`confirm_hold` accept an optional `idempotency_key`, scoped per `(operation_type,
key)`. A retried call with the same key and materially identical arguments/payload returns the
original result rather than acting twice; a concurrent same-key race resolves to one stored result
(proven via `asyncio.gather` against `InMemoryStore`'s lock-guarded critical section), never
double-spending capacity. `release_hold` is idempotent (a no-op on an unknown/already-released hold
id); `cancel_booking` is deliberately **not** — an unknown or already-cancelled booking_id always
raises `BookingNotFoundError`, never a silent no-op.

## Concurrency guarantees

Cited exactly as proven — not a broader "thread-safe" claim:

- **Postgres:** `place_hold` acquires a transaction-scoped advisory lock via
  `acquire_postgres_slot_lock` (`pg_advisory_xact_lock`, keyed on `(resource_id, slot_start)`,
  auto-released on commit/rollback). This closes the phantom-insert race that a bare
  `SELECT ... FOR UPDATE` cannot: `FOR UPDATE` cannot lock a row that does not yet exist, so two
  concurrent transactions can otherwise both count zero prior holds for an empty slot and both
  insert.
- **SQLite:** `attach_sqlite_begin_immediate` issues `BEGIN IMMEDIATE` for every transaction
  (SQLite has no row-level locking at all), giving the whole database file a RESERVED write lock
  upfront — phantom-safe by construction, since there is effectively one writer at a time.
- **Empirical proof, not just reasoning:** `tests/storage/test_concurrency_proof.py` drives real,
  independently-connected concurrent clients against a real testcontainers-Postgres instance
  (K=1/N=25 and K=3/N=30 capacity-vs-concurrent-attempts sweeps, exact success counts, verified
  clean across repeated runs).

The proven guarantee is precisely: **at most K of N concurrent `place_hold` calls succeed on a
capacity-K resource**, verified against real Postgres — not a claim about every possible SQL
backend or isolation level a consumer might configure.

## TZ/DST semantics

Every datetime crossing the public API boundary is UTC-aware — a naive `datetime` is rejected
(`require_utc` at the `get_availability`/`place_hold` boundary; the `UtcDatetime` Pydantic
annotation everywhere else). Each `Resource` declares its own IANA `timezone` field; operating
hours are declared in that resource's local wall-clock time and converted to UTC only at the
`time.localize_operating_hours` boundary.

- **DST transitions:** spring-forward and fall-back are fixture-tested on real 2026 transition
  dates (`tests/core/test_grid_dst.py`) — each boundary point converts independently via
  `.astimezone(UTC)` before elapsed span is computed, so a spring-forward gap compresses and a
  fall-back doubled hour expands the UTC duration correctly. A boundary landing *inside* a DST
  transition resolves deterministically via Python's default `fold=0`.
  This is a fixture-tested guarantee on the documented transition dates and mechanism above — not
  an unconditional claim for every timezone and every year.
- **Midnight-crossing operating hours:** a `LocalInterval` with `end <= start` (an overnight
  sentinel, e.g. `22:00`-`06:00`) is anchored on the following calendar day and is fixture-tested
  (`tests/test_engine.py::test_place_hold_succeeds_after_midnight_on_overnight_hours_resource`).

## Example integration

`examples/chatbot_adapter.py` is a reference `AvailabilityPort` adapter showing how a consumer
translates this engine's async, reason-code-driven contract into its own sync port shape. It is
**dev/reference code only** — the wheel's build config never ships `examples/` (regression-guarded
by `tests/packaging/test_wheel_contains_migrations.py`).
