---
phase: 04-sql-backend-concurrency-proof
reviewed: 2026-09-04T19:21:05Z
depth: standard
files_reviewed: 16
files_reviewed_list:
  - alembic/env.py
  - alembic.ini
  - alembic/script.py.mako
  - alembic/versions/0001_initial_schema.py
  - pyproject.toml
  - src/availability_engine/storage/sql/__init__.py
  - src/availability_engine/storage/sql/locking.py
  - src/availability_engine/storage/sql/models.py
  - src/availability_engine/storage/sql/store.py
  - tests/storage/conftest.py
  - tests/storage/contract_suite.py
  - tests/storage/test_concurrency_proof.py
  - tests/storage/test_protocol_conformance.py
  - tests/storage/test_sql_store.py
  - tests/test_aiosqlite_loop_responsiveness.py
  - tests/test_migrations.py
findings:
  critical: 2
  warning: 4
  info: 2
  total: 8
status: issues_found
---

# Phase 4: Code Review Report

**Reviewed:** 2026-09-04T19:21:05Z
**Depth:** standard
**Files Reviewed:** 16
**Status:** issues_found

## Summary

Reviewed the SQL storage backend (`store.py`, `models.py`, `locking.py`), the Alembic migration
and env, and the associated test suite for Phase 4 (SQL Backend & Concurrency Proof). The
Postgres advisory-lock design in `locking.py` is sound and correctly parameterized (no SQL
injection via bind params), and the migration schema is a faithful, column-for-column match of
`models.py`'s `MetaData`. `place_hold`'s dialect-locking branch is well-reasoned and its capacity
re-read closes the TOCTOU window described in its own comments.

However, two correctness gaps undermine the "no two bookers can ever double-book" guarantee this
phase exists to prove:

1. `confirm_hold` never verifies that its own `DELETE FROM holds` actually removed a row before
   unconditionally inserting the resulting `Booking` — a hold that is concurrently released (or
   double-confirmed) between the initial `SELECT` and the `DELETE` still gets converted into a
   live Booking, silently overriding the release and potentially exceeding resource capacity.
2. The SQLite serialization fix (`attach_sqlite_begin_immediate`) that makes `place_hold`
   phantom-safe on SQLite is never wired into any production code path — it is only ever invoked
   from test fixtures. A consumer constructing `SQLStore` the "obvious" way against a raw
   `create_async_engine("sqlite+aiosqlite:///...")` engine silently loses all concurrency
   protection, with no error, warning, or documentation surfacing the requirement.

Both are detailed below along with four warnings and two info-level items.

## Critical Issues

### CR-01: `confirm_hold` materializes a Booking without checking whether its hold-delete actually matched a row

**File:** `src/availability_engine/storage/sql/store.py:387-403`
**Issue:**

```python
if datetime.now(UTC) >= _ensure_utc(hold_row.expires_at):
    raise HoldExpiredError(hold_id)

await conn.execute(delete(models.holds).where(models.holds.c.id == hold_id))
booking_payload = payload if payload is not None else {}
await conn.execute(
    insert(models.bookings).values(
        id=hold_row.id,
        ...
    )
)
```

`hold_row` is captured from a `SELECT` a few lines earlier, in a separate statement from the
`DELETE`. Nothing checks the `DELETE`'s `rowcount` before the code unconditionally proceeds to
insert a `Booking` built from the *stale* `hold_row` data. `cancel_booking` (same file,
lines 424-437) uses exactly this rowcount-check pattern correctly — this is an inconsistent
omission, not a deliberate design choice.

Concretely reachable race (works today on Postgres under READ COMMITTED, and matches this
module's own stated concurrency model — `confirm_hold` deliberately takes no lock because it's
assumed "Postgres's normal READ COMMITTED row-level atomicity already handles correctly", per the
module docstring at the top of `store.py`):

1. Client A calls `confirm_hold(H1)`. Its transaction `SELECT`s hold `H1` — valid, not expired.
2. Before A's transaction reaches the `DELETE`, client B calls `release_hold(H1)` in its own,
   independent `engine.begin()` transaction, which commits — `H1`'s row is now gone.
3. A's transaction executes `DELETE ... WHERE id = H1` — matches 0 rows (no error: a `DELETE`
   with a non-matching `WHERE` simply reports `rowcount == 0`).
4. A's transaction proceeds anyway and inserts a `Booking` using the stale `hold_row` snapshot —
   this Booking now occupies the slot B just explicitly released.

The result: `release_hold` appeared to succeed (its own transaction committed cleanly), yet the
slot is still occupied — by a *Booking* that materialized out of a hold that no longer existed at
confirmation time. If a third client concurrently calls `place_hold` for the same now-apparently-
free slot between steps 2 and 4, resource capacity is exceeded: a live `Hold` and this phantom
`Booking` both count against the same slot. This is precisely the class of failure ("if everything
else fails, no two bookers can ever double-book") this phase's HOLD-02 concurrency work is meant
to close, and `confirm_hold` is not covered by `test_concurrency_proof.py` (that file only
exercises `place_hold`).

A secondary manifestation: two truly concurrent `confirm_hold(hold_id)` calls for the *same*
`hold_id` with no `idempotency_key` (so no dedup path is taken) both pass the initial `SELECT`
check, both attempt the `DELETE`/`INSERT` sequence, and the second `INSERT` collides on
`bookings.id` (same value as `hold_id`) — raising a raw, uncaught `IntegrityError` back to the
caller instead of the intended `HoldNotFoundError`.

**Fix:**
```python
result = await conn.execute(
    delete(models.holds).where(models.holds.c.id == hold_id)
)
if result.rowcount == 0:
    # The hold was concurrently released/expired-and-reaped/re-confirmed
    # between our SELECT and this DELETE — do not materialize a Booking
    # for a hold that no longer exists.
    raise HoldNotFoundError(hold_id)
booking_payload = payload if payload is not None else {}
await conn.execute(
    insert(models.bookings).values(
        id=hold_row.id,
        ...
    )
)
```

### CR-02: SQLite's write-serialization fix is never attached outside test fixtures — the default construction path is not phantom-safe

**File:** `src/availability_engine/storage/sql/locking.py:50-79`, `src/availability_engine/storage/sql/store.py:88-90`, `src/availability_engine/storage/sql/__init__.py:1`
**Issue:**

`attach_sqlite_begin_immediate(engine)` is what makes SQLite's `place_hold` phantom-safe (it
registers the `"connect"`/`"begin"` event listeners that force `BEGIN IMMEDIATE`, per this
module's own extensive docstring). Searching the whole `src/` tree, the *only* place this function
is ever called is `tests/storage/conftest.py:26` and (implicitly, via the same fixture)
`tests/storage/test_concurrency_proof.py`'s Postgres-only file does not need it. There is no
factory function, no `SQLStore.__init__` validation, and no mention anywhere in `README.md`
(checked — zero hits for "sqlite", "begin_immediate", or "SQLStore") that a consumer must call
`attach_sqlite_begin_immediate(engine)` themselves before handing the engine to `SQLStore`.

`SQLStore.__init__` (`store.py:88`) accepts *any* `AsyncEngine` with no validation:
```python
def __init__(self, engine: AsyncEngine) -> None:
    self._engine = engine
```

The natural, undocumented-requirement-unaware usage —
```python
engine = create_async_engine("sqlite+aiosqlite:///prod.db")
store = SQLStore(engine)
```
— silently runs every `place_hold` transaction under aiosqlite's default *DEFERRED* transaction
mode. Without `BEGIN IMMEDIATE`, two concurrent `place_hold` calls for the same slot can both run
their `_get_active_entries` capacity-check `SELECT`s before either has taken SQLite's write lock,
both see `count < capacity`, and both then insert — because only the physical write acquisition is
serialized (and the second writer's earlier-read snapshot is never re-validated), not the whole
transaction. This is the exact "phantom-insert, capacity exceeded" failure this module's own
docstring calls out for the *pre-fix* Postgres design — silently reopened for SQLite whenever this
one required setup call is skipped, which is the default/easy path today.

Compounding this, `place_hold`'s dialect branch (`store.py:245`) is a bare
`if conn.engine.dialect.name == "postgresql":` with no `else` and no assertion that the SQLite
listener is actually attached to `conn.engine` — there is nothing in the code path itself that
would fail loudly if the wiring is missing; it fails silently, only under concurrent load.

**Fix:** Wire this into the type consumers actually construct, rather than leaving it as a
manual, undiscoverable prerequisite. E.g. either:
```python
class SQLStore:
    def __init__(self, engine: AsyncEngine) -> None:
        if engine.dialect.name == "sqlite":
            attach_sqlite_begin_immediate(engine)
        self._engine = engine
```
or provide and document a `create_sql_engine(url: str) -> AsyncEngine` factory that all
consumers (and this repo's own test fixtures) are required to go through, so there is exactly one
way to obtain an `AsyncEngine` destined for `SQLStore` and it can't be constructed unsafely. At
minimum, document the requirement prominently in `README.md` and raise/warn from `SQLStore.__init__`
if a SQLite engine is passed without the listener attached (event listeners are introspectable via
`sqlalchemy.event.contains`).

## Warnings

### WR-01: `save_resource` has an unguarded check-then-write race that surfaces as a raw `IntegrityError`

**File:** `src/availability_engine/storage/sql/store.py:93-112`
**Issue:** `save_resource` does a plain `SELECT` for `existing_id`, then branches to `INSERT` or
`UPDATE` with no locking and no `IntegrityError` handling. Two concurrent `save_resource(resource)`
calls for a not-yet-persisted `resource.id` (e.g. two app workers bootstrapping the same static
resource catalog on startup) can both observe `existing_id is None` and both attempt the `INSERT`
branch; the second raises an unhandled, driver-level `IntegrityError` instead of resolving
gracefully (upsert semantics, or a clear domain error).
**Fix:** Either use a dialect-portable upsert (`INSERT ... ON CONFLICT DO UPDATE` for Postgres /
`INSERT OR REPLACE`/`ON CONFLICT` for SQLite, both supported via SQLAlchemy's dialect-specific
`insert()` variants — though this would reintroduce a small dialect branch), or catch
`IntegrityError` around the `INSERT` and fall back to the `UPDATE` path, mirroring the
`_write_idempotency_record` pattern already used elsewhere in this file.

### WR-02: `SQLStore`'s idempotency fingerprint depends on a "private" helper imported from a sibling module

**File:** `src/availability_engine/storage/sql/store.py:35`
**Issue:** `from availability_engine.storage.memory import _fingerprint` — `_fingerprint` is
underscore-prefixed by convention (private to `memory.py`), yet `SQLStore`'s idempotency-conflict
detection now depends on it having identical semantics to whatever `InMemoryStore` uses internally.
Nothing marks this as a shared, cross-module contract — a future edit to `memory.py` that renames,
inlines, or changes `_fingerprint`'s hashing scheme (reasonable to do to a function its own module
treats as private) silently breaks `SQLStore`'s idempotency-conflict semantics with no type-checker
or import-time signal beyond an `ImportError` if it's renamed outright (and no signal at all if its
behavior merely changes).
**Fix:** Promote `_fingerprint` to a small shared, public utility module (e.g.
`availability_engine.storage._shared` or similar) that both `memory.py` and `sql/store.py` import,
making the cross-backend contract explicit rather than incidental.

### WR-03: `place_hold`'s "authoritative capacity" re-read silently trusts the caller for unregistered resources

**File:** `src/availability_engine/storage/sql/store.py:288-299`
**Issue:**
```python
effective_capacity = (
    Resource.model_validate(resource_row.definition).capacity
    if resource_row is not None
    else capacity
)
```
The surrounding comment states the intent as "re-read the authoritative capacity from our own
store under the transaction/lock rather than trusting the caller-supplied snapshot" (WR-03 in the
original design), but for a `resource_id` that was never persisted via `save_resource`, the code
falls back to trusting the caller-supplied `capacity` argument outright — the opposite of the
stated intent for exactly the case where a caller-controlled value matters most (no server-side
record to cross-check against at all). No test in `contract_suite.py` or `test_sql_store.py`
exercises `place_hold` against an unregistered `resource_id`.
**Fix:** Either raise a not-found-style error when `resource_row is None` (matching the "never
trust the caller" framing consistently), or, if the fallback is intentional (e.g. to support a
caller that manages resources out-of-band), document why explicitly and add a test asserting the
fallback behavior.

### WR-04: SQL package `__init__.py` exports nothing

**File:** `src/availability_engine/storage/sql/__init__.py:1`
**Issue:** The file is a single docstring with no `__all__` and no re-exports. Consumers must
import `SQLStore` from `availability_engine.storage.sql.store`, `metadata`/tables from
`availability_engine.storage.sql.models`, and the locking helpers from
`availability_engine.storage.sql.locking` individually — there is no single package-level surface,
inconsistent with how a reusable library's public contract is typically exposed to consumers.
**Fix:** Re-export the public surface (`SQLStore`, `metadata`, `attach_sqlite_begin_immediate`) from
`__init__.py` with an explicit `__all__`.

## Info

### IN-01: Contract-suite fixtures couple every backend permutation to a live Postgres container

**File:** `tests/storage/conftest.py:53-91`
**Issue:** `backend_factory` and the autouse `_reset_sql_tables` fixture both unconditionally
depend on `sqlite_engine` *and* `pg_engine`, even when `request.param == "in-memory"`. Running only
the `"in-memory"` permutation of `contract_suite.py::TestStorageContractSuite` still spins up a
`testcontainers` Postgres via Docker, adding an unrelated hard dependency (a running container
runtime) to what should be the cheapest, most dependency-free parametrization.
**Fix:** Scope `pg_engine`/`sqlite_engine` fixture usage to only the parametrizations that need
them (e.g. via `request.getfixturevalue` inside `backend_factory`, resolved lazily per
`backend_id`), so an `in-memory`-only test run has no Docker/testcontainers dependency.

### IN-02: Migration downgrade path has no test coverage

**File:** `alembic/versions/0001_initial_schema.py:103-109`, `tests/test_migrations.py`
**Issue:** `test_migrations.py` only exercises `command.upgrade(cfg, "head")` against both dialects;
`downgrade()` (which drops all four tables/indexes) is never invoked in any test, so a mistake in
its statement order or table/index names would go undetected until someone actually runs a
downgrade against a real database.
**Fix:** Add a round-trip test — `upgrade("head")` then `downgrade("base")` then assert the schema
is empty (or re-`upgrade` and assert it matches again) — for at least the SQLite case.

---

_Reviewed: 2026-09-04T19:21:05Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
