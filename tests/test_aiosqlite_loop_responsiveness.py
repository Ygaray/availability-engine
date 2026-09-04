"""D-05 — verify aiosqlite's async driver does not block the event loop.

aiosqlite's per-connection background thread keeps calls awaitable, and the
event loop should stay responsive while a query runs — but "async API" does
not automatically mean "doesn't block" (RESEARCH.md Pitfall 2). This test
proves it empirically at the pinned aiosqlite==0.22.1 version rather than
assuming it from the driver's documentation: a ticker coroutine, running
concurrently (asyncio.gather) with an aiosqlite query carrying an artificial
~0.3s delay, must keep advancing its counter DURING the slow query — proving
the event loop kept running while the query was in flight, not just that the
query eventually completed.

This does NOT prove SQLite achieved parallel writes — SQLite's single-writer
model is unaffected by this and that is expected, not a defect (D-05's own
framing).
"""

import asyncio
import time
from pathlib import Path

import aiosqlite

SLOW_QUERY_DELAY_SECONDS = 0.3
TICKER_INTERVAL_SECONDS = 0.01


async def _ticker(counter: list[int], stop_event: asyncio.Event) -> None:
    """Increment counter[0] once per TICKER_INTERVAL_SECONDS until stopped."""
    while not stop_event.is_set():
        await asyncio.sleep(TICKER_INTERVAL_SECONDS)
        counter[0] += 1


def _blocking_sleep(seconds: float) -> int:
    # The Python UDF body registered via create_function — runs in
    # aiosqlite's background thread, not on the event loop itself. Returns
    # an int because SQLite UDFs need a SQL-representable return value.
    time.sleep(seconds)
    return 1


async def _slow_query(db_path: Path, stop_event: asyncio.Event) -> None:
    """Run one aiosqlite query carrying an artificial ~0.3s delay.

    Registers a Python UDF (via the raw driver connection's
    create_function) that calls time.sleep, then SELECTs it — RESEARCH.md's
    Pitfall 2 recipe.
    """
    async with aiosqlite.connect(str(db_path)) as conn:
        await conn.create_function("slow_sleep", 1, _blocking_sleep)
        await conn.execute("SELECT slow_sleep(?)", (SLOW_QUERY_DELAY_SECONDS,))
    stop_event.set()


async def test_ticker_advances_during_slow_aiosqlite_query(tmp_path: Path) -> None:
    db_path = tmp_path / "responsiveness.db"
    counter = [0]
    stop_event = asyncio.Event()

    start = time.monotonic()
    await asyncio.gather(
        _ticker(counter, stop_event),
        _slow_query(db_path, stop_event),
    )
    elapsed = time.monotonic() - start

    # The slow query alone takes ~SLOW_QUERY_DELAY_SECONDS; if the event
    # loop were blocked during it, the ticker would advance ~0 times. A
    # responsive loop should have advanced roughly elapsed / interval times
    # (with generous headroom for scheduling jitter — not an exact count).
    expected_min_ticks = int((elapsed / TICKER_INTERVAL_SECONDS) * 0.5)

    assert elapsed >= SLOW_QUERY_DELAY_SECONDS
    assert counter[0] >= expected_min_ticks
    # A blocked loop would produce ~0 ticks regardless of elapsed time —
    # guard explicitly against that degenerate case too.
    assert counter[0] > 5
