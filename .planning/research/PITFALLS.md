# Pitfalls Research

**Domain:** Domain-agnostic async Python scheduling/availability engine (resources × time-slots × atomic holds, pluggable storage: in-memory + SQL spanning SQLite/Postgres)
**Researched:** 2026-09-02
**Confidence:** MEDIUM (cross-checked web sources + established distributed-systems/interval-math theory; no vendor-authoritative docs required for these general patterns)

## Critical Pitfalls

### Pitfall 1: Check-then-insert (TOCTOU) capacity race

**What goes wrong:**
Availability is computed by reading current holds/bookings, checking `count < capacity`, then inserting a new hold as a separate step. Two concurrent bookers both read `count = capacity - 1`, both pass the check, both insert — capacity is now over-booked by N.

**Why it happens:**
It's the natural way to write the logic in application code ("check availability, then act"), and it works perfectly in every manual test because a human can't create the race window. This is exactly the bug Cal.com shipped in production: booking-limit enforcement was a non-transactional read followed by a separate insert, so two concurrent requests both read the same under-limit count and both persisted.

**How to avoid:**
The check and the write must be the *same* atomic operation from the database's point of view — never two round-trips. Concretely: a single `INSERT ... WHERE (SELECT COUNT(*) ... ) < capacity` guarded by a row lock on the resource/slot row, or a conditional `UPDATE` that decrements a `remaining_capacity` counter with `WHERE remaining_capacity > 0` and checks rows-affected. The storage protocol's `place_hold()` contract must specify "atomic conditional write," not "read then write," and every backend implementation must be tested against that exact contract, not just its own internals.

**Warning signs:**
Any code path where `has_capacity()` (or equivalent) is called, its boolean result is returned to a caller, and a *separate* call later performs the insert. If the atomicity boundary is anywhere above the storage layer, it's broken.

**Phase to address:**
Hold/booking lifecycle phase (place_hold, confirm) — this is the core value proposition of the whole library and should be the first thing verified with a real concurrency test, not the last.

---

### Pitfall 2: SQLite vs Postgres locking-semantics divergence in "one SQL impl spanning both"

**What goes wrong:**
Code written and tested against SQLite "works," then silently overbooks under load on Postgres (or vice versa) because the two engines have fundamentally different concurrency models that a single code path can't paper over with generic SQLAlchemy calls.

**Why it happens:**
SQLite allows exactly one writer at a time for the whole database file — even in WAL mode, "readers don't block writers and writers don't block readers," but writers still fully serialize against each other. Postgres allows many concurrent writers with row-level locking. A `SELECT ... FOR UPDATE` pattern that's essential for correctness on Postgres is a no-op-equivalent on SQLite (the single-writer lock already serializes everything) — but the reverse mistake is worse: relying on SQLite's coarse single-writer lock for "free" atomicity, then deploying the same code to Postgres where that lock doesn't exist and the missing row lock lets concurrent transactions interleave.

**How to avoid:**
Design the atomicity contract in terms of the *most restrictive* backend (Postgres row locks), and require the SQLite implementation to explicitly opt into equivalent semantics rather than relying on incidental behavior. Concretely:
- Always open write transactions with `BEGIN IMMEDIATE` on SQLite (a plain `BEGIN` starts as a read transaction that can fail with `SQLITE_BUSY` when it tries to upgrade to a writer while another writer holds the lock — this is the #1 cause of "works until concurrent" SQLite bugs).
- Use `SELECT ... FOR UPDATE` (not `FOR UPDATE SKIP LOCKED`) on the resource/slot row on Postgres for the capacity check-and-write, since `SKIP LOCKED` would let a concurrent request *skip* the contended row and read stale capacity instead of waiting for the correct answer — `SKIP LOCKED` is for queue-pop patterns, not capacity-limited writes.
- Set an explicit `busy_timeout` on SQLite connections and have the storage layer translate `SQLITE_BUSY`/serialization failures from both backends into one shared "contention, retry" exception so the engine's public API doesn't leak backend-specific errors.

**Warning signs:**
Any backend-specific SQL string, pragma, or isolation-level setting that exists in only one of the two code paths without an equivalent in the other. A test suite that passes entirely against the in-memory or SQLite backend but has no concurrent-writer test against real Postgres.

**Phase to address:**
SQL storage implementation phase — write the concurrency contract test once (N concurrent holds against capacity-1 resource → exactly 1 succeeds) and run it against SQLite *and* Postgres (via testcontainers) as a shared parametrized test, not two separate suites.

---

### Pitfall 3: Capacity counting via two-step read-modify instead of one atomic statement

**What goes wrong:**
Even within a single backend, `remaining = capacity - count_active_holds(); if remaining > 0: insert_hold()` is still a TOCTOU race even inside a transaction, if the isolation level doesn't prevent phantom reads (default `READ COMMITTED` on Postgres does not).

**Why it happens:**
"Wrap it in a transaction" is a common but incomplete fix — a transaction gives atomicity of the *whole* transaction's effects, but under `READ COMMITTED` two concurrent transactions can each see the same "before" count and both commit, because neither one's write conflicts with a value the other transaction *read* (only with values it *wrote*).

**How to avoid:**
Either (a) take an explicit row lock (`SELECT ... FOR UPDATE`) on the resource's capacity-tracking row *before* the count check, forcing the second transaction to block until the first commits its capacity change, or (b) use `SERIALIZABLE` isolation and handle serialization-failure retries at the storage layer. Row-locking is simpler to reason about and matches the "row-lock atomicity" decision already made for this project; `SERIALIZABLE` is more elegant but pushes retry-loop complexity into every caller unless the storage layer hides it.

**Warning signs:**
Any capacity check implemented as a `COUNT(*)` query followed by an `INSERT`/`UPDATE` in a *different* statement, even inside a transaction, without an explicit lock in between.

**Phase to address:**
SQL storage implementation phase, same as Pitfall 2 — these two should be designed and tested together since they're the same underlying atomicity contract.

---

### Pitfall 4: Hold-confirm race at the TTL boundary

**What goes wrong:**
A hold is about to expire. At nearly the same instant, (a) a lazy-expiry check reclaims it because it's past its TTL, and (b) the original holder calls `confirm()`. Depending on ordering, either a hold that should have expired gets confirmed into a booking, or a legitimate last-moment confirm is rejected even though the holder was first.

**Why it happens:**
"Is this hold still valid?" and "convert this hold into a booking" are naturally written as two operations (check TTL, then write), which reintroduces the same TOCTOU shape as Pitfall 1, but now racing against time itself instead of another writer.

**How to avoid:**
`confirm(hold_id)` must be a single atomic conditional write: `UPDATE holds SET status='confirmed' WHERE id=? AND status='active' AND expires_at > <db-computed now>`, checking rows-affected to decide success. Compute "now" inside the database (`NOW()` / `CURRENT_TIMESTAMP`) rather than passing in an application-computed timestamp, to avoid clock-skew between the app process and the DB server making the comparison wrong in either direction.

**Warning signs:**
A `confirm()` implementation that does `hold = get_hold(id); if not hold.is_expired(): write_booking()` as separate steps, or that compares `datetime.now()` from the application against a stored `expires_at` rather than letting the database do the comparison atomically with the write.

**Phase to address:**
Hold/booking lifecycle phase.

---

### Pitfall 5: Lazy expiry starves availability instead of causing overbooking

**What goes wrong:**
Because there's no background sweeper (by design), an expired-but-unreclaimed hold still occupies a capacity slot until the *next read or write* touches it. If reads are rare for a resource, a stream of abandoned holds can make a resource look fully booked for far longer than the TTL implies, even though no double-booking occurs (correctness is preserved, but availability accuracy degrades).

**Why it happens:**
Lazy-on-read is the right architectural call (no runtime lifecycle to own), but it shifts the burden of reclamation onto every read/write path — if even one query path (e.g. `get_availability()`) forgets to filter/reclaim expired holds before counting capacity, that path silently under-reports availability. This is the opposite failure mode of Pitfall 1 (false "unavailable" instead of false "available"), and it's easy to miss because it never causes a customer-visible double-booking — it just quietly loses bookings.

**How to avoid:**
Define one shared, storage-layer primitive — e.g. `active_holds_and_bookings(resource, window)` — that *always* excludes/reclaims expired holds as part of its query (a single `WHERE expires_at > now() OR status != 'active'` clause, or an actual reclaim-on-read `UPDATE ... RETURNING` that flips expired holds to `released` before counting). Every availability computation and every capacity check must route through this one primitive — never write a second, ad hoc "count active holds" query elsewhere in the codebase.

**Warning signs:**
More than one code path that queries "how many holds/bookings are active for this slot" independently. Availability numbers that are consistently a little lower than expected under load, without any double-booking ever being observed.

**Phase to address:**
Hold/booking lifecycle phase (define the shared reclaim-on-read primitive) — flag for reuse by the availability-computation phase too, since both must share it.

---

### Pitfall 6: Naive vs aware datetime mixing

**What goes wrong:**
A naive `datetime` (no tzinfo) gets compared, stored, or arithmetic'd against an aware one somewhere in the codebase — either raising `TypeError` at runtime in the best case, or silently producing wrong results if the naive value happens to be interpreted as UTC by one function and as local time by another.

**Why it happens:**
Python's stdlib does not stop you from constructing naive datetimes, and it's easy for one code path (e.g. a quick script, a test fixture, a third-party library's return value) to hand back a naive value that flows into engine logic expecting aware UTC. Because this only fails when the naive/aware boundary is actually crossed, it can pass unit tests for months.

**How to avoid:**
Enforce "TZ-aware only" at the boundary of the public API with runtime assertions (raise `ValueError` immediately if any datetime parameter lacks `tzinfo`), not just type hints (which are not enforced at runtime). Internally store and compute exclusively in UTC; convert to the resource's IANA zone only at the edges (grid generation from operating hours, and structured-output rendering). Never accept or emit fixed UTC offsets (`+05:00`) as a *substitute* for an IANA zone name when DST-observing correctness matters — an offset has no DST rule.

**Warning signs:**
Any function signature accepting `datetime` without an explicit contract (docstring + runtime check) about awareness. Any `datetime.now()` or `datetime.utcnow()` call in engine code (the former is naive-local, the latter is naive-UTC and deprecated) instead of `datetime.now(UTC)`.

**Phase to address:**
Core domain model phase — establish this as a lint-enforced or runtime-enforced invariant before any slot/hold logic is written on top of it, since retrofitting it later means auditing every datetime touchpoint.

---

### Pitfall 7: DST spring-forward gap in operating-hours grid generation

**What goes wrong:**
A resource's operating hours are defined as local wall-clock time (e.g. "09:00–17:00 America/New_York"). On the day clocks spring forward, the local time between 02:00 and 03:00 doesn't exist. If the grid generator naively constructs `datetime(2027, 3, 14, 2, 30, tzinfo=zone)` for a resource whose hours happen to span that gap, `zoneinfo` doesn't raise — it silently normalizes the non-existent time to a real UTC instant (typically treating it as if DST hadn't started yet), producing a slot that is off by exactly one hour from what the resource's calendar actually shows.

**Why it happens:**
This case is rare (2 days a year, only for zones/hours where the gap falls inside operating hours) and rarely appears in local testing unless the test author specifically constructs a fixture on a DST-transition day, so it survives to production undetected.

**How to avoid:**
When constructing local wall-clock times from operating-hours + slot-grid arithmetic, explicitly check whether the resulting local time is non-existent (`datetime.astimezone` round-trip mismatch, or use a library helper that surfaces `fold`/gap detection) and either skip generating that slot (grid has a real, documented gap that day) or shift it forward past the DST jump — but *choose one behavior deliberately and document it*, rather than let `zoneinfo` pick silently. Add DST-transition-day fixtures (per hemisphere, since transition dates differ) to the grid-generation test suite as a required case, not an edge case.

**Warning signs:**
No test in the suite constructs a grid for a resource whose operating hours span a documented spring-forward date for its zone. Grid generation code that builds local datetimes via naive arithmetic (`start + timedelta(minutes=30)` in local time) rather than doing arithmetic in UTC and converting to local only for display/operating-hours-window comparison.

**Phase to address:**
Core domain model / grid-generation phase, in the same pass as per-resource IANA zone support (this is not separable from that requirement — it's the exact correctness case that requirement exists to solve).

---

### Pitfall 8: DST fall-back ambiguity duplicates or drops a slot

**What goes wrong:**
On the day clocks fall back, one local hour (e.g. 01:00–02:00 in the US) occurs twice. A grid generator walking wall-clock time slot-by-slot can either (a) generate two slots that both render as "01:30" with no way for a consumer to distinguish them, or (b) generate only one and silently skip an hour of real, bookable time, depending on how the loop is written.

**Why it happens:**
Symmetric to Pitfall 7, but on the ambiguous side rather than the gap side — and it's just as easy to omit from test fixtures.

**How to avoid:**
Do slot-grid arithmetic by advancing a UTC instant by a fixed duration (`timedelta`), not by advancing a local wall-clock string — this makes each generated slot's *identity* the UTC instant, so the fall-back hour naturally produces two distinct, correctly-ordered slots (one at `fold=0`, one at `fold=1`) rather than a duplicate or a gap. When rendering local time back to a consumer for a slot that falls in the ambiguous hour, surface which occurrence it is (e.g. include the UTC offset alongside local time in the structured output) so the consumer isn't given two visually identical labels for different bookable windows.

**Warning signs:**
Grid-generation logic that loops by repeatedly calling `local_dt + timedelta(...)` and reformatting, rather than looping in UTC and converting once per slot. Structured output that renders only `HH:MM` local time with no offset/UTC disambiguator for zones that observe DST.

**Phase to address:**
Core domain model / grid-generation phase (same as Pitfall 7) and structured-output-contract phase (for the rendering side).

---

### Pitfall 9: Midnight-crossing operating hours mishandled

**What goes wrong:**
A resource with hours like "22:00–02:00" (crosses midnight) either gets rejected by validation that assumes `close > open` within one calendar day, or gets silently truncated to "22:00–23:59" losing the after-midnight portion, or gets double-counted against the *next* day's operating-hours record if the model naively treats each day's hours independently.

**Why it happens:**
Per-day operating-hours models (this project's stated design) are naturally keyed by calendar day, and the "day" the shift starts on isn't the "day" it ends on — a very common gap in first-pass calendar models, and one that combines badly with DST if the crossing happens on a transition night.

**How to avoid:**
Model an operating-hours entry as `(start_instant_offset, duration)` or `(start_local_time, end_local_time, spans_midnight: bool)` rather than assuming `close > open`, and generate that day's grid entirely from the start day's anchor, extending past midnight in UTC terms as needed. Explicitly test a resource whose hours cross midnight *and* whose crossing night is a DST transition night, since that's the true worst case for this project's domain (per-resource IANA zones + midnight-crossing hours + fixed grid, all three requirements interacting at once).

**Warning signs:**
Any validation that rejects or reinterprets an operating-hours record where the end time is numerically less than the start time. Grid generation keyed strictly per calendar day with no carry-over state.

**Phase to address:**
Core domain model phase, when the operating-hours schema is first defined — this is a schema-shape decision, expensive to change once storage and grid-generation code depend on "same-day" semantics.

---

### Pitfall 10: Buffer/reset time applied inconsistently at adjacency

**What goes wrong:**
Two back-to-back bookings on the same resource each need a buffer/reset window afterward. If both the "end of booking A" and "start of booking B" logic independently add half a buffer, or if the buffer is applied when generating the grid *and again* when checking for overlaps against existing bookings, adjacent slots either overlap (buffer double-counted as unavailable) or touch with zero buffer (buffer silently dropped) depending on which code path ran last.

**Why it happens:**
Buffer time is conceptually "attached" to both the preceding and following slot depending on how you think about it (cleanup after A, or setup before B), and if the grid generator bakes buffer into slot spacing while the overlap-checker *also* re-applies it when checking a candidate hold against existing bookings, the two independently-reasonable implementations conflict.

**How to avoid:**
Decide once, in the domain model, that buffer is owned by exactly one side (recommended: the *preceding* booking's effective occupied window includes its trailing buffer, so a slot's "occupied" interval is `[start, end + buffer)` in half-open terms) and never let overlap-detection re-derive or re-add buffer independently — overlap detection should just compare the already-buffer-inclusive intervals with plain half-open overlap math (Pitfall 11). Bake this into one shared "effective occupied interval" function used by both grid generation and hold/overlap checks.

**Warning signs:**
Buffer duration referenced in more than one place in the codebase (grid generator *and* overlap checker *and* hold placement) with separate arithmetic in each, rather than one shared function computing the effective occupied interval.

**Phase to address:**
Core domain model / interval-math phase — same phase as half-open interval design (Pitfall 11), since buffer handling is a direct extension of that same interval representation.

---

### Pitfall 11: Half-open vs closed interval inconsistency causing off-by-one adjacency bugs

**What goes wrong:**
Grid generation, overlap detection, and operating-hours-boundary checks each independently decide whether the end timestamp of an interval is inclusive or exclusive. If even one of the three treats intervals as closed (`[start, end]`) while the others treat them as half-open (`[start, end)`), back-to-back adjacent slots either falsely overlap (a slot ending at 10:00 and one starting at 10:00 get flagged as conflicting) or a slot exactly at the operating-hours boundary gets incorrectly included or excluded.

**Why it happens:**
Half-open representation is the standard, correct choice for calendar/interval systems specifically *because* it makes adjacency and overlap math trivial (`overlap iff max(s1,s2) < min(e1,e2)`; adjacent `[10,20)` and `[20,30)` never overlap), but it has to be applied *consistently everywhere* — a single closed-interval comparison anywhere in the codebase reintroduces exactly the off-by-one bugs half-open intervals exist to eliminate.

**How to avoid:**
Adopt half-open `[start, end)` as a documented, project-wide invariant for every interval type (slot, hold, booking, operating-hours window) from the very first line of domain-model code. Write the overlap-detection function once as a single shared utility (`intervals_overlap(a, b) -> max(a.start, b.start) < min(a.end, b.end)`) and require every overlap check in the codebase to call it — never let a second overlap check get hand-rolled with `<=`.

**Warning signs:**
Any interval comparison using `<=` or `>=` at a boundary instead of strict `<`/`>`. More than one hand-written overlap-check implementation in the codebase.

**Phase to address:**
Core domain model / interval-math phase — this is foundational and should be locked down (with property-based tests, see Testing section) before grid generation or hold placement is built on top of it.

---

### Pitfall 12: Storage protocol leaks backend-specific concepts, breaking swappability and the parallel consumer's stub

**What goes wrong:**
The `Protocol` defining pluggable storage ends up with a method signature, return type, or exception type that only makes sense for one backend — e.g. returning a SQLAlchemy `Row`/ORM model, taking a DB session/connection object as a parameter, or leaking `sqlite3.IntegrityError` up through the public API. The in-memory implementation then has to fake those types just to satisfy the interface, and worse, the *stub* that the parallel first-consumer (the chatbot) is coding against either can't be written faithfully, or diverges from what the real engine eventually returns — breaking the contract-first promise this project is explicitly built around.

**Why it happens:**
It's fastest to write the SQL implementation first (since row-lock atomicity is the hard part) and derive the Protocol from what that implementation naturally wants to expose, rather than designing the Protocol backend-agnostically first and making both implementations conform to it.

**How to avoid:**
Design and freeze the storage `Protocol` (and the domain-level exception hierarchy it raises — e.g. `CapacityExhausted`, `HoldNotFound`, `ContentionError` — never a raw DB driver exception) *before* writing the SQL implementation, using only plain dataclasses/domain types in every signature. Write the in-memory implementation first or in lockstep specifically because its simplicity will immediately expose any accidental SQL-shaped leakage in the Protocol. Run the *exact same* contract test suite against both the in-memory and SQL implementations — if a test needs backend-specific setup to pass, the Protocol has a leak.

**Warning signs:**
Any type in a `Protocol` method signature or raised exception that isn't a project-owned domain type or a Python builtin. The in-memory implementation needing to import a SQL driver, or needing awkward workarounds to conform to a signature clearly shaped for SQL.

**Phase to address:**
Storage protocol definition phase — this must precede (or be co-designed with) both implementations, and its shared contract-test suite is what phase-gates "is the protocol actually backend-agnostic."

---

### Pitfall 13: Structured output contract drifts silently, breaking the parallel consumer

**What goes wrong:**
The chatbot consumer is coding against a stubbed version of the structured `available`/`booked` output contract while this engine is built in parallel. If the real engine's eventual output shape (field names, nesting, timezone representation, enum values) diverges from the stub — even in small ways like renaming a field or changing a timestamp format from ISO string to epoch — the consumer's integration breaks at repin time, discovered late and expensively.

**Why it happens:**
The stub is written once, early, based on a sketch of the contract; the real implementation evolves as edge cases (DST, buffers, capacity>1) are discovered, and it's natural for the output shape to accrete new fields or change representations to accommodate them without anyone re-syncing the stub.

**How to avoid:**
Treat the structured output contract as a versioned, testable artifact from day one: define it once (e.g. as a `TypedDict`/`dataclass`/JSON-schema) in a location both the stub and the real implementation can import or validate against, and add a schema-conformance test that runs against real engine output on every change. Any field addition should be additive and optional-tolerant on the consumer side; any breaking change (rename, type change, removed field) should bump an explicit contract version the consumer can pin against, rather than silently changing shape under the same version.

**Warning signs:**
The stub and the real implementation living in genuinely separate files/repos with no shared schema artifact or conformance test connecting them. A "let's just update the stub later" plan with no automated check that it happened.

**Phase to address:**
Structured output contract phase — should ship a machine-checkable schema (not just documentation prose) before the parallel consumer starts coding against it, and that schema should be the thing both sides pin to.

---

### Pitfall 14: Partial-async ergonomics stall the event loop

**What goes wrong:**
The storage protocol is async and the public API "follows suit where it touches storage," but a specific backend implementation (most likely the SQLite path, since many SQLite drivers are sync-only under the hood) does blocking I/O inside an `async def` method without offloading it to a thread executor. Under real concurrent load, this blocks the entire event loop, silently serializing all requests (defeating the purpose of async) or causing timeouts elsewhere in the consumer's process.

**Why it happens:**
`aiosqlite` and similar wrappers make the *call site* look async, but if the underlying driver work happens synchronously in a way that isn't properly delegated to a thread pool, or if a well-intentioned "quick synchronous helper" gets called from inside an async method during development, the blocking is invisible in tests that never exercise real concurrency (Pitfall 15).

**How to avoid:**
Pick one async SQLite driver deliberately (e.g. one that's confirmed to offload to a thread executor internally) and audit it, rather than assuming "has an async API" means "doesn't block." Add a load-bearing test early that runs many concurrent `async` calls against the SQLite backend and asserts they interleave (e.g. via timing or explicit yield-point instrumentation) rather than fully serializing — this is a different property than the correctness test in Pitfall 2, and both are needed.

**Warning signs:**
Any `async def` method in the SQL implementation with no `await` on the line that actually performs I/O, or a call to a known-synchronous library function without `run_in_executor`/`asyncio.to_thread`.

**Phase to address:**
SQL storage implementation phase.

---

### Pitfall 15: No schema-migration story until the first breaking change is urgent

**What goes wrong:**
The SQL implementation ships with a hand-rolled `CREATE TABLE` (or ORM `create_all()`) and no migration tool. The first time a column needs to change (e.g. adding the capacity-counter column from Pitfall 3, or a contract version marker), there's no safe, tested path to evolve an existing SQLite/Postgres database without a manual, error-prone one-off script — and because this is a *library*, the maintainer doesn't even control when/how consumers apply the migration.

**Why it happens:**
Migrations feel unnecessary for a "v1" library with no production data yet, so the tooling investment gets deferred — but retrofitting a migration tool onto an already-shipped schema (with real consumer databases already created from it) is much more expensive than starting with one.

**How to avoid:**
Adopt a migration tool (e.g. Alembic, which supports both SQLite and Postgres from one codebase) from the first SQL schema commit, even if the first migration is trivial. Document the migration-application story for consumers explicitly (does the library apply migrations itself on startup, or does it hand the consumer a migration script to run?) as part of the storage-protocol contract, not as an afterthought.

**Warning signs:**
A `CREATE TABLE IF NOT EXISTS` or ORM `metadata.create_all()` call as the only schema-provisioning mechanism, with no versioned migration files anywhere in the repo.

**Phase to address:**
SQL storage implementation phase — set up the migration tool alongside the first schema, not after.

---

### Pitfall 16: Concurrency correctness "verified" only against the in-memory backend

**What goes wrong:**
The in-memory storage implementation runs inside a single Python process's asyncio event loop, where "concurrent" async tasks are cooperatively scheduled and never truly run in parallel unless a task explicitly yields at exactly the wrong moment. A concurrency test suite that only exercises the in-memory backend can pass 100% of the time while the same logical race, run against real concurrent connections to SQLite or Postgres, overbooks every time.

**Why it happens:**
The in-memory backend is fast and dependency-free, so it's the natural default for the whole test suite, and asyncio's cooperative scheduling means naive in-memory "race" tests often don't actually race unless an explicit `await asyncio.sleep(0)` or similar yield point is inserted at the exact right spot to simulate interleaving.

**How to avoid:**
Maintain two distinct tiers of concurrency test: (1) an in-memory-backend test that deliberately injects yield points (or an explicit lock-free/naive reference implementation) to prove the *contract* is race-safe in principle, and (2) a real-database test using testcontainers (ephemeral Postgres in Docker, and a real SQLite file with multiple actual OS threads/processes) that fires genuinely concurrent hold requests at a capacity-1 resource and asserts exactly one succeeds. Only tier (2) is real evidence for the SQL backend; tier (1) is a design-time sanity check, not a substitute.

**Warning signs:**
Every concurrency test in the suite uses the in-memory backend. No test suite dependency on testcontainers, docker, or a real Postgres/SQLite fixture. "It passed 1000 iterations" claims made without confirming genuine OS-level concurrent execution (multiple threads, processes, or real separate DB connections under contention) occurred.

**Phase to address:**
Testing infrastructure — should be established at the same time as (or immediately after) the SQL storage implementation phase, since that's the phase whose correctness this test tier actually verifies.

---

### Pitfall 17: Frozen-clock test tooling silently breaks async hold-expiry tests

**What goes wrong:**
A test uses a time-freezing library to simulate a hold's TTL expiring, but the freeze also stops `asyncio`'s internal monotonic clock, causing `asyncio.sleep()` calls (used by the test itself, or by connection-pool/retry logic in the storage driver) to hang indefinitely — the test suite stalls rather than failing cleanly, which is confusing to diagnose and can lead to disabling/skipping the test rather than fixing it.

**Why it happens:**
`freezegun` in particular is a documented source of asyncio hangs because it freezes `time.monotonic()` along with wall-clock time by default; `time-machine` is a faster C-level alternative with similar caveats if not configured correctly.

**How to avoid:**
If using `freezegun`, always pass `real_asyncio=True` for any test that touches async code paths, so the event loop keeps seeing real monotonic time while wall-clock/`datetime.now()` stays frozen. Prefer `time-machine` for this project given it's an async-native library, and verify its interaction with the event loop explicitly in a canary test before relying on it project-wide. Never let hold-expiry tests rely on real `asyncio.sleep(ttl_seconds)` wall-clock waits either (slow, flaky) — the TTL comparison should be structured so tests can inject/advance a clock abstraction cleanly.

**Warning signs:**
A test suite where time-dependent tests are occasionally reported as "hanging" or need a manual timeout/kill in CI. Any use of a time-freezing library without an explicit note about its asyncio interaction.

**Phase to address:**
Testing infrastructure phase, in lockstep with the hold/booking lifecycle phase (the first place TTL-dependent tests will be written).

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|-----------------|------------------|
| Skip real-Postgres/testcontainers tests, rely on SQLite + in-memory only | Faster CI, no Docker dependency | Concurrency bugs on Postgres (Pitfall 2, 16) ship undetected since Postgres has the weaker single-writer safety net that SQLite accidentally provides | Never, once the SQL backend claims Postgres support — acceptable only during the earliest scaffolding before row-lock logic exists at all |
| Use `SERIALIZABLE` isolation everywhere instead of explicit row locks | Simpler mental model, DB catches all anomalies | Every capacity-check call site needs retry-on-serialization-failure logic, or silent transaction failures | Acceptable if retry logic is centralized in the storage layer itself, never left to callers |
| Represent operating hours/slots as naive local-time strings internally, convert to UTC only at storage boundary | Feels more "human readable" during early development | Reintroduces every naive/aware and DST bug this research flags; very expensive to retrofit once grid-generation and hold logic assume it | Never |
| Defer schema migrations ("we'll add Alembic later") | Faster first SQL implementation | Expensive, risky retrofit once real consumer databases exist from the un-migrated schema | Only acceptable pre-first-tag, before any consumer has a real database created from the schema |
| Hand-roll the overlap/interval-adjacency check per call site instead of one shared utility | Feels quicker for a "simple" one-off check | Off-by-one inconsistency (Pitfall 11) the moment a second call site diverges | Never |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|-----------------|-------------------|
| SQLite (via aiosqlite or similar) | Assuming `busy_timeout` alone prevents `SQLITE_BUSY` under concurrent writers | Combine `busy_timeout` with `BEGIN IMMEDIATE` for every write transaction |
| Postgres (via asyncpg/SQLAlchemy async) | Using `FOR UPDATE SKIP LOCKED` for capacity checks (borrowed from queue-worker patterns) | Use plain `FOR UPDATE` (blocking) on the capacity-tracking row for correctness; reserve `SKIP LOCKED` for genuine queue/job-claiming use cases only |
| `zoneinfo` / IANA tz database | Treating a fixed UTC offset (`+05:00`) as equivalent to an IANA zone name for a resource's operating hours | Always store and require an IANA zone name (e.g. `America/Chicago`) per resource; an offset has no DST rule and silently breaks half the year |
| testcontainers-python (Postgres) | Standing up a fresh container per test (slow, flaky in CI) instead of a session-scoped container with per-test transaction rollback | Use one session-scoped Postgres container, wrap each test in a transaction that's rolled back afterward, for both speed and isolation |
| freezegun / time-machine | Freezing time in a test that also exercises async connection pools or retry backoff, without asyncio-safe configuration | Use `real_asyncio=True` (freezegun) or verify `time-machine`'s event-loop interaction explicitly before relying on it |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|-----------------|
| Row-level lock held for the full duration of an availability computation, not just the capacity write | Lock contention/latency spikes under moderate concurrent load even though actual writes are cheap | Compute/validate availability read-only outside the lock; take the row lock only immediately before the atomic write | Noticeable once more than a handful of concurrent bookers target the same popular resource/slot |
| Full-table or full-resource scan to compute availability over a date range (no index on `(resource_id, start_time)`) | Availability queries slow down linearly with total historical booking volume, not with the queried range | Index storage tables on `(resource_id, start_time, end_time)`; ensure the SQL backend's schema ships this index from its first migration | Becomes visible once a resource accumulates months of booking history |
| SQLite single-writer serialization becomes the bottleneck under real concurrent load | All writes queue up behind each other even though logically independent (different resources) | Treat SQLite as the local-dev/low-concurrency backend it's decided to be; document that high-concurrency production deployments should use the Postgres path | Breaks down once concurrent-writer throughput needs exceed what one serialized writer can sustain — expected and acceptable for SQLite's stated role, but must be documented so consumers don't deploy it to a high-traffic production case by mistake |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Accepting a caller-supplied "now" timestamp for TTL/expiry comparisons instead of computing it server-side | A malicious or buggy consumer could pass a skewed timestamp to force premature or delayed hold expiry, manipulating capacity | Always compute expiry comparisons using the storage backend's own clock (DB `NOW()`, or the engine process's monotonic clock for in-memory), never a caller-supplied value |
| Letting the opaque consumer payload attached to a hold/booking flow into log lines, error messages, or exception text un-redacted | Library-level logs could leak consumer-domain PII the engine was explicitly designed never to know about | Treat the payload as fully opaque even in logging/error paths — log its presence/size/type only, never its contents |
| Raising raw backend driver exceptions (e.g. containing SQL fragments or connection strings) through the public API | Leaks infrastructure details to consumer code/logs that shouldn't need or want them | Wrap all backend exceptions in the domain exception hierarchy (Pitfall 12) before they cross the public API boundary |

## UX Pitfalls

This is a backend library with no end-user UI; "UX" here means the developer experience of the consumer integrating against this engine's API and structured contract.

| Pitfall | Consumer Impact | Better Approach |
|---------|------------------|-------------------|
| Structured output renders local times without timezone/offset context | Consumer displays a slot time that's ambiguous or wrong-looking to end users, especially near DST transitions (Pitfall 8) | Include both the UTC instant and the resolved local time + offset in every structured slot/booking output |
| Capacity-exhausted and hold-expired failures surfaced as the same generic exception | Consumer can't distinguish "try a different slot" from "your hold timed out, restart the flow" and builds a worse end-user experience or retries incorrectly | Distinct, documented exception types per failure mode (`CapacityExhausted`, `HoldExpired`, `HoldNotFound`, `ContentionError`) as part of the frozen public contract |
| Async API requires the consumer to know backend-specific setup (e.g. connection pool sizing, event-loop policy) to avoid Pitfall 14's stalls | Consumer inherits performance bugs they can't diagnose without deep knowledge of this library's internals | Document required async setup explicitly per backend in the storage-protocol docs, and provide sane, tested defaults |

## "Looks Done But Isn't" Checklist

- [ ] **Atomic hold placement:** Passes single-process tests — verify it also passes a real-concurrent-connections test against Postgres via testcontainers, not just the in-memory backend (Pitfall 16).
- [ ] **DST handling:** Grid generation "works" against a handful of typical days — verify it's been explicitly tested against a documented spring-forward date and fall-back date for at least one DST-observing IANA zone, and against a resource whose hours span midnight on those dates (Pitfalls 7, 8, 9).
- [ ] **Lazy hold expiry:** Confirmed holds can't be created for expired holds — verify availability *reads* also correctly exclude expired-but-unreclaimed holds via the one shared reclaim primitive, not just the write path (Pitfall 5).
- [ ] **Storage protocol swappability:** In-memory and SQL implementations both "pass their own tests" — verify the *same* contract test suite runs unmodified against both, with no backend-specific test-only helpers (Pitfall 12).
- [ ] **Structured output contract:** Consumer's stub and the real implementation "look similar" — verify there's an automated schema-conformance check that would fail if they diverged, not just a documentation comparison (Pitfall 13).
- [ ] **SQL schema:** Database "gets created fine" for the first run — verify there's a versioned migration path for the *second* schema change, tested against an existing populated database, not just fresh `create_all()` (Pitfall 15).

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|----------------|------------------|
| Capacity race shipped and caused real overbooking | MEDIUM | Add the missing atomic conditional write/row lock; audit historical data for over-capacity periods to decide if any compensating consumer-facing action (e.g. notify affected bookers) is needed — this is a data-integrity incident, not just a code fix |
| DST gap/ambiguity bug discovered after resources with affected zones are live | MEDIUM | Backfill-correct any grid/slot records generated incorrectly around the transition date; add the missing DST fixture tests so it can't regress; this is generally contained to specific dates/zones, not a systemic corruption |
| Storage protocol leak discovered after the SQL implementation has consumers depending on the leaked shape | HIGH | Requires a breaking Protocol version bump and coordinated update on the consumer side — exactly the scenario contract-first design (Pitfall 12, 13) exists to prevent; budget for a deprecation window if any consumer has already repinned |
| Schema migration tooling retrofitted after consumer databases already exist | HIGH | Requires hand-writing a "baseline" migration that matches the existing ad hoc schema exactly before any further migrations can be layered on top — error-prone and best avoided entirely by doing Pitfall 15's prevention from the start |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|-------------------|----------------|
| 1. Check-then-insert capacity TOCTOU | Hold/booking lifecycle | Concurrency test: N parallel `place_hold()` calls against capacity-1 resource → exactly 1 succeeds, across all backends |
| 2. SQLite/Postgres locking divergence | SQL storage implementation | Shared parametrized contract test run against both SQLite (with `BEGIN IMMEDIATE`) and Postgres (with `FOR UPDATE`) via testcontainers |
| 3. Two-step capacity counting inside a transaction | SQL storage implementation | Test under `READ COMMITTED` (Postgres default) specifically, not just `SERIALIZABLE`, to catch the phantom-read gap |
| 4. Hold-confirm TTL boundary race | Hold/booking lifecycle | Test confirming a hold at/just-past its exact expiry instant, using DB-side "now" comparison, both succeeding and failing paths |
| 5. Lazy expiry starves availability | Hold/booking lifecycle | Test that `get_availability()` and `place_hold()` both correctly reclaim/exclude an expired hold via the same shared primitive |
| 6. Naive/aware datetime mixing | Core domain model | Runtime assertion rejecting naive datetimes at every public API boundary; a test asserting this raises |
| 7. DST spring-forward gap | Core domain model / grid generation | Fixture test: generate a grid for a resource whose hours span a documented gap date; assert deliberate, documented behavior (skip or shift) |
| 8. DST fall-back ambiguity | Core domain model / grid generation | Fixture test: generate a grid spanning a documented fall-back date; assert two distinct, correctly-ordered slots, not a dupe or drop |
| 9. Midnight-crossing operating hours | Core domain model (schema definition) | Test a resource with midnight-crossing hours on a DST-transition night |
| 10. Buffer/reset inconsistency | Core domain model / interval math | Test back-to-back bookings with buffer via the single shared "effective occupied interval" function; assert no double-count or drop |
| 11. Half-open/closed interval inconsistency | Core domain model / interval math | Property-based test: for any two generated intervals, the shared `intervals_overlap()` utility agrees with a brute-force reference implementation at every boundary |
| 12. Storage protocol leaks backend concepts | Storage protocol definition | Same contract test suite, unmodified, passes against in-memory and SQL implementations |
| 13. Structured output contract drift | Structured output contract | Automated schema-conformance test comparing real engine output against the consumer-facing stub/schema |
| 14. Partial-async event-loop stalls | SQL storage implementation | Concurrent-load test asserting interleaved (not fully serialized) execution against the SQLite backend specifically |
| 15. No schema migration story | SQL storage implementation | A second, real migration applied and tested against a populated database created from the first schema |
| 16. Concurrency only verified in-memory | Testing infrastructure | testcontainers-backed Postgres concurrency test exists and runs in CI, not just locally/manually |
| 17. Frozen-clock breaks async tests | Testing infrastructure | Canary test confirming the chosen time-freezing tool + `real_asyncio`/equivalent setting doesn't hang a hold-expiry async test |

## Sources

- [What to do about SQLITE_BUSY errors despite setting a timeout](https://berthub.eu/articles/posts/a-brief-post-on-sqlite3-database-locked-despite-timeout/) — MEDIUM confidence
- [SQLite WAL & Concurrency docs](https://coddy.tech/docs/sqlite/wal-mode-and-concurrency) — MEDIUM confidence
- [SELECT FOR UPDATE considered harmful in PostgreSQL — Cybertec](https://www.cybertec-postgresql.com/en/select-for-update-considered-harmful-postgresql/) — MEDIUM confidence
- [Using FOR UPDATE SKIP LOCKED for queue workflows — netdata](https://www.netdata.cloud/academy/update-skip-locked/) — MEDIUM confidence
- [PostgreSQL docs: Transaction Isolation](https://www.postgresql.org/docs/current/transaction-iso.html) — MEDIUM confidence
- [PEP 495 — Local Time Disambiguation (fold)](https://peps.python.org/pep-0495/) — MEDIUM confidence
- [Ten Python datetime pitfalls](https://dev.arie.bovenberg.net/blog/python-datetime-pitfalls/) — MEDIUM confidence
- [Booking limits exceeded by concurrent requests — Cal.com TOCTOU issue](https://github.com/calcom/cal.diy/issues/29605) — MEDIUM confidence
- [Handling the Double-Booking Problem in Databases](https://adamdjellouli.com/articles/databases_notes/07_concurrency_control/04_double_booking_problem) — MEDIUM confidence
- [Time-of-check to time-of-use — Wikipedia](https://en.wikipedia.org/wiki/Time-of-check_to_time-of-use) — MEDIUM confidence
- [Half-open interval — Wikipedia](https://en.wikipedia.org/wiki/Half-open) — MEDIUM confidence
- [Overlapping Intervals: My Calendar II](https://medium.com/@passionshiv007/overlapping-intervals-3-my-calendar-ii-485e735dda84) — MEDIUM confidence
- [Getting started with Testcontainers for Python](https://testcontainers.com/guides/getting-started-with-testcontainers-for-python/) — MEDIUM confidence
- [time-machine versus freezegun, a benchmark — Adam Johnson](https://adamj.eu/tech/2021/02/19/freezegun-versus-time-machine/) — MEDIUM confidence
- [freezegun hangs parametrized asyncio test — GitHub issue #401](https://github.com/spulec/freezegun/issues/401) — MEDIUM confidence
- [freezegun asyncio tests source](https://github.com/spulec/freezegun/blob/master/tests/test_asyncio.py) — MEDIUM confidence
- [Stock Reservation and Cart Fairness — "Soft Reservation"](https://medium.com/@umutt.akbulut/stock-reservation-and-cart-fairness-is-soft-reservation-really-fair-2de5c8acaf23) — MEDIUM confidence
- Domain expertise / established distributed-systems and interval-math theory (row locking, half-open interval overlap formula, TOCTOU pattern, lease/TTL reclamation) — HIGH confidence, cross-checked against the sources above

---
*Pitfalls research for: Domain-agnostic async Python scheduling/availability engine*
*Researched: 2026-09-02*
