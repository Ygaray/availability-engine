# Milestones

## v1.0 v1 Release (Shipped: 2026-09-05)

**Phases completed:** 5 phases, 17 plans, 37 tasks

**Key accomplishments:**

- A real AvailabilityEngine over InMemoryStore — define resource, sweep-line free-fragment computation, fixed-duration grid, and atomic hold/confirm/release — proven end to end by one integration test, with ruff/mypy --strict clean on src/.
- Seven new passing unit tests proving contracts.py's boundary rejections (capacity, IANA timezone, UTC-only datetimes) and core.intervals/core.grid's frozen half-open Interval and buffer-aware grid_slots() semantics — zero production code changes.
- Proved InMemoryStore's structural Protocol conformance, stood up Phase 4's SQLStore-ready parametrized contract suite, and added three engine tests proving capacity exhaustion rejection, opaque-payload non-leakage, and idempotent release — all against Plan 01-01's existing implementation, zero production code changes.
- Fixed the one verified `time.py::localize_operating_hours` midnight-crossing bug and fixture-proved the existing UTC-boundary-conversion design is already DST-correct by construction on real 2026 America/New_York transition dates, with zero changes to `core/grid.py`.
- Collapsed `InMemoryStore`'s two duplicated, non-expiry-filtering active-entries scans into one shared `get_active_entries()` primitive that correctly excludes expired holds, fixing the real, verified AVAIL-03/HOLD-05 gap where an unreleased expired hold blocked capacity forever.
- Restructured `AvailabilityResult` into the two-list `available`/`booked` capacity-shape contract, rebased every domain exception onto a closed `ReasonCode` enum, added the new `OutsideHoursError` check to `place_hold`, and froze the result with a golden-file conformance test plus a hypothesis-proven capacity invariant.
- Wired `cancel_booking` end-to-end (Protocol → InMemoryStore → AvailabilityEngine facade) as a distinct, non-idempotent terminal-status operation on confirmed bookings — cancelling frees capacity immediately, and unknown/already-cancelled/hold ids are always rejected with `BookingNotFoundError`.
- Wired `idempotency_key` end-to-end through `AvailabilityEngine.place_hold`/`confirm_hold` into `InMemoryStore`'s lock-guarded critical sections — a same-key/same-args replay returns the original `Hold`/`Booking`, a same-key/different-args replay raises `IdempotencyConflictError`, and a concurrent same-key race (proven via `asyncio.gather`) never double-consumes capacity.
- SQLStore's Postgres dialect path proven correct against the identical, unmodified 51-case shared contract suite already proven correct for SQLite — testcontainers Postgres 17 wired via session-scoped fixtures, no store.py changes needed.
- Versioned Alembic migrations (SQLite + real testcontainers Postgres, both proven identical) plus an empirical, non-assumed confirmation that aiosqlite keeps the asyncio event loop responsive during a query (D-05).
- Empirically proved no-overbooking under 25 and 30 genuinely concurrent, independently-connected real Postgres callers via a dedicated testcontainers fixture, then closed out Phase 4 with a fully green 110-test project-wide gate.
- Fixed the confirmed D-05 packaging bug: the wheel now ships Alembic migrations via a hatchling `force-include`, proven by a real `uv build` → fresh venv → `pip install` → `alembic upgrade head` round trip that creates all four tables.
- Shipped the thin `SyncAvailabilityEngine` background-thread bridge (D-04) so the consumer's synchronous `AvailabilityPort` can call this engine inline from its own already-running event loop, without hitting `asyncio.run()`'s running-loop crash -- proven by a real loop-in-loop regression test, not just reasoned about.
- Proved D-02/D-03/PKG-03 end to end: dev-depended on the consumer's `AvailabilityContractSuite` via a pinned, pushed `v1.0` git tag, and shipped `examples/chatbot_adapter.py` -- a real `AvailabilityPort`-conforming adapter over `SyncAvailabilityEngine` that passes all 10 inherited contract tests, including the idempotency-after-confirm edge case the research flagged as an open gap.
- Rewrote README.md from a pre-planning scaffold stub into the frozen, documented product surface (PKG-02) -- both engine facades, the storage protocol, the output contract, the exact dialect-aware locking mechanisms Phase 4 proved, and fixture-tested TZ/DST semantics -- with every code example proven to run against the real installed API by a new automated test rather than a manual read-through.
- Cut and pushed the `v0.1.0` annotated git tag to origin at commit `3fc81b2` -- the first artifact SocialNetwork-Chatbot's already-committed `[tool.uv.sources]` pin seam resolves against -- gated by the operator's prior explicit approval and reconfirmed green (139 core tests + 13 conformance tests) at execution time before the one-way tag push.

---
