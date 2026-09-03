# Project Research Summary

**Project:** availability-engine
**Researched:** 2026-09-02
**Milestone:** v1.0

## Executive Summary

This is a domain-agnostic async Python scheduling library designed to power atomic reservation systems (chatbots, booking apps, escape rooms, salons) without baking in domain vocabulary. The core value is deterministic availability computation and capacity-safe hold placement that guarantees no double-booking under concurrent load, all while maintaining correctness across timezones and DST transitions.

**Atomicity model:** Correctness lives entirely in the storage backend via a coarse-grained protocol, not in application code. The engine orchestrates read-then-compute over storage reads, but the moment of truth—placing a hold—is a single atomic SQL statement (`INSERT ... WHERE (SELECT COUNT(*) ...) < capacity` with rowcount verification) or equivalent atomic operation in the in-memory store. This pattern makes the library portable across SQLite (single-writer serialization via `BEGIN IMMEDIATE`) and Postgres (row-level MVCC via `SELECT ... FOR UPDATE`) without dialect branches in the engine itself.

**Timezone correctness:** Built in from day one, non-negotiable. Operating hours are stored as per-resource IANA zone + local wall-clock times (how humans configure resources). Slot grids are generated per concrete calendar date, so DST transitions (spring-forward gaps, fall-back ambiguities) resolve correctly. All internal computation happens in UTC; the facade's `time.py` is the only place that imports `zoneinfo`. Combined with half-open interval representation and sweep-line capacity counting (not binary subtraction), this gives capacity ≥ 1 full expressiveness from v1 without architectural rework.

**Contract-first design is non-negotiable:** A parallel consumer (the reusable chatbot backend) is coding against a stubbed structured output contract while this library is built. Storage protocol is designed backend-agnostically first (not derived from SQL implementation), proven by running identical contract tests against in-memory, SQLite, and Postgres implementations in parallel.

## Key Findings

### From STACK.md

**Core Stack:**
- Python 3.12+, stdlib `datetime` + `zoneinfo` (not Pendulum; avoids imposing a third-party datetime type on every consumer)
- SQLAlchemy 2.0.x async Core (not ORM; row-lock atomicity requires explicit statement composition)
- asyncpg (Postgres), aiosqlite (SQLite)
- Pydantic v2 for public contract serialization; frozen `@dataclass(slots=True)` for internal value objects (2–3x faster for grid generation)
- Hand-rolled half-open `Interval` type for v1 (defer full algebra library `portion` until arbitrary-duration bookings are added)
- pytest-asyncio, time-machine (100–200x faster than freezegun; critical for hold-expiry + DST tests), hypothesis (property-based interval math), testcontainers[postgres] (concurrency verification)
- ruff, mypy --strict, pre-commit

**Anti-patterns explicitly rejected:**
- SQLAlchemy ORM (Session, identity map, flush ordering add noise to atomic transactions)
- encode/databases (archived, read-only as of 2025-08-19)
- Naive datetimes anywhere in the engine (runtime assertions required at every public boundary)
- Relying on `with_for_update()` alone for atomicity on SQLite (it's a no-op there; must use `BEGIN IMMEDIATE`)

### From FEATURES.md

**Table Stakes (v1 must-haves):**
- Resource model: capacity ≥ 1, per-day operating hours, buffer/reset time, IANA timezone
- Fixed-duration slot grid generation from hours + slot length + buffer
- Capacity-aware ranged availability query (available/booked windows)
- **Atomic hold placement with capacity check** (single SQL statement; no separate read + write)
- Hold → confirm → booking lifecycle with opaque consumer payload
- Explicit hold release + lazy TTL expiry (predicate: `expires_at > now`, never a state transition)
- **Idempotency keys on hold/confirm operations** (network-facing retries; flagged as likely v1 implementation gap)
- Pluggable async storage protocol + in-memory reference implementation
- SQL storage targeting SQLite (dev) + Postgres (prod) with row-lock atomicity
- Stable, documented structured output contract (frozen early for parallel consumer to code against)
- Cancellation of confirmed bookings

**Differentiators (post-v1, triggered by real consumer need):**
- Multi-resource / next-available query (fan-out + merge)
- Free/busy window mode (merged intervals) alongside slot-list
- Rescheduling as first-class atomic operation (not cancel + rebook)
- Rich rejection reason codes (capacity_exhausted, outside_hours, blackout, hold_expired, not_found, idempotency_conflict)

**Structured output shape:**
- Two modes from one internal truth: slot-list (discrete grid items) + free/busy windows (merged intervals)
- Capacity as a count, never collapsed to a boolean
- Machine-readable rejection reason codes
- Opaque payload rounds-trips untouched

**Anti-features (explicitly deferred):**
- Recurrence (RRULE), holidays → v1 has per-day hours + simple blackout dates only
- Arbitrary-duration bookings → v1 is fixed-grid; internal [start, end) design preps for v2 addition
- Pricing, notifications, user/auth, UI, calendar sync → consumer concerns
- Background sweeper for hold expiry → lazy-on-read only; library owns no runtime lifecycle

### From ARCHITECTURE.md

**Atomicity seam: Coarse-grained storage protocol**
- `StorageBackend` Protocol exposes only whole-operation methods: `place_hold()`, `confirm_hold()`, `release_hold()`, `get_active_entries()`, `get_resource()`
- Every method is exactly one atomic operation; Protocol never exposes a transaction object
- Enforced structurally: `engine.py` written against Protocol type, never a concrete backend
- In-memory impl: single `asyncio.Lock` guarding the store (test/dev scoped)
- SQLStore: correctness from database's single-statement atomicity; no Python-level lock needed (wouldn't survive across processes)

**Portable atomicity pattern (the load-bearing design):**
- Single `INSERT ... SELECT ... WHERE (SELECT COUNT(*) ...) < capacity` statement with rowcount check
- On SQLite: wrap all write transactions in `BEGIN IMMEDIATE` (acquires write lock upfront; serializes writers)
- On Postgres: optional `SELECT ... FOR UPDATE` on resource/slot row (reduces contention but not required for correctness; WHERE clause is already atomic)
- Same Python code, same SQLAlchemy Core statement; dialect differences absorbed by SQLAlchemy
- Verify atomicity against both backends via testcontainers Postgres (N concurrent place_hold calls against capacity-1 resource → exactly 1 succeeds)

**Sweep-line capacity accounting (not binary interval subtraction):**
- Every hold/booking is a (+1 at start, -1 at end+buffer) event pair
- Sort all events for the query window, sweep left-to-right accumulating running "in-use count"
- A time interval is available iff count < capacity
- Generalizes for all capacity values >= 1; capacity-1 degenerates to plain interval subtraction
- Buffers applied by extending each busy interval's effective end before event generation

**Time boundary (TZ handling lives here only):**
- `time.py::localize_operating_hours(resource, date_range) -> Interval[]` converts per-resource IANA local hours + concrete dates → UTC
- Called only by engine.py facade, never by core; core imports no `zoneinfo`
- DST correctness via per-date conversion (not memoized): spring-forward and fall-back transitions resolve correctly for each date queried
- Output contract carries UTC datetimes only (ISO 8601 with offset); localizing for display is consumer's job

**Project structure (enforces clean boundaries):**
```
src/availability_engine/
  ├── contracts.py (Resource, Interval, Hold, Booking, Slot, AvailabilityResult — the contract-first surface)
  ├── time.py (localize_operating_hours, require_utc() runtime guard)
  ├── core/ (pure functions, zero I/O, zero tz-awareness, UTC-only Interval objects)
  │   ├── intervals.py (half-open overlap/merge/subtract)
  │   ├── availability.py (sweep-line, capacity-aware fragments)
  │   └── grid.py (fixed-duration slot overlay)
  ├── storage/
  │   ├── protocol.py (StorageBackend Protocol)
  │   ├── memory.py (in-memory reference impl + test double)
  │   └── sql/ (schema, backend, atomic statements)
  └── engine.py (AvailabilityEngine facade)

tests/
  ├── storage/contract_suite.py (ONE parametrized test, run against all backends)
  ├── core/ (interval algebra, grid generation, capacity accounting)
  └── test_time_boundary.py (DST transition fixtures)
```

### From PITFALLS.md

**Top critical pitfalls (shipped bugs in Cal.com, Ticketmaster-style systems):**

1. **Check-then-insert TOCTOU race (Pitfall 1):** Two concurrent bookers both read count < capacity, both insert → overbooking. Fix: single atomic `INSERT...WHERE` statement.

2. **SQLite/Postgres locking divergence (Pitfall 2):** `SELECT ... FOR UPDATE` is a no-op on SQLite (no row-level locking). Fix: `BEGIN IMMEDIATE` on SQLite (coarse write lock) + `FOR UPDATE` on Postgres (row lock), both tested via testcontainers.

3. **Two-step capacity check under READ COMMITTED (Pitfall 3):** Even inside a transaction, phantom reads allow two writers to see the same count before either commits. Fix: explicit row lock (`FOR UPDATE`) or `SERIALIZABLE` isolation + retry handling.

4. **Hold-confirm TTL race (Pitfall 4):** Hold expires while confirm() is in flight; depends on ordering. Fix: single atomic `UPDATE WHERE id=? AND expires_at > db_now()`, using database's own clock, not application time.

5. **Lazy expiry starves availability (Pitfall 5):** If any read path forgets to exclude expired holds, it under-reports availability (no overbooking, but visibility is wrong). Fix: one shared `get_active_entries()` primitive with `expires_at > now` baked in; every path uses it.

6. **Naive/aware datetime mixing (Pitfall 6):** Silent UTC/local confusion or TypeError. Fix: require UTC-aware at every public API boundary (runtime assertions, not just type hints).

7. **DST spring-forward gap (Pitfall 7):** Local time 02:30 doesn't exist on spring-forward days; naive grid generation produces hour-off slots. Fix: construct slots in UTC, convert to local for display; explicitly test documented gap dates.

8. **DST fall-back ambiguity (Pitfall 8):** Local 01:30 occurs twice; naive grid generator produces duplicate or drops an hour. Fix: loop in UTC, not local; surface `fold`/offset in output.

9. **Midnight-crossing hours (Pitfall 9):** Hours like "22:00–02:00" span calendar days; naive per-day model truncates or double-counts. Fix: model as (start_local, duration) or handle crossing in schema; test midnight crossing on DST-transition nights (worst case).

10. **Buffer applied inconsistently (Pitfall 10):** Grid generation adds buffer, overlap checker re-adds it → double-count or drop. Fix: one shared "effective occupied interval" function used everywhere.

11. **Half-open/closed interval inconsistency (Pitfall 11):** One code path treats [start, end], another [start, end) → off-by-one adjacency bugs. Fix: enforce half-open everywhere from day one; one shared overlap utility.

12. **Storage protocol leaks backend concepts (Pitfall 12):** Protocol has SQLAlchemy Row types, session objects, or SQL-specific exceptions → in-memory impl and parallel consumer's stub can't match. Fix: design protocol backend-agnostically first; write in-memory impl first to expose leaks; run identical contract test against both.

13. **Structured output contract drifts (Pitfall 13):** Stub diverges from real output → consumer integration breaks at repin. Fix: versioned, machine-checkable schema; automated conformance test on every change.

14. **Partial-async event-loop stalls (Pitfall 14):** SQLite wrapper looks async but does blocking I/O → serializes all requests silently. Fix: verify actual asyncio interleaving under concurrent load; don't assume "async API" = "doesn't block."

15. **No schema migration story (Pitfall 15):** First breaking change has no safe path to evolve existing databases. Fix: adopt Alembic from first SQL commit, even if first migration is trivial.

16. **Concurrency verified only in-memory (Pitfall 16):** Asyncio's cooperative scheduling hides races; pass against in-memory but fail on real Postgres/SQLite with separate writers. Fix: testcontainers-backed Postgres concurrency test in CI (multiple actual OS-level connections under contention).

17. **Frozen-clock breaks async tests (Pitfall 17):** freezegun/time-machine freezes asyncio's monotonic clock → hold-expiry async tests hang. Fix: use time-machine (faster), or freezegun + `real_asyncio=True`; canary test asyncio safety before CI adoption.

**"Looks done but isn't" validation checklist:**
- [ ] Atomic hold placement: passes single-process tests AND testcontainers Postgres with multiple real concurrent connections
- [ ] DST handling: explicitly tested against documented spring-forward date, fall-back date, and midnight crossing on DST-transition night
- [ ] Lazy expiry: availability *reads* correctly exclude expired holds via one shared primitive, not just writes
- [ ] Storage protocol swappability: same contract test suite runs unmodified against in-memory, SQLite, and Postgres
- [ ] Output contract: automated conformance test comparing real output against consumer's stub
- [ ] Schema migrations: versioned migrations applied and tested against a populated database (not just fresh create)

## Implications for Roadmap

### Suggested Phase Structure (7 phases to v1)

#### Phase 1: Storage Protocol & Domain Model (Foundation)
**Rationale:** Nothing else is buildable without the storage contract frozen and domain types defined. This phase determines whether atomicity is achievable.

**Deliverables:**
- `StorageBackend` Protocol: get_resource, get_active_entries, place_hold, confirm_hold, release_hold, expire_holds (all coarse-grained, atomic)
- Domain value objects (frozen dataclasses): Resource, Interval, Hold, Booking, Slot, AvailabilityResult, error hierarchy
- Contract schema (TypedDict/exported pydantic for parallel consumer stub)
- InMemoryStore reference implementation
- Shared contract test suite (parametrized; start against in-memory)

**Pitfalls prevented:** 12 (protocol design), 6 (UTC enforcement), 11 (half-open intervals)

**Confidence:** HIGH (straightforward contract design)

**No research required.** Proceed from STACK/FEATURES/ARCHITECTURE consensus.

---

#### Phase 2: Core Time + Interval Math + Grid (Timezone Correctness)
**Rationale:** TZ + DST handling is cross-cutting; retrofitting it is a rewrite. Grid generation depends on it.

**Deliverables:**
- `time.py::localize_operating_hours()` (per-resource IANA → UTC per date)
- `time.py::require_utc()` runtime assertion guard
- Half-open Interval type + algebra (overlap, merge, subtract via shared utilities)
- Sweep-line capacity accounting (pure function)
- Fixed-duration slot grid generator
- **DST transition test fixtures** (spring-forward gap, fall-back ambiguity, midnight crossing)

**Pitfalls prevented:** 6, 7, 8, 9, 11

**Confidence:** MEDIUM-HIGH (patterns are established; DST fixture coverage is the key validation)

**Research required:** None. Execution discipline: must test documented gap/fold dates for at least one DST-observing zone.

---

#### Phase 3: Hold/Booking Lifecycle + Atomicity (Correctness Core)
**Rationale:** This is the engine's value proposition. Atomicity contract must be proven against both SQLite and Postgres concurrently.

**Deliverables:**
- `engine.py::place_hold()`, `confirm_hold()`, `release_hold()`
- Atomic conditional write pattern in InMemoryStore
- Hold TTL + lazy expiry (predicate `expires_at > now`)
- **Idempotency keys on place_hold and confirm_hold** (unique constraint on operation + key)
- SQLStore complete implementation:
  - Schema (holds, bookings tables; indexes on `(resource_id, slot_start, status)`)
  - Alembic migrations from day one (first migration = current schema)
  - SQLite: `BEGIN IMMEDIATE` on all writes
  - Postgres: `SELECT ... FOR UPDATE` on resource/slot (optional correctness optimization)
- **Concurrency test: N parallel place_hold calls against capacity-1 resource via testcontainers Postgres → exactly 1 succeeds**
- **Concurrency test: confirm_hold atomicity (hold must be active + unexpired at confirm time)**

**Pitfalls prevented:** 1 (TOCTOU), 2 (SQLite/Postgres divergence), 3 (phantom reads), 4 (TTL race), 14 (partial async), 15 (migrations), 16 (in-memory only)

**Confidence:** MEDIUM (pattern is correct; depends on testcontainers + real concurrent connections for proof)

**Research required:** Verify aiosqlite's actual asyncio safety (Pitfall 14). Confirm Alembic SQLite+Postgres parity.

---

#### Phase 4: Availability Query (Read Path)
**Rationale:** Depends on prior phases. Straightforward orchestration of core algorithms.

**Deliverables:**
- `engine.py::get_availability(resource_id, date_range) -> AvailabilityResult`
- Structured output contract (finalized, frozen for parallel consumer)
- Test: lazy expiry works (expired holds are excluded via shared `get_active_entries` primitive)

**Pitfalls prevented:** 5 (lazy expiry starves), 13 (contract drift)

**Confidence:** HIGH

**No research required.**

---

#### Phase 5: Testing Infrastructure + Scaling
**Rationale:** Before production, prove correctness under real concurrency, time shifts, and scale.

**Deliverables:**
- testcontainers fixture (session-scoped Postgres, per-test rollback)
- time-machine integration + canary asyncio safety test
- DST property-based tests (Hypothesis)
- Load tests (1000+ holds, assert indexes are used)
- Concurrent-client fixture (simulate multiple OS threads/processes)

**Pitfalls prevented:** 16, 17

**Confidence:** MEDIUM (integration heavy; patterns are standard)

**Research required:** Verify time-machine + asyncio interaction explicitly.

---

#### Phase 6: SQL Storage Completion + Scaling Tuning
**Rationale:** All domain logic proven; this phase materializes it for production backends.

**Deliverables:**
- SQLStore fully hardened (both dialects)
- All contract tests pass against InMemoryStore, SQLStore(sqlite), SQLStore(postgres) unmodified
- Lock contention instrumentation (metrics for future tuning)
- Deployment guide (SQLite dev/low-traffic, Postgres high-traffic)

**Confidence:** MEDIUM-HIGH

**No research required.**

---

#### Phase 7: Documentation + Parallel Consumer Repin (v1 Launch)
**Rationale:** Public contract frozen; parallel consumer pins and ships.

**Deliverables:**
- README + API docs (async facade, storage protocol, concurrency model, TZ/DST semantics)
- Migration story (how consumers apply/version migrations)
- Example integration (stub fulfillment + conformance test)
- First git tag + published release

**Confidence:** HIGH

**No research required.**

---

### Research Flags by Phase

| Phase | Research Needed? | Flag |
|-------|-----------------|------|
| 1 (Protocol) | No | Proceed immediately from consensus |
| 2 (Time + Grid) | No | Execution-heavy (DST fixtures); no external research |
| 3 (Atomicity) | **Yes** | Verify aiosqlite asyncio safety; confirm Alembic SQLite parity |
| 4 (Availability) | No | Straightforward orchestration |
| 5 (Testing) | **Yes** | Verify time-machine + asyncio behavior as canary |
| 6 (SQL completion) | No | Standard implementation |
| 7 (Launch) | No | Documentation + coordination |

### Standard Patterns (No Deeper Research Needed)

- Half-open interval algebra for calendar systems (established practice)
- Sweep-line event-counting for resource-capacity scheduling (textbook algorithm)
- Coarse-grained protocol for backend-agnostic atomicity (standard architecture pattern)
- Lazy-on-read predicate-based expiry (common in distributed systems)
- SQLAlchemy Core for dialect-portable SQL composition (well-documented)

## Confidence Assessment

| Area | Level | Notes |
|------|-------|-------|
| **Stack / Technology** | MEDIUM | Python 3.12, SQLAlchemy 2.0, stdlib datetime confirmed stable. Versions from PyPI as of 2026-09-02; re-verify pyproject.toml pinning at implementation. aiosqlite asyncio safety flagged for Phase 3 research. |
| **Features / Requirements** | MEDIUM | Table stakes locked in PROJECT.md. Idempotency keys flagged as likely implementation gap. Anti-features scope (recurrence, arbitrary bookings) well-defined. |
| **Architecture / Patterns** | **HIGH** | Portable atomicity (`INSERT...SELECT` + rowcount check) is established. Sweep-line capacity accounting is textbook. Coarse-grained protocol design is sound. SQLite/Postgres dialect divergence solution (`BEGIN IMMEDIATE` + `FOR UPDATE`) confirmed via research. |
| **Time / Timezone** | MEDIUM-HIGH | Per-date conversion strategy is sound. **DST transition testing is the critical unknown** — must explicitly fixture-test spring-forward gap, fall-back ambiguity, midnight crossing. zoneinfo is stdlib stable. |
| **Atomicity / Concurrency** | MEDIUM | Pattern is correct; **confidence depends entirely on Phase 3 executing real-Postgres testcontainers concurrency tests**. In-memory tests alone are insufficient (Pitfall 16). |
| **Storage Protocol** | MEDIUM | Backend-agnostic design is solid. Risk: leakage of SQL concepts into Protocol (Pitfall 12). Mitigation: write in-memory impl first; run identical contract suite against both. |
| **Risk Mitigation** | MEDIUM | All 17 pitfalls have clear prevention strategies. "Looks done but isn't" checklist is the v1 gate. Execution discipline is the limiting factor. |

### Gaps Requiring Attention

1. **aiosqlite asyncio safety (Phase 3 research):** Must verify under concurrent load that aiosqlite doesn't serialize writes.
2. **Alembic SQLite+Postgres parity (Phase 3 research):** Confirm migrations don't diverge between dialects.
3. **DST edge case coverage (Phase 2):** Test suite must include documented gap/fold dates; not optional.
4. **Idempotency key uniqueness (Phase 3):** Storage schema must have unique constraint or application-layer check.
5. **Parallel consumer stub conformance (Phase 4):** Establish automated conformance test before v1; not a post-launch check.

## Sources

**Research conducted:** 2026-09-02

**Research files synthesized:**
- [STACK.md](./STACK.md) — Technology recommendations (MEDIUM confidence on versions; established patterns HIGH)
- [FEATURES.md](./FEATURES.md) — Feature landscape, MVP definition, comparable systems (MEDIUM confidence)
- [ARCHITECTURE.md](./ARCHITECTURE.md) — System design, patterns, concurrency model (HIGH confidence for established patterns)
- [PITFALLS.md](./PITFALLS.md) — 17 critical pitfalls + prevention strategies (MEDIUM confidence; grounded in distributed-systems theory + published incident reports)
- [PROJECT.md](./PROJECT.md) — Core requirements + scope (HIGH confidence; author-authored)

**Key external sources cited in research:**
- Cal.com TOCTOU issue (GitHub #29605) — check-then-insert race in production
- SQLite concurrency docs (sqlite.org, AWS blog) — WAL mode limitations, BEGIN IMMEDIATE behavior
- SQLAlchemy dialect docs — SELECT FOR UPDATE behavior across backends
- PostgreSQL transaction isolation docs — READ COMMITTED phantom reads, SERIALIZABLE
- testcontainers-python guide — ephemeral Postgres fixture pattern
- time-machine vs freezegun benchmark — performance + asyncio interaction
- zoneinfo / PEP 495 — local-time ambiguity (fold) in DST transitions

---

**This research synthesis is complete and ready for roadmap planning.**
