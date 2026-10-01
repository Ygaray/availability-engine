"""HOLD-02 concurrency proof — the empirical arbiter of `locking.py`'s
`pg_advisory_xact_lock` fix, which supersedes CONTEXT.md's D-01 ("defer
`SELECT ... FOR UPDATE`, rely solely on the atomic conditional-write
statement") and the Runtime Decisions section's restated "Postgres
`SELECT ... FOR UPDATE`". RESEARCH.md documents that both are unsafe against
genuinely concurrent Postgres connections for this schema: `FOR UPDATE`
cannot lock a row that does not yet exist, so two concurrent transactions can
both count zero prior holds for an empty slot and both insert, overbooking
capacity 1 to 2 (a documented Postgres phantom-insert race, cited in
RESEARCH.md's "Pitfall 1" from cybertec-postgresql.com's transaction-anomaly
analysis). This test — not a code review of `locking.py` alone — is what
Phase 4's HOLD-02 requirement rests on: it opens N genuinely independent,
real OS-level connections against a real Postgres container and proves the
advisory-lock fix, not D-01's literal text, is what makes `place_hold` safe
under real concurrent load.

Per RESEARCH.md Pattern 3, this file deliberately does NOT import or reuse
tests/storage/conftest.py's `pg_container`/`pg_engine` fixtures or
contract_suite.py's rollback/table-delete isolation wrapper — binding all
activity to one shared connection/transaction is the opposite of the
genuinely-concurrent-OS-connections requirement HOLD-02 exists to prove. This
file opens its own session-scoped Postgres container and its own AsyncEngine,
sized so every concurrent task can hold an open connection simultaneously
(an undersized pool would silently serialize calls at the connection-
checkout layer, passing the assertion for the wrong reason — queueing, not
the advisory lock — and producing a false proof).
"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, time, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from testcontainers.postgres import PostgresContainer

from availability_engine.contracts import (
    DEFAULT_BUSINESS_ID,
    Booking,
    LocalInterval,
    Resource,
    Weekday,
)
from availability_engine.core.intervals import Interval
from availability_engine.errors import CapacityExhaustedError, HoldNotFoundError
from availability_engine.storage.sql import models
from availability_engine.storage.sql.store import SQLStore

# Largest N used below (K=3/N=30 case) — the pool must be sized so every one
# of the N concurrent tasks can hold its own open connection simultaneously,
# never queueing at checkout (RESEARCH.md must_haves key_links).
_MAX_N = 30

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture(scope="session")
def concurrency_pg_container() -> Iterator[PostgresContainer]:
    # Own, dedicated container — not tests/storage/conftest.py's pg_container
    # — so this file's connections are never coincidentally shared with the
    # contract suite's rollback-isolated fixtures (Pattern 3).
    with PostgresContainer("postgres:17", driver="asyncpg") as pg:
        yield pg


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def concurrency_pg_engine(
    concurrency_pg_container: PostgresContainer,
) -> AsyncIterator[AsyncEngine]:
    # pool_size >= _MAX_N so every concurrent task gets its own real,
    # independently-checked-out connection — an undersized pool would
    # silently serialize calls at checkout, which would pass the assertion
    # for the wrong reason (queueing, not the advisory lock).
    engine = create_async_engine(
        concurrency_pg_container.get_connection_url(),
        pool_size=_MAX_N + 10,
        max_overflow=0,
    )
    async with engine.begin() as conn:
        await conn.run_sync(models.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def _reset_concurrency_tables(concurrency_pg_engine: AsyncEngine) -> None:
    # Explicit row deletion (not a rolled-back savepoint — this file
    # deliberately avoids the contract suite's isolation mechanism per
    # Pattern 3) so the K=1/N=25 and K=3/N=30 cases below do not interfere
    # with each other.
    async with concurrency_pg_engine.begin() as conn:
        for table in reversed(models.metadata.sorted_tables):
            await conn.execute(table.delete())


def _make_resource(resource_id: str, capacity: int) -> Resource:
    return Resource(
        id=resource_id,
        capacity=capacity,
        operating_hours={
            Weekday.MONDAY: [LocalInterval(start=time(0, 0), end=time(23, 59))],
        },
        buffer=timedelta(minutes=0),
        timezone="UTC",
        slot_duration=timedelta(minutes=30),
    )


async def test_concurrent_place_hold_never_exceeds_capacity_k1(
    concurrency_pg_engine: AsyncEngine,
) -> None:
    store = SQLStore(concurrency_pg_engine)
    resource = _make_resource("concurrency-k1", capacity=1)
    await store.save_resource(resource)
    slot = Interval(
        start=datetime(2026, 9, 7, 15, 0, tzinfo=UTC),
        end=datetime(2026, 9, 7, 15, 30, tzinfo=UTC),
    )

    n = 25
    results = await asyncio.gather(
        *(
            store.place_hold(
                DEFAULT_BUSINESS_ID,
                resource.id,
                slot,
                capacity=resource.capacity,
                ttl_seconds=60,
            )
            for _ in range(n)
        ),
        return_exceptions=True,
    )

    successes = [r for r in results if not isinstance(r, Exception)]
    failures = [r for r in results if isinstance(r, Exception)]

    # Not merely `<= 1` — exactly 1 also proves the lock does not
    # UNDER-serialize and spuriously reject a call that should have
    # succeeded.
    assert len(successes) == 1, (
        f"expected exactly 1 success for capacity=1/N={n}, got "
        f"{len(successes)}: {successes}"
    )
    assert len(failures) == n - 1
    for exc in failures:
        assert isinstance(exc, CapacityExhaustedError), (
            f"expected CapacityExhaustedError, got {type(exc)!r}: {exc!r}"
        )


async def test_concurrent_place_hold_never_exceeds_capacity_k3(
    concurrency_pg_engine: AsyncEngine,
) -> None:
    # RESEARCH.md explicitly warns that a small N against a fast local
    # Postgres may never trigger the race even when the underlying code is
    # wrong — this second, larger case hardens the proof rather than resting
    # on a single capacity/N combination.
    store = SQLStore(concurrency_pg_engine)
    resource = _make_resource("concurrency-k3", capacity=3)
    await store.save_resource(resource)
    slot = Interval(
        start=datetime(2026, 9, 7, 15, 0, tzinfo=UTC),
        end=datetime(2026, 9, 7, 15, 30, tzinfo=UTC),
    )

    n = 30
    results = await asyncio.gather(
        *(
            store.place_hold(
                DEFAULT_BUSINESS_ID,
                resource.id,
                slot,
                capacity=resource.capacity,
                ttl_seconds=60,
            )
            for _ in range(n)
        ),
        return_exceptions=True,
    )

    successes = [r for r in results if not isinstance(r, Exception)]
    failures = [r for r in results if isinstance(r, Exception)]

    assert len(successes) == 3, (
        f"expected exactly 3 successes for capacity=3/N={n}, got "
        f"{len(successes)}: {successes}"
    )
    assert len(failures) == n - 3
    for exc in failures:
        assert isinstance(exc, CapacityExhaustedError), (
            f"expected CapacityExhaustedError, got {type(exc)!r}: {exc!r}"
        )


async def test_concurrent_confirm_and_release_never_leaves_phantom_booking(
    concurrency_pg_engine: AsyncEngine,
) -> None:
    # CR-01 regression: confirm_hold must never materialize a Booking from
    # its pre-DELETE hold_row snapshot when that row was concurrently
    # removed by release_hold between confirm_hold's SELECT and its own
    # DELETE (DELETE matches 0 rows). Runs many real concurrent iterations
    # against genuinely independent connections (matching this file's
    # existing approach — no forced single interleaving) so some
    # iterations empirically land in that exact race window.
    store = SQLStore(concurrency_pg_engine)
    resource = _make_resource("concurrency-cr01", capacity=1)
    await store.save_resource(resource)
    slot = Interval(
        start=datetime(2026, 9, 7, 15, 0, tzinfo=UTC),
        end=datetime(2026, 9, 7, 15, 30, tzinfo=UTC),
    )

    iterations = 50
    for _ in range(iterations):
        hold = await store.place_hold(
            DEFAULT_BUSINESS_ID,
            resource.id,
            slot,
            capacity=resource.capacity,
            ttl_seconds=60,
        )

        confirm_result, release_result = await asyncio.gather(
            store.confirm_hold(hold.id),
            store.release_hold(hold.id),
            return_exceptions=True,
        )

        # release_hold is documented as an idempotent no-op regardless of
        # whether the hold still exists — it must never raise here.
        assert not isinstance(release_result, Exception), release_result

        active = await store.get_active_entries(DEFAULT_BUSINESS_ID, resource.id, slot)

        if isinstance(confirm_result, HoldNotFoundError):
            # release_hold "won" this iteration's race — confirm_hold
            # correctly detected its DELETE matched 0 rows and raised,
            # rather than materializing a phantom Booking from the stale
            # hold_row snapshot (the CR-01 bug). The slot must be fully
            # free again, not still occupied by a phantom Booking.
            assert active == [], (
                "CR-01 regression: confirm_hold lost the race to a "
                f"concurrent release_hold but left {active!r} active — a "
                "phantom Booking or stray Hold survived a release."
            )
        elif isinstance(confirm_result, Exception):
            raise AssertionError(
                f"unexpected exception from confirm_hold: {confirm_result!r}"
            )
        else:
            # confirm_hold "won" the race — a legitimate Booking now
            # occupies the slot; release_hold's concurrent DELETE was a
            # correct no-op against an already-consumed hold.
            assert len(active) == 1
            assert isinstance(active[0], Booking)
            # Free the capacity-1 slot before the next iteration's
            # place_hold — a legitimate "confirm wins" outcome must not
            # poison every subsequent iteration with a permanently
            # occupied slot (the Booking id equals the original hold.id
            # per confirm_hold's insert).
            await store.cancel_booking(hold.id)
