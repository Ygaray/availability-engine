# Phase 4: SQL Backend & Concurrency Proof - Research

**Researched:** 2026-09-04
**Domain:** Async SQLAlchemy Core storage backend (SQLite + Postgres), Alembic migrations, real-concurrency proof via testcontainers
**Confidence:** MEDIUM-HIGH (schema/protocol facts VERIFIED from source; SQLAlchemy/Postgres locking mechanics CITED from official docs; package versions VERIFIED from PyPI registry)

## Summary

Phase 4 swaps a real SQL backend beneath the already-frozen `StorageBackend` Protocol and engine
facade with zero consumer-visible change. The schema is settled by the Runtime Decisions in
CONTEXT.md: separate `holds` and `bookings` tables mirroring the landed
`src/availability_engine/storage/memory.py` `_holds`/`_bookings` split, plus a distinct
`idempotency` table.

**The single most important finding of this research reframes the phase's central open question.**
CONTEXT.md's D-01 ("defer `FOR UPDATE`, rely solely on the atomic `INSERT ... SELECT ... WHERE
(COUNT < capacity)` conditional write") is **not safe** against genuinely concurrent Postgres
connections given this schema shape, and the Runtime Decisions' restated "Postgres `SELECT ...
FOR UPDATE`" is **also not sufficient by itself** — `SELECT ... FOR UPDATE` cannot lock a row that
does not yet exist, so two concurrent transactions counting zero prior holds for an empty slot will
both pass a `COUNT(*) < capacity` check and both insert, overbooking capacity 1 to 2. This is a
well-documented Postgres phantom-insert class of race, distinct from the classic "lock the row
you're updating" case `FOR UPDATE` actually solves. The concrete, portable recommendation below is
a **Postgres transaction-scoped advisory lock keyed on `(resource_id, slot_start)`**
(`pg_advisory_xact_lock`) acquired as the first statement inside the same transaction as the
count-then-insert, released automatically on commit/rollback. SQLite's `BEGIN IMMEDIATE` needs no
equivalent change — a whole-database write lock has no "existing row" precondition and is already
phantom-safe.

**Primary recommendation:** Ship one `SQLStore` class satisfying `StorageBackend`, dialect-branching
only at the transaction-locking seam (`pg_advisory_xact_lock` on Postgres, `BEGIN IMMEDIATE` via a
SQLAlchemy `"begin"` event listener on SQLite) around an otherwise-identical
count-then-conditional-insert SQL shape; extend `tests/storage/contract_suite.py`'s
`@pytest.mark.parametrize("backend_factory", ...)` list (not its test bodies) to cover SQLite and
Postgres; add a dedicated, separate `HOLD-02` concurrency test that opens N independent real
connections against a testcontainers Postgres and asserts `rowcount <= K` — this test must NOT
share a connection/savepoint with the rollback-isolated contract-suite tests, or it stops proving
anything.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Capacity-safe hold placement (atomicity) | Database / Storage | API (engine facade validates hours/resource first) | The engine facade (`engine.py`) never takes a lock — atomicity lives entirely behind `StorageBackend` (STORE-01), so the SQL storage impl is the sole owner of the count+insert critical section. |
| Schema definition & migrations | Database / Storage | — | Alembic + SQLAlchemy `Table` metadata are storage-layer concerns; the engine/facade never issues DDL. |
| Dialect-aware locking strategy | Database / Storage | — | Postgres advisory lock vs. SQLite `BEGIN IMMEDIATE` is entirely inside the `SQLStore` implementation; the Protocol interface is dialect-agnostic. |
| Contract test parametrization | Test / CI tooling | Database / Storage | `contract_suite.py` lives in `tests/`, but what it tests (behavioral parity across backends) is a storage-tier guarantee. |
| Idempotency record retention | Database / Storage | — | SQL-only concern (Runtime Decisions); the in-memory store's "no reaper" policy does not need to survive into the SQL backend as-is. |

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| STORE-03 | One SQL storage implementation targets both SQLite (dev) and Postgres (prod), using the portable atomic conditional-write pattern | See "Standard Stack", "Code Examples" — dialect-branch only at the locking seam; concrete SQLAlchemy Core query shapes given per dialect. |
| STORE-04 | The same parametrized contract test suite passes unmodified against in-memory, SQLite, and Postgres backends | See "Pattern: Extending contract_suite.py without touching test bodies" — the existing `backend_factory` parametrize list is exactly the extension point the Phase 1-3 code already anticipated. |
| STORE-05 | The SQL schema is versioned with migrations from the first commit (initial migration = current schema) | See "Alembic" subsection — `batch_alter_table` + `render_as_batch=True` from commit 1. |
| HOLD-02 | Concurrent hold placement never exceeds capacity, proven against real Postgres | See "Common Pitfalls" (phantom-insert race) and "Code Examples" (advisory-lock pattern + testcontainers proof harness). This is the requirement most at risk of a false-pass if the advisory-lock finding above is skipped. |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `sqlalchemy` | 2.0.52 `[VERIFIED: PyPI registry, published 2026-08-11]` | Async Core query building, dialect abstraction (SQLite `aiosqlite` / Postgres `asyncpg`) | Locked in `.claude/CLAUDE.md`; only actively-maintained option spanning both async dialects from one codebase. |
| `asyncpg` | 0.31.0 `[VERIFIED: PyPI registry, published 2025-11-24]` | Async Postgres driver (`postgresql+asyncpg` dialect) | Locked in CLAUDE.md; de facto standard SQLAlchemy async Postgres driver. |
| `aiosqlite` | 0.22.1 `[VERIFIED: PyPI registry, published 2025-12-23]` | Async SQLite driver (`sqlite+aiosqlite` dialect) | Locked in CLAUDE.md; only viable async SQLite driver. Per-connection background thread architecture confirmed `[CITED: aiosqlite.omnilib.dev]` — see D-05 verification pattern below. |
| `alembic` | 1.19.2 `[VERIFIED: PyPI registry, published 2026-09-04]` | Versioned schema migrations, consumer-run | D-03: initial migration = current schema, `batch_alter_table` mode for SQLite parity. |
| `testcontainers` (extras: `postgres`) | 4.15.0 `[VERIFIED: PyPI registry, published 2026-07-24]` | Real Postgres container for the concurrency proof and SQL-parametrized contract-suite runs | D-04: genuinely concurrent OS-level connections, rejecting an in-process-only proof. |

### Package Legitimacy Audit

All five packages are already human-approved for Phase 4 in `.planning/APPROVED-DEPS.md` (approved
2026-09-03) — the planner may skip the per-package blocking-human checkpoint per that file's own
rule. Re-ran the check this session for currency:

| Package | Registry | Age at check time | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|--------------------|-----------|--------------|---------|--------------|
| sqlalchemy | pypi | ~3 wks (2.0.52) | 71.3M/wk | sqlalchemy.org (canonical project site, not raw GitHub) | SUS (`too-new`) | Approved — pre-approved in APPROVED-DEPS.md; "too-new" reflects the *patch release* date, not project age (SQLAlchemy the project is 20+ years old). No action needed. |
| asyncpg | pypi | ~3 mo | 22.2M/wk | none reported by the seam | SUS (`no-repository`) | Approved — pre-approved in APPROVED-DEPS.md; this is a heuristic gap (asyncpg is `github.com/MagicStack/asyncpg`), not a real signal. No action needed. |
| aiosqlite | pypi | ~9 mo | unknown (not reported) | none reported by the seam | SUS (`unknown-downloads`, `no-repository`) | Approved — pre-approved in APPROVED-DEPS.md; real repo is `github.com/omnilib/aiosqlite`. No action needed. |
| alembic | pypi | 0 days (1.19.2 released same day as this research) | unknown (not reported) | github.com/sqlalchemy/alembic | SUS (`too-new`, `unknown-downloads`) | Approved — pre-approved in APPROVED-DEPS.md. **However:** pin `alembic==1.19.1` (the prior release, per the `alembic.sqlalchemy.org` docs snapshot fetched this session) rather than the same-day `1.19.2` unless the planner re-verifies `1.19.2`'s changelog at execution time — a release published hours before use has had zero real-world soak time. |
| testcontainers | pypi | ~6 wks | 6.6M/wk | github.com/testcontainers/testcontainers-python | OK | Approved — clean verdict, no flag needed. |

**Packages removed due to `[SLOP]` verdict:** none.
**Packages flagged as suspicious `[SUS]`:** sqlalchemy, asyncpg, aiosqlite, alembic — all already human-approved this milestone (APPROVED-DEPS.md); no new checkpoint needed. The `alembic` same-day-release note above is a soak-time caution, not a legitimacy concern.

**Installation:**
```bash
uv add "sqlalchemy>=2.0,<2.1" "asyncpg==0.31.0" "aiosqlite==0.22.1" "alembic==1.19.1"
uv add --group dev "testcontainers[postgres]==4.15.0"
```

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pytest-asyncio` (already pinned `1.4.0`) | existing | Async fixtures for engine/container setup | Already in `pyproject.toml`'s dev group from Phase 1; no version change needed for Phase 4. |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `pg_advisory_xact_lock` (transaction-scoped advisory lock) | `SERIALIZABLE` isolation + app-level retry on `40001` | Correct and arguably "more standard SQL," but requires an explicit retry loop in every write path and changes the isolation level away from the project's stated `READ COMMITTED` (D-04's own resolution text names `READ COMMITTED` explicitly) — advisory lock achieves the same guarantee with less code and no retry logic. |
| `pg_advisory_xact_lock` | A pre-seeded per-`(resource_id, slot)` capacity-counter row, `UPDATE ... WHERE used < capacity RETURNING ...` | Would let `SELECT/UPDATE ... FOR UPDATE` work correctly (the row already exists, so it can be locked) — genuinely simpler reasoning, but requires a schema change (a new counter table, or lazily inserting a placeholder row per slot on first touch) that the Runtime Decisions' schema (holds/bookings/idempotency only) does not currently include. Out of scope for this phase's locked schema; worth flagging as a v2 alternative if advisory-lock throughput ever becomes a bottleneck. |

## Architecture Patterns

### System Architecture Diagram

```
                        Consumer code
                              │
                              ▼
                   AvailabilityEngine facade      (engine.py — unchanged this phase)
                              │  calls only StorageBackend Protocol methods
                              ▼
                  ┌───────────────────────┐
                  │   StorageBackend       │      (protocol.py — unchanged this phase)
                  │   Protocol (async)     │
                  └───────────┬───────────┘
                              │  satisfied by either backend
              ┌───────────────┴────────────────┐
              ▼                                 ▼
      InMemoryStore (Phase 1-3)          SQLStore (NEW — this phase)
      dict + asyncio.Lock                SQLAlchemy Core AsyncEngine
                                                  │
                              ┌───────────────────┴───────────────────┐
                              ▼                                       ▼
                    sqlite+aiosqlite engine                postgresql+asyncpg engine
                    BEGIN IMMEDIATE (SQLAlchemy            pg_advisory_xact_lock(...)
                    "begin" event listener)                then INSERT...SELECT...WHERE
                    → whole-DB write lock,                 COUNT<capacity, guarded by the
                    phantom-safe by construction            advisory lock (row-level FOR
                                                             UPDATE alone is NOT phantom-safe
                                                             — see Common Pitfalls)
                              │                                       │
                              ▼                                       ▼
                     holds / bookings / idempotency tables (same SQLAlchemy Table metadata,
                     Alembic-versioned, `batch_alter_table` for SQLite parity)

      Contract proof: tests/storage/contract_suite.py runs its ONE test-body set against
      backend_factory ∈ {InMemoryStore, SQLStore+sqlite_engine, SQLStore+pg_engine}

      Concurrency proof (HOLD-02, separate test file, NOT sharing a connection/savepoint
      with the contract suite): testcontainers Postgres ← N real, independently-connected
      asyncio tasks each calling place_hold() concurrently on a capacity-K resource/slot
      → assert successes <= K
```

### Recommended Project Structure
```
src/availability_engine/
├── storage/
│   ├── protocol.py          # unchanged
│   ├── memory.py            # unchanged
│   ├── sql/
│   │   ├── __init__.py
│   │   ├── models.py        # SQLAlchemy Table/MetaData: holds, bookings, idempotency
│   │   ├── store.py         # SQLStore(StorageBackend) — dialect branch lives here only
│   │   └── locking.py       # advisory-lock helper (postgres) / begin-immediate event listener (sqlite)
alembic/
├── env.py                   # render_as_batch=True
├── versions/
│   └── 0001_initial_schema.py   # STORE-05: first commit = current schema, batch_alter_table
tests/
├── storage/
│   ├── contract_suite.py    # test BODIES unchanged; parametrize list extended
│   ├── conftest.py           # NEW: sqlite_engine / pg_container / pg_engine fixtures
│   └── test_concurrency_proof.py   # NEW: HOLD-02, separate from contract_suite's rollback isolation
```

### Pattern 1: Dialect-aware locking is the ONLY branch point
**What:** `SQLStore` has exactly one method (or a small `locking.py` helper) that differs by
`engine.dialect.name`; every other method (schema, query shape, error mapping) is identical across
both dialects.
**When to use:** Any time a "one SQL implementation, two dialects" constraint exists (CLAUDE.md's
locked "Row-lock atomicity" pattern).
**Example (Postgres — advisory lock guards the whole check-then-insert):**
```python
# Source: reasoned from CITED Postgres advisory-lock docs (pgpedia.info,
# postgresql.org function reference) + CITED phantom-insert analysis
# (cybertec-postgresql.com/en/transaction-anomalies-with-select-for-update).
# Two-int32-key overload avoids needing a bigint hash of a string key.
from sqlalchemy import text, func, select

async def place_hold_postgres(conn, resource_id: str, slot_start, slot_end, capacity: int, ttl_seconds: int):
    # Transaction-scoped advisory lock, auto-released on commit/rollback —
    # never leaks on crash (pgpedia.info / postgresql.org fn reference).
    await conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:rid), hashtext(:slot))"),
        {"rid": resource_id, "slot": slot_start.isoformat()},
    )
    active_count = await conn.scalar(
        select(func.count()).select_from(
            select(holds_table.c.id)
            .where(
                holds_table.c.resource_id == resource_id,
                holds_table.c.slot_start == slot_start,
                holds_table.c.expires_at > func.now(),
            )
            .union_all(
                select(bookings_table.c.id).where(
                    bookings_table.c.resource_id == resource_id,
                    bookings_table.c.slot_start == slot_start,
                    bookings_table.c.status == "CONFIRMED",
                )
            )
            .subquery()
        )
    )
    if active_count >= capacity:
        raise CapacityExhaustedError(resource_id, Interval(slot_start, slot_end))
    # INSERT proceeds — safe because the advisory lock, not FOR UPDATE, is what
    # serialized this check against any other concurrent place_hold for the
    # SAME (resource_id, slot_start); a different slot hashes to a different
    # lock key and is not blocked.
    ...
```
**Example (SQLite — BEGIN IMMEDIATE via SQLAlchemy event listener):**
```python
# Source: CITED docs.sqlalchemy.org/en/20/dialects/sqlite.html "Serializable
# isolation / Savepoints / Transactional DDL" section pattern, extended with
# "BEGIN IMMEDIATE" per the documented "disable pysqlite's BEGIN, emit our
# own" recipe (the doc's own example uses bare "BEGIN"; substituting
# "BEGIN IMMEDIATE" is the documented mechanism for choosing SQLite's lock
# mode explicitly, confirmed via a targeted secondary search this session).
from sqlalchemy import event

@event.listens_for(sqlite_engine.sync_engine, "connect")
def _do_connect(dbapi_connection, connection_record):
    dbapi_connection.isolation_level = None  # disable aiosqlite's implicit BEGIN

@event.listens_for(sqlite_engine.sync_engine, "begin")
def _do_begin(conn):
    conn.exec_driver_sql("BEGIN IMMEDIATE")
```
No advisory-lock-equivalent is needed on the SQLite side: `BEGIN IMMEDIATE` acquires the whole-database
RESERVED lock before any read happens in the transaction, so a second concurrent `place_hold`
transaction cannot even begin its count read until the first commits or rolls back — this is
already phantom-safe by construction (there is only ever one writer transaction on a SQLite file at
a time under this mode).

### Pattern 2: Extending `contract_suite.py` without touching test bodies
**What:** `tests/storage/contract_suite.py`'s own module docstring: *"Currently parametrized over
[InMemoryStore] only (Phase 1). Phase 4 adds SQLStore to the single `parametrize` list below without
rewriting any test body in this file"* `[VERIFIED: tests/storage/contract_suite.py:1-6]` — quoted
verbatim. Every test body in that file constructs its backend with a **bare, synchronous** call:
`backend = backend_factory()` `[VERIFIED: tests/storage/contract_suite.py:30, 40, 47, ...
(all 16 test methods use this exact line shape)]` — no `await`, no arguments. This is trivial for
`InMemoryStore` (a plain dataclass with `field(default_factory=dict)` defaults
`[VERIFIED: src/availability_engine/storage/memory.py:43-56]`) but SQL backends need an
already-open `AsyncEngine` and already-created schema before any test body runs, and need a
per-test reset so state doesn't leak between the 16+ test methods (unlike `InMemoryStore()`,
which is trivially fresh on every call).
**When to use:** Any time a shared contract-test file's parametrize axis must grow to include
backends with heavier construction/teardown needs than the original backend.
**Recommended shape — keep the parametrize *decorator* as the extension point, not the test bodies:**
```python
# tests/storage/conftest.py (NEW)
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from availability_engine.storage.sql.models import metadata

@pytest_asyncio.fixture(scope="session")
async def sqlite_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    # ... attach the BEGIN IMMEDIATE event listeners from Pattern 1 ...
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield engine
    await engine.dispose()

@pytest_asyncio.fixture(autouse=True)
async def _reset_sql_tables(sqlite_engine):
    # Runs BEFORE each test body via pytest's fixture injection — the test
    # body's own `backend = backend_factory()` line is never touched.
    async with sqlite_engine.begin() as conn:
        for table in reversed(metadata.sorted_tables):
            await conn.execute(table.delete())
    yield
```
```python
# tests/storage/contract_suite.py — ONLY this decorator line changes:
@pytest.mark.parametrize(
    "backend_factory",
    [InMemoryStore, lambda: SQLStore(sqlite_engine_fixture_value)],  # see note
    ids=["in-memory", "sqlite"],
)
```
**Note on closing over a fixture from a static `parametrize` list:** `pytest.mark.parametrize`'s
argument list is evaluated at collection time, before fixtures exist, so a lambda cannot literally
close over `sqlite_engine`'s runtime value this way. The two working options, in order of
preference for this codebase's existing style:
1. **Indirect parametrization:** change to
   `@pytest.mark.parametrize("backend_factory", ["in-memory", "sqlite", "postgres"], indirect=True)`
   and add a `backend_factory` fixture in `conftest.py` that reads `request.param` and returns
   the right zero-arg factory using the already-built `sqlite_engine`/`pg_engine` fixtures.
2. **Module-level engine singletons** built once at import time in `contract_suite.py` (loses
   proper async fixture teardown; not recommended given `pytest-asyncio` is already the project's
   async-test tool).
Option 1 keeps every `test_*` method body in `contract_suite.py` byte-for-byte unchanged — only the
one `@pytest.mark.parametrize(...)` decorator and a new `conftest.py` change, which matches the file's
own stated contract ("without rewriting any test body").

### Pattern 3: The concurrency proof must NOT share the contract suite's isolation mechanism
**What:** The standard testcontainers+SQLAlchemy per-test isolation pattern is a `connection.begin_nested()`
savepoint that gets rolled back after each test `[CITED: multiple sources cross-referenced — sqlalchemy/sqlalchemy
GitHub Discussion #11658, johal.in "SQLAlchemy Test Utils: Database Rollback Fixtures"]`. This is the
right pattern for `contract_suite.py`'s functional tests against Postgres (fast, isolated, no real
commits pollute state between tests). **It must NOT be reused for the HOLD-02 concurrency proof**,
because that pattern binds all activity to a single shared connection/transaction — the opposite of
"N genuinely concurrent OS-level connections" that CONTEXT.md's `<specifics>` explicitly requires
("an in-process/asyncio-only proof hides the race and is rejected"). The concurrency test needs its
own fixture: a real `AsyncEngine` with a connection pool sized ≥ N, N separate `asyncio.create_task`
calls each opening its own connection and calling `place_hold`, gathered with `asyncio.gather`, and
real commits (schema reset via `DROP SCHEMA/CREATE SCHEMA` or table truncation between concurrency
test cases, not a rolled-back savepoint).

### Anti-Patterns to Avoid
- **Trusting `SELECT ... FOR UPDATE` alone to make a COUNT-based capacity check race-free on
  Postgres:** confirmed this session via `[CITED: cybertec-postgresql.com/en/transaction-anomalies-with-select-for-update]`
  and a Postgres mailing-list thread `[CITED: postgresql.org/message-id/...]` describing exactly this
  "two transactions both see zero matching rows, both proceed" phantom-insert class. `FOR UPDATE`
  locks rows that already satisfy the `WHERE` clause at read time; it has nothing to lock when the
  invariant being protected is "no row yet exists that would trip the count." Use the advisory-lock
  pattern above instead (or a pre-seeded counter row + `UPDATE ... RETURNING`, deferred per
  "Alternatives Considered").
- **Reusing the rollback-savepoint fixture pattern for the HOLD-02 concurrency test** — see Pattern 3.
- **Auto-applying Alembic migrations on `SQLStore.__init__` or engine construction** — D-03 explicitly
  rejects this ("auto-apply takes a coarse write lock and violates 'library owns no runtime
  lifecycle'"); migrations are consumer-run via the Alembic CLI, never triggered by importing the
  library.
- **Using the ORM `Session`/identity-map for the storage layer** — CLAUDE.md's locked stack table
  explicitly rejects this for the exact reason relevant here: "flush-ordering, detached-instance,
  and identity-map complexity" is the last thing wanted in the code paths where correctness under
  concurrency matters most. Use Core (`Table`, `select()`, explicit `async with engine.begin()`).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cross-dialect SQL query construction | Hand-written dialect-branching SQL strings for every query | SQLAlchemy Core `select()`/`insert()` — dialect-agnostic except at the one locking seam | Core's compiler already handles parameter binding, quoting, and dialect differences (e.g. Postgres `NOW()` vs. SQLite's datetime functions) everywhere except the locking primitive itself. |
| SQLite ALTER TABLE limitations | Manual "create new table, copy data, drop old, rename" migration scripts | Alembic `batch_alter_table` (`render_as_batch=True` in `env.py`) | SQLite "has almost no support for the ALTER statement which relational schema migrations rely upon" `[CITED: alembic.sqlalchemy.org/en/latest/batch.html]` — Alembic's batch mode already implements the safe recreate-table dance; hand-rolling it is exactly the kind of "deceptively complex, well-trodden" problem this rule exists for. |
| Concurrent capacity-limiting on Postgres | A custom in-app mutex, Redis lock, or polling retry loop | `pg_advisory_xact_lock` (built into Postgres, transaction-scoped, auto-released) | Purpose-built for exactly this "serialize access to a logical resource, not a specific row" case `[CITED: multiple advisory-lock pattern articles cross-referenced]`; no extra infrastructure (Redis) needed, and no leak risk on crash since it releases with the transaction. |
| Testcontainers lifecycle management | Hand-rolled `subprocess.Popen(["docker", "run", ...])` + polling for readiness | `testcontainers[postgres]`'s `PostgresContainer` context manager | Already solves container startup, port mapping, and readiness polling; explicitly pre-approved for this phase in APPROVED-DEPS.md. |

**Key insight:** every "don't hand-roll" item above has a single, well-known correct primitive
(Alembic batch mode, Postgres advisory locks, testcontainers) — the risk in this phase isn't building
something from scratch, it's *reaching for the wrong built-in primitive* (row-level `FOR UPDATE`)
and getting a false sense of safety because it looks like the "obviously correct" tool.

## Runtime State Inventory

Not applicable — this is a greenfield SQL backend addition, not a rename/refactor/migration of
existing runtime state. Skipping per the trigger condition (no rename/rebrand/refactor in scope).

## Common Pitfalls

### Pitfall 1: The phantom-insert race (the central finding of this research)
**What goes wrong:** A `place_hold` implementation that runs `SELECT COUNT(*) ... FOR UPDATE` (or
even a bare `INSERT ... SELECT ... WHERE (subquery COUNT) < capacity` with no locking at all) against
an empty or under-capacity slot appears correct in every manual/sequential test, then silently
overbooks under real concurrent load — exactly the load HOLD-02's testcontainers proof is designed
to apply.
**Why it happens:** `FOR UPDATE` locks rows that exist and match the `WHERE` clause at the moment of
the read. When two transactions concurrently evaluate "how many active holds exist for this slot"
and the true answer is `capacity - 1` (one seat left) or `0` (still empty), there is no existing row
representing "the seat about to be taken" for either transaction to lock — both read the same stale
count, both pass the check, both insert. This is a documented, named Postgres behavior, not a
project-specific bug `[CITED: cybertec-postgresql.com/en/transaction-anomalies-with-select-for-update]`.
**How to avoid:** Acquire a transaction-scoped Postgres advisory lock keyed on
`(resource_id, slot_start)` as the very first statement of the transaction, before the count read —
see Pattern 1's Postgres example. This serializes concurrent `place_hold` attempts for the *same*
slot without needing any pre-existing row to lock, and releases automatically on commit or rollback
(no leak risk even on a crashed connection).
**Warning signs:** A concurrency test that "usually passes" but occasionally reports `successes > K`
under load, or that only ever fails when N is large enough to guarantee actual connection-level
overlap (small N against a fast local Postgres may never trigger the race even when the code is
wrong) — treat any concurrency test that isn't rock-solid at N ≥ 20 against capacity K = 1 as
suspect, don't just re-run it hoping it passes.

### Pitfall 2: aiosqlite's async API does not mean "doesn't block" — verify, don't assume
**What goes wrong:** Code (and reviewers) assume "it's an async driver" implies "the event loop stays
responsive during a query," and skip verifying it, only to discover under real load that a slow
SQLite query starves other coroutines.
**Why it happens:** aiosqlite's per-connection background thread does keep the *asyncio event loop*
itself unblocked while a query runs `[CITED: aiosqlite.omnilib.dev — "allows interaction with SQLite
databases on the main AsyncIO event loop without blocking execution of other coroutines"]`, but this
is a claim worth confirming at the pinned version rather than assuming from the library's marketing,
per D-05.
**How to avoid:** Write the explicit interleave/yield-point test D-05 calls for: run a "ticker"
coroutine that increments a counter via a tight `asyncio.sleep(0.01)` loop concurrently with an
aiosqlite query (ideally one with an artificial delay, e.g. a `time.sleep` inside a Python UDF, or a
deliberately large table scan), and assert the ticker's counter advanced during the query — proving
loop *responsiveness*, not write *throughput* (SQLite's single-writer model still means true parallel
writes don't happen — that's expected and fine, matching D-05's own framing).
**Warning signs:** A "responsiveness" test that only asserts the query itself completed successfully
— that proves nothing about whether the loop was blocked meanwhile.

### Pitfall 3: SQLite's default pysqlite/aiosqlite transaction handling silently undermines `BEGIN IMMEDIATE`
**What goes wrong:** Adding `conn.execute(text("BEGIN IMMEDIATE"))` inside application code without
first disabling the driver's own implicit `BEGIN` emission does nothing useful — the driver has
already opened a `DEFERRED` transaction before the app's explicit statement runs, or the explicit
statement errors because a transaction is already open.
**Why it happens:** `sqlite3` (and aiosqlite, which wraps it) defaults to legacy transactional
behavior that automatically emits `BEGIN` (deferred) on the first DML statement, not on connect
`[CITED: docs.sqlalchemy.org/en/20/dialects/sqlite.html]`.
**How to avoid:** The two-event-listener pattern in Pattern 1 (`isolation_level = None` on `"connect"`,
explicit `conn.exec_driver_sql("BEGIN IMMEDIATE")` on `"begin"`) is the documented way to take full
control — this is the exact SQLAlchemy-recommended recipe (the docs show `"BEGIN"`; substitute
`"IMMEDIATE"` to get the whole-DB write lock explicitly, confirmed via secondary search this session).
**Warning signs:** `sqlite3.OperationalError: cannot start a transaction within a transaction`, or a
concurrency test that reports the SQLite backend allows overbooking (meaning the lock never actually
took effect).

### Pitfall 4: Wheel-packaging Alembic migrations is explicitly deferred, but the migration *layout* decided now constrains Phase 5
**What goes wrong:** Choosing an `alembic/` directory layout or import structure this phase that
turns out to be awkward to `force-include` into a hatchling wheel later (Phase 5's own gray area
`[packaging]` in `v1.0-DECISION-MAP.md` §Phase 5 explicitly says it "depends on Phase 4's actual
migration layout, so refresh once it exists").
**Why it happens:** Migrations are naturally authored assuming a repo-root `alembic/` directory (the
Alembic default), but a `src/`-layout hatchling package needs migrations to be importable/locatable
from the *installed* wheel, not just the repo checkout.
**How to avoid:** Keep the migration directory at the repo root (`alembic/`, Alembic's default) for
this phase — don't try to solve wheel-packaging now (it's explicitly deferred, per CONTEXT.md's
`<deferred>` section: "Wheel packaging of the Alembic migrations → Phase 5"). Just don't bury it
somewhere Phase 5 can't find, e.g. inside `.venv` or a test-only directory.
**Warning signs:** None yet observable this phase — this is a forward-compatibility note for the
planner, not a defect to fix now.

## Code Examples

### Alembic `env.py` — batch mode + async engine (STORE-05)
```python
# Source: CITED alembic.sqlalchemy.org/en/latest/batch.html (render_as_batch),
# combined with the standard async env.py recipe for SQLAlchemy 2.0 (async
# engine run via run_sync from within Alembic's sync migration runner —
# this bridging pattern is Alembic's own documented async cookbook recipe).
def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,  # safe on Postgres too — batch only activates for SQLite
    )
    with context.begin_transaction():
        context.run_migrations()

async def run_migrations_online():
    connectable = create_async_engine(config.get_main_option("sqlalchemy.url"))
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()
```

### Initial migration — `batch_alter_table` shape (even though the first migration is a create, not an alter)
```python
# Source: reasoned from CITED alembic.sqlalchemy.org/en/latest/batch.html.
# create_table itself needs no batch wrapper (CREATE TABLE works identically
# on both dialects) — batch mode matters starting with migration 0002+ when a
# column gets dropped/altered. Document this explicitly so the planner
# doesn't cargo-cult batch_alter_table onto a bare create_table call.
def upgrade():
    op.create_table(
        "holds",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("resource_id", sa.String, nullable=False),
        sa.Column("slot_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("slot_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Index("ix_holds_resource_slot", "resource_id", "slot_start"),
    )
    # ... bookings, idempotency tables similarly ...
```

### Concurrency proof harness shape (HOLD-02)
```python
# Source: reasoned from CITED testcontainers-python guides
# (lealre.github.io/fastapi-testcontainer-asyncpg) + this session's advisory-
# lock findings. NOT sharing the rollback-savepoint fixture from the
# contract suite (Pattern 3) — this uses independent connections and real
# commits, which is the entire point of the proof.
import asyncio
import pytest
from testcontainers.postgres import PostgresContainer
from sqlalchemy.ext.asyncio import create_async_engine

@pytest.fixture(scope="session")
def pg_container():
    with PostgresContainer("postgres:17", driver="asyncpg") as pg:
        yield pg

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
    assert len(successes) <= 1  # capacity=1
    await engine.dispose()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `python-intervals` for interval-set algebra | `portion` (same author, renamed) | Already resolved in project CLAUDE.md, not this phase's concern | Not applicable to Phase 4 — no interval-set algebra needed until v2 continuous-duration bookings. |
| `encode/databases` for async SQL | SQLAlchemy 2.x async Core/ORM | Archived by maintainer 2025-08-19 (per CLAUDE.md's own sourcing) | Already excluded by CLAUDE.md's "What NOT to Use" — not re-litigated here, just confirmed still current. |

**Deprecated/outdated:** none newly discovered this session beyond what CLAUDE.md already documents.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `pg_advisory_xact_lock(hashtext(:rid), hashtext(:slot))`'s two-int32-key form is the right shape (vs. a single bigint hash) — chosen to avoid needing a bigint-hash helper, but `hashtext` collisions across two different resource/slot pairs hashing to the same `(int, int)` pair are theoretically possible (extremely low probability, not zero) `[ASSUMED — reasoned from CITED signature docs, not verified against a live Postgres instance this session]` | Code Examples, Pattern 1 | A hash collision would over-serialize two *unrelated* slots (a correctness-safe but throughput-costly false conflict) — never causes overbooking, so the risk is purely a rare performance hiccup, not a correctness bug. Confirm during planning/implementation with a live `EXPLAIN`/manual test rather than trusting this document alone. |
| A2 | Alembic `1.19.1` (one version behind the same-day `1.19.2`) is the safer pin | Package Legitimacy Audit | If `1.19.2` in fact contains an important fix, pinning `1.19.1` could miss it — low risk either way since Alembic is a mature, slow-moving tool; the planner should do a 30-second changelog check at execution time rather than trust this guess blindly. |
| A3 | The exact table/column names in the "Code Examples" migration (`holds`, `bookings`, `idempotency`, columns `id`/`resource_id`/`slot_start`/`slot_end`/`expires_at`/`status`) follow directly from the in-memory model's field names `[VERIFIED: src/availability_engine/contracts.py:188-204]` for `Hold`/`Booking`, but the exact SQL column types/nullability/index shape are this researcher's reasonable inference, not something CONTEXT.md or the codebase pins today | Code Examples | Low risk — CONTEXT.md's Claude's Discretion explicitly leaves "exact SQLAlchemy Core query construction" open; the planner has full latitude here as long as the Runtime Decisions' table split and the `(resource_id, slot_start, status)`-equivalent index are honored. |

## Open Questions (RESOLVED — see 04-01-PLAN.md)

1. **Should the advisory-lock finding be treated as overriding D-01, or as a new decision the human should confirm?** _(RESOLVED: orchestrator ruling adopted the advisory-lock fix as an in-scope technical correction under CONTEXT.md's "Claude's Discretion" grant — D-01 was `source: ai-auto`, not human-approved, and the fix preserves schema/isolation-level. Documented as a superseding decision in 04-01-PLAN.md's objective, with HOLD-02 (04-04-PLAN.md) as the empirical proof.)_
   - What we know: D-01 ("defer FOR UPDATE, conditional write is sufficient") is factually incorrect
     for this schema under genuine Postgres concurrency, per the CITED phantom-insert sources this
     session. The Runtime Decisions section's restated "Postgres SELECT ... FOR UPDATE" is also
     insufficient by itself (same reason).
   - What's unclear: Whether the human who resolved D-01 (source: ai-auto, not human) would want
     the advisory-lock approach specifically, versus the SERIALIZABLE+retry or counter-row
     alternatives documented above.
   - Recommendation: The planner should surface this finding explicitly (not silently substitute
     the advisory-lock pattern) — HOLD-02's testcontainers proof is the actual arbiter here: if
     the plan ships the bare conditional-write-only approach and the proof still passes reliably
     at N ≥ 20 / capacity K = 1 across many runs, that would falsify this research's concern; if it
     doesn't, the advisory-lock fix is the documented, portable remedy. Either way, this needs a
     human-visible checkpoint, not a silent code choice, since it revises a "resolved, not
     provisional" decision.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Docker daemon | testcontainers-Postgres concurrency proof (HOLD-02) | ✓ | Docker 29.1.3, daemon running (confirmed via `docker info`/`docker ps` this session) | — |
| SQLite (stdlib) | dev backend | ✓ | 3.45.1 (bundled with system Python 3) | — |
| `uv` | dependency management | ✓ | present at `/home/yahir/.local/bin/uv` (locked project tool per CLAUDE.md) | — |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none — this environment has everything Phase 4 needs
already available.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 + pytest-asyncio 1.4.0 `[VERIFIED: pyproject.toml]`, `asyncio_mode = "auto"` |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` — note `python_files = ["test_*.py", "*_test.py", "contract_suite.py"]` already special-cases `contract_suite.py` for collection `[VERIFIED: pyproject.toml]` |
| Quick run command | `uv run pytest tests/storage/ -x` |
| Full suite command | `uv run pytest` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| STORE-03 | SQLStore satisfies StorageBackend Protocol structurally | unit | `uv run pytest tests/storage/test_protocol_conformance.py -x` | ❌ Wave 0 — needs a new `test_sqlstore_satisfies_protocol` case added to this existing file, mirroring `test_inmemory_satisfies_protocol` `[VERIFIED: tests/storage/test_protocol_conformance.py:7-8]` |
| STORE-04 | Same contract suite passes unmodified against InMemory/SQLite/Postgres | integration | `uv run pytest tests/storage/contract_suite.py -x` | ❌ Wave 0 — extend the `backend_factory` parametrize per Pattern 2; needs new `tests/storage/conftest.py` fixtures (`sqlite_engine`, `pg_container`, `pg_engine`) |
| STORE-05 | Migrations apply cleanly on both dialects, initial = current schema | smoke | `uv run alembic upgrade head` against both a fresh SQLite file and the testcontainers Postgres | ❌ Wave 0 — `alembic/` dir + `0001_initial_schema.py` don't exist yet |
| HOLD-02 | N concurrent place_hold on capacity-K resource → ≤K succeed, real Postgres | integration (concurrency) | `uv run pytest tests/storage/test_concurrency_proof.py -x` | ❌ Wave 0 — new file, see Code Examples harness shape; must NOT reuse the contract suite's per-test rollback fixture (Pattern 3) |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/storage/ -x` (fast — SQLite in-memory + already-warm Postgres container if session-scoped)
- **Per wave merge:** `uv run pytest` (full suite, all backends, all phases' tests)
- **Phase gate:** Full suite green, including the HOLD-02 concurrency proof, before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/storage/conftest.py` — `sqlite_engine` (with BEGIN IMMEDIATE event listeners), `pg_container` (session-scoped `PostgresContainer`), `pg_engine` fixtures, plus the `_reset_sql_tables` autouse fixture (Pattern 2)
- [ ] `src/availability_engine/storage/sql/` — `models.py`, `store.py`, `locking.py` (none exist yet)
- [ ] `alembic/env.py` + `alembic/versions/0001_initial_schema.py` — no Alembic scaffolding exists in the repo yet (confirmed: no `alembic/` directory, no `alembic.ini` found this session)
- [ ] `tests/storage/test_concurrency_proof.py` — new file, HOLD-02
- [ ] `tests/test_aiosqlite_loop_responsiveness.py` (or similar) — new file, D-05's interleave/yield-point test
- [ ] Framework install: `uv add "sqlalchemy>=2.0,<2.1" asyncpg aiosqlite alembic && uv add --group dev "testcontainers[postgres]"`

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | No | Out of scope — library has no auth surface (per REQUIREMENTS.md "Out of Scope": no user/auth). |
| V3 Session Management | No | Not applicable — no session concept in this library. |
| V4 Access Control | No | Not applicable at this layer — consumer's responsibility. |
| V5 Input Validation | Yes | Already handled at the Pydantic boundary (`contracts.py`'s `UtcDatetime`/`Resource`/etc. `[VERIFIED: src/availability_engine/contracts.py]`); the SQL layer's job is to use bound parameters exclusively (SQLAlchemy Core's `select()`/`insert()` parameter binding — never raw string interpolation into SQL, including the advisory-lock `text()` call above, which uses named bind parameters `:rid`/`:slot`, not f-string interpolation). |
| V6 Cryptography | No | No cryptographic operations in this phase. |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|----------------------|
| SQL injection via string-built queries (e.g. a careless dialect-branch that f-string-interpolates `resource_id` into a raw SQL string for the advisory-lock call or a hand-rolled dialect check) | Tampering | SQLAlchemy Core `text()` with named bind parameters (as shown in Pattern 1's example) or `select()`/`insert()` constructs exclusively; never string-format a value into SQL text. Existing `errors.py` already establishes the project's security discipline here — exception constructors never accept payload contents `[VERIFIED: src/availability_engine/errors.py:1-11]`, and the same "never trust/interpolate untrusted-adjacent strings" discipline extends to the SQL layer. |
| Idempotency-table unbounded growth used as a resource-exhaustion vector | Denial of Service | Runtime Decisions already flags this: "needs an explicit retention/cleanup policy (an unbounded idempotency table has real operational cost in SQL)" — out of full scope for this phase per `<deferred>` ("SQL idempotency retention/cleanup reaper... keep minimal for v1"), but the schema should not make retention structurally impossible later (e.g., include a `created_at` column even if no reaper runs yet). |
| Alembic auto-apply on library import taking an unexpected write lock | Denial of Service (self-inflicted) | Already resolved by D-03: consumer-run migrations only, never triggered by constructing `AvailabilityEngine` or `SQLStore`. |

## Sources

### Primary (HIGH confidence)
- PyPI JSON API (`pypi.org/pypi/<pkg>/json`) — direct registry query this session for `sqlalchemy`, `asyncpg`, `aiosqlite`, `alembic`, `testcontainers` current versions and publish dates.
- `gsd-tools query package-legitimacy check --ecosystem pypi` — this session, all 5 packages.
- Direct `Read` of `src/availability_engine/{contracts.py, errors.py, engine.py}`, `src/availability_engine/storage/{protocol.py, memory.py}`, `src/availability_engine/core/intervals.py`, `tests/storage/{contract_suite.py, test_protocol_conformance.py}`, `tests/conftest.py`, `pyproject.toml` — this session, with line-ranged quotes above.
- `docker info` / `docker ps` — this session, confirmed Docker daemon running.

### Secondary (MEDIUM confidence — WebFetch/WebSearch cross-referenced against official docs)
- `docs.sqlalchemy.org/en/20/dialects/sqlite.html` (WebFetch, this session) — BEGIN-control event-listener recipe.
- `alembic.sqlalchemy.org/en/latest/batch.html` (WebFetch, this session) — `render_as_batch`, cross-dialect safety of batch mode.
- `lealre.github.io/fastapi-testcontainer-asyncpg` (WebFetch, this session) — testcontainers-Postgres async fixture shape.
- `cybertec-postgresql.com/en/transaction-anomalies-with-select-for-update` and a `postgresql.org` mailing-list thread (WebSearch, this session) — the phantom-insert race finding central to this research.
- `pgpedia.info/p/pg_advisory_xact_lock.html` + PostgreSQL official function reference (WebSearch, this session) — advisory lock signatures (`bigint` and two-`integer` overloads).
- `aiosqlite.omnilib.dev` (WebSearch, this session) — background-thread architecture claim underlying D-05.

### Tertiary (LOW confidence — single-source or inferred, flagged in Assumptions Log)
- The two-int32-key `hashtext`/`hashtext` advisory-lock pairing (A1) — reasoned, not independently verified against a live Postgres instance this session.
- Alembic `1.19.1` vs `1.19.2` pin choice (A2) — a same-day-release soak-time caution, not a verified defect in `1.19.2`.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — versions VERIFIED directly from PyPI registry, all five packages already human-approved in APPROVED-DEPS.md.
- Architecture (schema/protocol): HIGH — VERIFIED by direct Read of the landed Phase 1-3 source with line-ranged quotes.
- Locking/concurrency mechanics: MEDIUM-HIGH — the phantom-insert finding is CITED from multiple independent, authoritative-adjacent sources (Postgres mailing list + a specialized Postgres consultancy's technical writeup) and is internally consistent with well-known Postgres MVCC semantics, but was not verified this session against a live Postgres instance (no `psql`/testcontainers run performed) — flagged as an Open Question for human confirmation given it revises a "resolved" decision.
- Alembic/testcontainers patterns: MEDIUM — CITED from official/near-official docs, standard and unsurprising.

**Research date:** 2026-09-04
**Valid until:** 30 days (stable, mature ecosystem — SQLAlchemy/Postgres/Alembic move slowly; re-verify exact pins if this research is reused past ~2026-10-04)
