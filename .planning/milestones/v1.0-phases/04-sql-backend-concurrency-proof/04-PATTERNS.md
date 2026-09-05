# Phase 4: SQL Backend & Concurrency Proof - Pattern Map

**Mapped:** 2026-09-04
**Files analyzed:** 10
**Analogs found:** 8 / 10

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|---------------|
| `src/availability_engine/storage/sql/models.py` | model (schema) | CRUD | `src/availability_engine/contracts.py` (Hold/Booking field shapes) | role-match (Pydantic model → SQLAlchemy Table columns, same field names) |
| `src/availability_engine/storage/sql/store.py` | service (storage backend) | CRUD + event-driven (lazy expiry) | `src/availability_engine/storage/memory.py` (`InMemoryStore`) | exact (must satisfy same `StorageBackend` Protocol, same method set, same idempotency/expiry semantics) |
| `src/availability_engine/storage/sql/locking.py` | utility (dialect-aware lock helper) | transform | none in codebase (new concern) — pattern from RESEARCH.md Pattern 1 | no analog |
| `alembic/env.py` | config | batch | none in codebase — new tooling | no analog (use RESEARCH.md Code Example verbatim) |
| `alembic/versions/0001_initial_schema.py` | migration | batch | none in codebase — new tooling | no analog (use RESEARCH.md Code Example) |
| `tests/storage/conftest.py` | test (fixtures) | request-response | `tests/conftest.py` (`sample_resource`, `store` fixtures) | role-match (same fixture idiom, extended for engine/container setup) |
| `tests/storage/contract_suite.py` (MODIFIED — parametrize decorator + `backend_factory` indirection only) | test | CRUD | itself (existing file, Phase 1) | exact — this file already declares itself the extension point |
| `tests/storage/test_protocol_conformance.py` (MODIFIED — add SQLStore case) | test | request-response | itself (existing file) | exact |
| `tests/storage/test_concurrency_proof.py` | test (concurrency proof) | event-driven / concurrent | `tests/test_hold_expiry.py` (closest existing async time/race-sensitive test) — but structurally novel (real OS connections, no lock, no time-machine) | partial match |
| `tests/test_aiosqlite_loop_responsiveness.py` | test (async behavior verification) | event-driven | none — genuinely new pattern (loop-responsiveness probe) | no analog |

## Pattern Assignments

### `src/availability_engine/storage/sql/store.py` (service, CRUD)

**Analog:** `src/availability_engine/storage/memory.py`

**Imports pattern** (lines 1-25 of memory.py):
```python
import asyncio
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from availability_engine.contracts import Booking, BookingStatus, Hold, Resource
from availability_engine.core.intervals import Interval, overlaps
from availability_engine.errors import (
    BookingNotFoundError,
    CapacityExhaustedError,
    HoldExpiredError,
    HoldNotFoundError,
    IdempotencyConflictError,
)
```
`SQLStore` should mirror this: same domain imports (`contracts`, `core.intervals`, `errors`), plus new imports for `sqlalchemy.ext.asyncio.AsyncEngine`, `sqlalchemy.select/insert/update/delete`, and the local `sql.models`/`sql.locking` modules.

**Core CRUD/lock pattern to replicate exactly** (memory.py lines 104-193, `place_hold`):
- The idempotency check happens *first*, inside the same critical section as the capacity check and the write (`async with self._lock:` in memory; `async with engine.begin() as conn:` + dialect lock in SQL).
- Capacity is re-read from the store's own authoritative resource record (WR-03), never trusted from the caller.
- `get_active_entries` is the ONE shared active-entries primitive (AVAIL-03) — the SQL version must implement this as a single reusable query (or method) that both `place_hold`'s count check and any direct `get_active_entries()` call use; do not duplicate the scan.
- On the SQL side, replace `async with self._lock:` with: Postgres → `pg_advisory_xact_lock(hashtext(:rid), hashtext(:slot))` as first statement in the transaction (see `locking.py` below); SQLite → `BEGIN IMMEDIATE` via the two SQLAlchemy event listeners (`isolation_level = None` on `"connect"`, `conn.exec_driver_sql("BEGIN IMMEDIATE")` on `"begin"`).
- CapacityExhaustedError is raised — and the idempotency record is NEVER cached — on the failure path exactly as memory.py lines 175-179 do; replicate this ordering in the SQL transaction (raise before commit, so nothing is persisted).

**Idempotency replay pattern to replicate exactly** (memory.py lines 125-157, 207-246):
- Same `_fingerprint(*parts)` shape (`hashlib.sha256(json.dumps(parts, sort_keys=True, default=str))`) — reuse as-is from `memory.py`, or import it, do not reinvent.
- CR-01: always re-validate the cached snapshot against live state before returning it (SQL: re-`SELECT` the referenced hold/booking row inside the same transaction as the idempotency-table lookup, not just return the cached blob).
- IN-02: explicit `isinstance`/type checks (not `assert`) on the idempotency record's referenced type.

**`confirm_hold` pattern to replicate exactly** (memory.py lines 195-266):
- Idempotency check runs BEFORE the `hold is None` lookup (documented ordering requirement — a replay's hold may already be deleted by the first call's success). The SQL version's transaction must do the idempotency-table lookup before the `holds` table row fetch, in that exact order, inside one transaction.
- Hold → Booking transition: hold row deleted, booking row inserted with the *same id* (Runtime Decisions in CONTEXT.md confirms this — `id` is shared across the delete+insert pair).
- `payload` JSON-validation guard (memory.py lines 209-225: fail fast with `TypeError` if not JSON-serializable) must be replicated verbatim before fingerprinting, since the SQL `payload` column is JSON/JSONB and needs the same guarantee.

**`release_hold` / `cancel_booking` pattern** (memory.py lines 268-283):
- `release_hold` is an idempotent no-op on unknown id (SQL: `DELETE ... WHERE id = :id`, no existence check, no error if 0 rows affected).
- `cancel_booking` is NOT idempotent — raises `BookingNotFoundError` on unknown-or-already-cancelled id (D-04). SQL: `SELECT` first to check current status, or use an `UPDATE ... WHERE id=:id AND status != 'cancelled' RETURNING id` and raise if `rowcount == 0`.

**Error handling pattern:** import and raise the exact same exception classes from `src/availability_engine/errors.py` — `CapacityExhaustedError`, `HoldExpiredError`, `HoldNotFoundError`, `BookingNotFoundError`, `IdempotencyConflictError`. Never introduce SQL-specific exception types at the Protocol boundary; catch driver-level `IntegrityError`/`OperationalError` inside `store.py` and translate to the domain exceptions above (SQLite's unique-constraint violation for a duplicate idempotency key, for instance, should surface as `IdempotencyConflictError`, mirroring memory.py's in-Python dict-key check).

---

### `src/availability_engine/storage/protocol.py` (unchanged — reference only)

**Analog:** itself.

`SQLStore` must structurally satisfy this exact `Protocol` (lines 12-55) — same six async methods, same signatures including the reserved `payload`/`idempotency_key` defaulted kwargs (never rename per the Protocol's own comment "reserved for Phase 3 — never rename"). `runtime_checkable` means `isinstance(SQLStore(engine), StorageBackend)` is the structural-conformance assertion `test_protocol_conformance.py` will add (mirroring `test_inmemory_satisfies_protocol`, lines 7-8 of that file).

---

### `src/availability_engine/storage/sql/models.py` (model, CRUD)

**Analog:** `src/availability_engine/contracts.py` `Hold`/`Booking` classes (lines 188-204) — field names and types are the direct source of truth for SQL column names/types, per RESEARCH.md Assumption A3 (`[VERIFIED: contracts.py:188-204]`).

```python
class Hold(BaseModel):
    id: str
    resource_id: str
    slot_start: UtcDatetime
    slot_end: UtcDatetime
    expires_at: UtcDatetime

class Booking(BaseModel):
    id: str
    resource_id: str
    slot_start: UtcDatetime
    slot_end: UtcDatetime
    payload: dict[str, Any]
    status: BookingStatus = BookingStatus.CONFIRMED
```
Map directly to SQLAlchemy `Table` columns: `id: String PK`, `resource_id: String`, `slot_start`/`slot_end`/`expires_at`: `DateTime(timezone=True)`, `payload`: `JSON`/`JSONB`, `status`: `String`/`Enum` matching `BookingStatus` values (`"confirmed"`/`"cancelled"`, lowercase per the `StrEnum` values in contracts.py line 153-155). Per Runtime Decisions in CONTEXT.md: separate `holds` and `bookings` tables (not one physical table), plus an `idempotency` table keyed on `(operation_type, idempotency_key)` mirroring `IdempotencyRecord` (memory.py lines 37-40) and a `created_at` column for future retention (Security Domain note in RESEARCH.md). Index: `(resource_id, slot_start, status)`-equivalent per table, per CONTEXT.md D-02/Runtime Decisions.

---

### `src/availability_engine/storage/sql/locking.py` (utility, transform)

**No codebase analog** — new dialect-locking concern. Use RESEARCH.md's Code Examples verbatim as the pattern source (not invented here):
- Postgres: `pg_advisory_xact_lock(hashtext(:rid), hashtext(:slot))` as the first statement in the transaction, via `sqlalchemy.text()` with named bind params — never f-string interpolate `resource_id`/`slot_start` into the SQL text (Security Domain V5 requirement).
- SQLite: two `@event.listens_for` hooks (`"connect"` → `dbapi_connection.isolation_level = None`; `"begin"` → `conn.exec_driver_sql("BEGIN IMMEDIATE")`).
- This is the ONLY dialect-branch point in the whole SQL backend (RESEARCH.md Pattern 1) — every other query in `store.py` must be dialect-agnostic SQLAlchemy Core.

---

### `tests/storage/conftest.py` (test fixtures, request-response)

**Analog:** `tests/conftest.py` (`sample_resource` fixture, lines 14-25) for the fixture-authoring idiom (plain `@pytest_asyncio.fixture` function returning a constructed object), extended per RESEARCH.md Pattern 2 to add:
- `sqlite_engine` (session-scoped, `create_async_engine("sqlite+aiosqlite:///:memory:")` + the `locking.py` event listeners + `metadata.create_all`)
- `pg_container` (session-scoped `testcontainers.postgres.PostgresContainer`)
- `pg_engine` (built from `pg_container.get_connection_url()`)
- `_reset_sql_tables` (autouse fixture, `table.delete()` for `reversed(metadata.sorted_tables)` between tests)
- `backend_factory` (indirect-parametrize fixture reading `request.param` — required because `pytest.mark.parametrize`'s static list can't close over a runtime fixture value; see RESEARCH.md's explicit note on this).

---

### `tests/storage/contract_suite.py` (MODIFIED — test, CRUD)

**Analog:** itself — this file's own docstring is the pattern spec: *"Phase 4 adds SQLStore to the single `parametrize` list below without rewriting any test body in this file"* (lines 1-6). Only this line changes:
```python
@pytest.mark.parametrize("backend_factory", [InMemoryStore], ids=["in-memory"])
```
→ becomes (per RESEARCH.md Pattern 2's indirect-parametrization recommendation):
```python
@pytest.mark.parametrize("backend_factory", ["in-memory", "sqlite", "postgres"], indirect=True)
```
All 16 `test_*` method bodies (lines 27-449) stay byte-for-byte unchanged — they already call `backend = backend_factory()` with no args (e.g. line 30, 40, 47), which is exactly what the new `backend_factory` fixture in `conftest.py` must return regardless of which backend it resolves to.

---

### `tests/storage/test_protocol_conformance.py` (MODIFIED — test, request-response)

**Analog:** itself. Add a second, structurally identical test function mirroring the existing one exactly:
```python
def test_inmemory_satisfies_protocol() -> None:
    assert isinstance(InMemoryStore(), StorageBackend)
```
→ add `test_sqlstore_satisfies_protocol` following the same one-line-assertion shape, constructing `SQLStore` with a (sync-constructible, or session-scoped fixture-provided) engine.

---

### `tests/storage/test_concurrency_proof.py` (test, event-driven/concurrent)

**No close analog for the concurrency-proof shape itself** — `tests/test_hold_expiry.py` is the closest existing file dealing with time-sensitive race conditions in this codebase (uses `time_machine.travel` to simulate expiry), but HOLD-02 requires genuinely concurrent OS-level connections, which `time_machine`-style single-process simulation cannot provide. Use RESEARCH.md's Code Examples harness shape as the primary source:
```python
async def test_concurrent_place_hold_never_exceeds_capacity(pg_container, sample_resource_k1):
    engine = create_async_engine(pg_container.get_connection_url(), pool_size=25)
    store = SQLStore(engine)
    await store.save_resource(sample_resource_k1)  # capacity=1
    N = 25
    results = await asyncio.gather(
        *(store.place_hold(sample_resource_k1.id, slot, capacity=1, ttl_seconds=60)
          for _ in range(N)),
        return_exceptions=True,
    )
    successes = [r for r in results if not isinstance(r, Exception)]
    assert len(successes) <= 1
```
Critical constraint (RESEARCH.md Pattern 3): this test's fixture must NOT reuse `contract_suite.py`'s rollback-savepoint isolation — it needs its own real-commit, real-connection-pool fixture, kept in a separate file for exactly this reason.

**`sample_resource` shape to reuse for the capacity-1 fixture:** `tests/conftest.py` lines 14-25 (`Resource(id=..., capacity=1, operating_hours={...}, timezone="America/Chicago", slot_duration=timedelta(minutes=30))`) — same construction idiom, just needs `capacity=1` explicit for the K=1 proof.

---

### `tests/test_aiosqlite_loop_responsiveness.py` (test, event-driven)

**No codebase analog** — new verification concern (D-05). Follow RESEARCH.md's Pitfall 2 recipe: a ticker coroutine incrementing a counter via tight `asyncio.sleep(0.01)` loop, run concurrently (via `asyncio.gather`) with a slow aiosqlite query (e.g. a Python UDF with `time.sleep`, or a large table scan); assert the ticker's counter advanced during the query, proving loop responsiveness (not write throughput).

## Shared Patterns

### Error handling / domain exceptions
**Source:** `src/availability_engine/errors.py` (whole file, 109 lines)
**Apply to:** `store.py` exclusively — every raised error at the `StorageBackend` boundary must be one of `CapacityExhaustedError`, `OutsideHoursError`, `HoldExpiredError`, `HoldNotFoundError`, `BookingNotFoundError`, `IdempotencyConflictError`, `ResourceNotFoundError`. Never leak a raw SQLAlchemy/driver exception (`IntegrityError`, `OperationalError`) across the Protocol boundary — catch and translate in `store.py`.
```python
class CapacityExhaustedError(AvailabilityEngineError):
    reason_code = ReasonCode.CAPACITY_EXHAUSTED
    def __init__(self, resource_id: str, slot: Interval) -> None:
        self.resource_id = resource_id
        self.slot = slot
        super().__init__(f"capacity exhausted for resource {resource_id!r}")
```
Note the constructor discipline (errors.py lines 1-11): never accept/store a payload argument in any exception constructor — this must hold for the SQL backend too (don't add a `sql_error` or raw-row-contents kwarg to any of these).

### Idempotency fingerprinting
**Source:** `src/availability_engine/storage/memory.py:28-34` (`_fingerprint` function)
**Apply to:** `store.py` — reuse the identical deterministic-fingerprint construction (`hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()`) so idempotency-conflict detection is byte-identical in behavior to the in-memory backend; the contract suite's idempotency tests assume this exact semantic (fingerprint over `(resource_id, slot.start, slot.end)` for `place_hold`, excluding `ttl_seconds` per Open Question 1's resolution).

### Active-entries / capacity predicate
**Source:** `src/availability_engine/storage/memory.py:64-102` (`get_active_entries`)
**Apply to:** `store.py` — the single shared predicate ("active" = not expired for holds, not cancelled for bookings, overlapping the query window) must be implemented as one reusable SQL query/method, called by both the public `get_active_entries` Protocol method AND internally by `place_hold`'s capacity check — never duplicate the scan (AVAIL-03, HOLD-05 in the code comments).

### Dialect-aware locking (the one branch point)
**Source:** RESEARCH.md Pattern 1 (no codebase precedent — this is new infrastructure)
**Apply to:** `locking.py`, invoked from `store.py`'s `place_hold`/`confirm_hold`/`cancel_booking` transactions only.
```python
# Postgres
await conn.execute(
    text("SELECT pg_advisory_xact_lock(hashtext(:rid), hashtext(:slot))"),
    {"rid": resource_id, "slot": slot_start.isoformat()},
)
# SQLite
@event.listens_for(sqlite_engine.sync_engine, "connect")
def _do_connect(dbapi_connection, connection_record):
    dbapi_connection.isolation_level = None
@event.listens_for(sqlite_engine.sync_engine, "begin")
def _do_begin(conn):
    conn.exec_driver_sql("BEGIN IMMEDIATE")
```

### Fixture idiom
**Source:** `tests/conftest.py:9-25`
**Apply to:** `tests/storage/conftest.py` — same plain `@pytest_asyncio.fixture` async-function-returning-object style; no fixture factories/classes needed, matching the codebase's existing minimalism.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `src/availability_engine/storage/sql/locking.py` | utility | transform | No dialect-locking code exists yet anywhere in the codebase — genuinely new infrastructure; use RESEARCH.md Pattern 1 as the sole source. |
| `alembic/env.py`, `alembic/versions/0001_initial_schema.py` | config, migration | batch | No Alembic scaffolding exists in the repo at all (confirmed by RESEARCH.md: no `alembic/` dir, no `alembic.ini`); use RESEARCH.md's Code Examples verbatim. |
| `tests/test_aiosqlite_loop_responsiveness.py` | test | event-driven | Novel verification concern (D-05); no existing test probes event-loop responsiveness under a blocking-adjacent driver call. |
| `tests/storage/test_concurrency_proof.py` | test | event-driven/concurrent | `test_hold_expiry.py` is a partial match (time-sensitive) but uses `time_machine` single-process simulation, the opposite of the genuinely-concurrent-OS-connections requirement here. |

## Metadata

**Analog search scope:** `src/availability_engine/` (all modules), `tests/` (all test files), `pyproject.toml`
**Files scanned:** 24 Python source/test files + `pyproject.toml`
**Pattern extraction date:** 2026-09-04
