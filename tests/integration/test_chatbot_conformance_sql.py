"""SQLStore-backed conformance proof (review round-2/3 HIGH, cluster: "conformance
uses InMemoryStore, not SQLStore") — the duration-aware search, buffer-fetch-window
widening, blocked-interval exclusion, and business_id-column scoping Plan 26-09 built
are ALL implemented in `storage/sql/store.py`; an InMemoryStore-only conformance run
(`test_chatbot_conformance.py`) cannot prove any of that SQL-specific behavior
actually works end to end, even though `InMemoryStore` got equivalent logic in Plan
26-09 Task 2.

Mirrors the source repo's own `TestRealEngineSqlBackedConformance` fixture pattern
(`tests/consumers/test_availability_engine_conformance.py`, Plan 26-04): tears down
via the single, established `close_availability_engine(adapter)` helper — never a
hand-rolled `engine.close()` + `await engine.dispose()` pair across two DIFFERENT
objects (the `SyncAvailabilityEngine`'s background thread vs. the SQLAlchemy
`AsyncEngine`'s connection pool). `close_availability_engine` already resolves both
hops off `adapter` alone (unwrapping any `_BusinessScopedPort` first) and disposes
the SQL engine on the correct background loop -- see `examples/chatbot_adapter.py`'s
WR-01/WR-05 docstring for why a hand-rolled pair is the exact leak this centralizes.

A brand-new throwaway SQLite database needs no Alembic migration chain -- unlike a
PRODUCTION bootstrap, which must carry `0002`'s ALTER against pre-existing data.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Generator
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

import pytest
from chatbot_engine.availability.port import AvailabilityPort, Hold, Slot
from chatbot_engine.availability.testing.contract import AvailabilityContractSuite
from examples.chatbot_adapter import (
    AvailabilityEngineAdapter,
    close_availability_engine,
)
from sqlalchemy.ext.asyncio import create_async_engine

from availability_engine.contracts import LocalInterval, Resource, Weekday
from availability_engine.storage.sql import models
from availability_engine.storage.sql.store import SQLStore
from availability_engine.sync import SyncAvailabilityEngine

_RESOURCE_ID = "conformance-resource-sql"


async def _create_schema(database_url: str) -> None:
    schema_engine = create_async_engine(database_url)
    try:
        async with schema_engine.begin() as conn:
            await conn.run_sync(models.metadata.create_all)
    finally:
        await schema_engine.dispose()


class TestChatbotConformanceSql(AvailabilityContractSuite):
    """Same shared `AvailabilityContractSuite`, now proven against the REAL
    SQL-backed engine (SQLite via `SQLStore`), not only `InMemoryStore`
    (`TestChatbotConformance` in `test_chatbot_conformance.py`).

    Class-body fixtures below shadow the module-level `port`/`_query_window`/
    `one_available_slot`/`no_available_slot`/`held_slot` fixtures
    `tests/integration/conftest.py` declares, for every test in THIS class
    only -- the same class-body fixture-precedence technique the source
    repo's own `TestRealEngineSqlBackedConformance` uses, avoiding a name
    collision with `TestChatbotConformance`'s module-level fixtures.
    """

    @pytest.fixture
    def port(self, tmp_path: Path) -> Generator[AvailabilityPort, None, None]:
        database_url = f"sqlite+aiosqlite:///{tmp_path}/conformance.db"
        asyncio.run(_create_schema(database_url))

        engine = create_async_engine(database_url)
        store = SQLStore(engine)
        sync_engine = SyncAvailabilityEngine(store)
        sync_engine.define_resource(
            Resource(
                id=_RESOURCE_ID,
                capacity=1,
                # All seven weekdays, near-full-day hours, so the fixture
                # produces multiple 30-minute slots regardless of which
                # calendar day the suite actually runs on -- same shape as
                # tests/integration/conftest.py's existing port fixture.
                operating_hours={
                    weekday: [LocalInterval(start=time(0, 0), end=time(23, 59))]
                    for weekday in Weekday
                },
                buffer=timedelta(minutes=0),
                timezone="America/Chicago",
                slot_duration=timedelta(minutes=30),
            )
        )
        adapter = AvailabilityEngineAdapter(sync_engine)
        try:
            yield adapter
        finally:
            # Review concern (cycle-3 MEDIUM): the ESTABLISHED single-object
            # teardown path, not a hand-rolled `engine.close()` +
            # `await engine.dispose()` pair across two different objects.
            close_availability_engine(adapter)

    @pytest.fixture
    def _query_window(self) -> tuple[datetime, datetime]:
        now = datetime.now(UTC)
        return now, now + timedelta(days=2)

    @pytest.fixture
    def one_available_slot(
        self, port: AvailabilityPort, _query_window: tuple[datetime, datetime]
    ) -> Slot:
        slots = port.query_availability(_RESOURCE_ID, _query_window, party_size=1)
        assert slots, "expected at least one available slot in the query window"
        return slots[0]

    @pytest.fixture
    def no_available_slot(
        self,
        port: AvailabilityPort,
        _query_window: tuple[datetime, datetime],
        one_available_slot: Slot,
    ) -> Slot:
        slots = port.query_availability(_RESOURCE_ID, _query_window, party_size=1)
        candidates = [s for s in slots if s.slot_id != one_available_slot.slot_id]
        assert candidates, "expected a second distinct slot in the query window"
        target = candidates[0]
        # Pre-exhaust this specific slot's one unit of capacity -- distinct
        # from one_available_slot's own slot, so it stays untouched.
        port.place_hold(target.slot_id, ttl_seconds=300, idempotency_key=str(uuid.uuid4()))
        return target

    @pytest.fixture
    def held_slot(self, port: AvailabilityPort, one_available_slot: Slot) -> Hold:
        return port.place_hold(
            one_available_slot.slot_id, ttl_seconds=300, idempotency_key=str(uuid.uuid4())
        )
