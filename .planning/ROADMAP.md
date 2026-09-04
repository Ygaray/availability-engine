# Roadmap: availability-engine

## Overview

A domain-agnostic Python scheduling library built as a series of **vertical MVP slices**. Phase 1
stands up a complete, importable `AvailabilityEngine` over the in-memory backend — define a resource,
generate a slot grid, answer availability, and place/confirm/release a hold, end to end — so the
parallel booking chatbot can code against a real structured contract immediately. Later phases harden
correctness underneath that already-working library: capacity-aware + DST correctness and a frozen
contract (Phase 2), idempotency + cancellation for a network-facing consumer (Phase 3), then the real
SQL backend (SQLite + Postgres) swapping in invisibly with a real-Postgres concurrency proof (Phase 4),
and finally packaging, docs, and the v1 git tag the consumer repins to (Phase 5). The engine names zero
domain concepts throughout; correctness lives in the storage backend behind a coarse-grained async
protocol.

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: End-to-End Walking Skeleton (In-Memory)** - Importable engine that defines a resource, generates a grid, answers availability, and places/confirms/releases a hold end to end (completed 2026-09-03)
- [x] **Phase 2: Capacity & Time Correctness** - Capacity-aware (≥1) availability, DST/midnight-crossing correctness, lazy expiry, reason codes, and a frozen documented contract (completed 2026-09-04)
- [ ] **Phase 3: Idempotency & Cancellation** - Retry-safe hold/confirm via idempotency keys and cancellation of confirmed bookings
- [ ] **Phase 4: SQL Backend & Concurrency Proof** - Real SQLite+Postgres backend swaps in beneath the engine, with a testcontainers-Postgres proof that concurrent holds never overbook
- [ ] **Phase 5: Packaging, Docs & v1 Release** - Packaged, documented, and cut as a v1 git tag the first consumer can repin to

## Phase Details

### Phase 1: End-to-End Walking Skeleton (In-Memory)

**Goal**: A working, importable `AvailabilityEngine` over the in-memory store that defines a resource, generates a fixed-duration slot grid, answers structured availability, and places/confirms/releases a hold — end to end, TZ-aware at the boundary — so the parallel consumer can start coding against a real structured output.
**Mode:** mvp
**Depends on**: Nothing (first phase)
**Requirements**: MODEL-01, MODEL-02, MODEL-03, MODEL-04, MODEL-05, GRID-01, GRID-04, AVAIL-01, STORE-01, STORE-02, HOLD-01, HOLD-03, HOLD-04
**Success Criteria** (what must be TRUE):

  1. A developer can import `AvailabilityEngine`, construct it over the in-memory store, and define a Resource with capacity ≥1, per-weekday operating hours, a buffer/reset time, and an IANA timezone.
  2. Asking the engine over a date range returns a fixed-duration slot grid derived from the resource's operating hours + slot length + buffer.
  3. Querying availability over a range returns a structured `available` / `booked` result shape the parallel consumer can code against.
  4. A caller can place a hold on a slot, confirm it into a booking carrying an opaque payload that round-trips untouched, and release a hold — end to end against the in-memory backend behind the async storage protocol.
  5. The public API rejects naive (non-UTC) datetimes at the boundary; all value objects are immutable and use half-open `[start, end)` intervals throughout.

**Plans**: 0/3 plans executed

- [x] 01-01-PLAN.md
- [x] 01-02-PLAN.md
- [x] 01-03-PLAN.md

### Phase 2: Capacity & Time Correctness

**Goal**: The engine's availability is provably capacity-aware for capacity ≥1 and correct across DST transitions and midnight-crossing hours; expired holds stop counting lazily, rejections carry reason codes, and the structured output contract is frozen and documented for the parallel consumer.
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: AVAIL-02, AVAIL-03, AVAIL-04, GRID-02, GRID-03, HOLD-05, HOLD-08
**Success Criteria** (what must be TRUE):

  1. Availability reports remaining capacity as a count (never collapsed to a boolean) and is correct for a capacity-K resource — a slot with J active holds reports K−J remaining — computed via sweep-line event counting.
  2. Grid generation produces no missing, duplicated, or hour-shifted slots across a real spring-forward date, a real fall-back date, and operating hours that cross midnight (fixture-tested on documented transition dates).
  3. Availability reads exclude expired holds via the one shared active-entries primitive (`expires_at > now`); an expired hold stops counting against capacity on the next read or hold attempt, with no background sweeper.
  4. Rejections carry machine-readable reason codes (e.g. `capacity_exhausted`, `outside_hours`, `hold_expired`, `not_found`).
  5. The structured output contract is documented and frozen, with an automated conformance test the parallel consumer's stub can be checked against.

**Plans**: 3/3 plans executed
**Wave 1**

- [x] 02-01-PLAN.md — Fix midnight-crossing time.py bug + DST fixture tests (GRID-02, GRID-03); pin tzdata/time-machine/hypothesis

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 02-02-PLAN.md — Collapse duplicated active-entries scan into one shared expiry-filtering primitive (AVAIL-03, HOLD-05)
- [x] 02-03-PLAN.md — Capacity-shape contract restructure, reason codes, engine wiring, golden-file conformance (AVAIL-02, AVAIL-04, HOLD-08)

### Phase 3: Idempotency & Cancellation

**Goal**: Hold and confirm operations are safe to retry via idempotency keys, and confirmed bookings can be cancelled — completing the write-side lifecycle a network-facing consumer needs before it relies on the contract.
**Mode:** mvp
**Depends on**: Phase 2
**Requirements**: HOLD-06, HOLD-07
**Success Criteria** (what must be TRUE):

  1. Calling `place_hold` or `confirm` twice with the same idempotency key returns the original result instead of acting twice (enforced by a unique constraint / conditional write).
  2. A retried call that races the original never double-spends capacity; a genuinely conflicting key surfaces an `idempotency_conflict` reason code.
  3. A caller can cancel a confirmed booking, and its capacity is freed immediately — the freed slot reappears on the next availability read.

**Plans**: TBD

### Phase 4: SQL Backend & Concurrency Proof

**Goal**: A production SQL backend (SQLite for dev, Postgres for prod) swaps in beneath the already-working engine — invisibly to the consumer — with the portable atomic conditional-write pattern proven to never overbook under real concurrent Postgres load.
**Mode:** mvp
**Depends on**: Phase 3
**Requirements**: STORE-03, STORE-04, STORE-05, HOLD-02
**Success Criteria** (what must be TRUE):

  1. The same parametrized contract test suite passes unmodified against the in-memory, SQLite, and Postgres backends.
  2. Swapping the SQL backend under an existing engine requires no consumer code change — the engine facade and structured output contract are byte-for-byte identical to the in-memory path.
  3. A concurrency test runs N parallel `place_hold` calls against a capacity-K resource on real Postgres (testcontainers) and proves at most K succeed — no overbooking under OS-level concurrent connections.
  4. The SQL schema ships with versioned migrations from the first commit (initial migration = current schema), applied and tested against both SQLite and Postgres.

**Plans**: TBD

### Phase 5: Packaging, Docs & v1 Release

**Goal**: The library is packaged, documented, and cut as a v1 git tag the first consumer can repin to, with an example integration proving the frozen contract matches the consumer's stub.
**Mode:** mvp
**Depends on**: Phase 4
**Requirements**: PKG-01, PKG-02, PKG-03
**Success Criteria** (what must be TRUE):

  1. The library installs via a git-tag pin (`uv` + `hatchling`, Python 3.12+) into a fresh consumer project.
  2. Public API docs cover the engine facade, storage protocol, output contract, concurrency guarantees, and TZ/DST semantics.
  3. An example integration fulfills the consumer's stub and passes the contract conformance test end to end.
  4. v1.0 is cut as a git tag / release the first consumer can repin to.

**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. End-to-End Walking Skeleton (In-Memory) | 3/3 | Complete    | 2026-09-03 |
| 2. Capacity & Time Correctness | 3/3 | Complete    | 2026-09-04 |
| 3. Idempotency & Cancellation | 0/TBD | Not started | - |
| 4. SQL Backend & Concurrency Proof | 0/TBD | Not started | - |
| 5. Packaging, Docs & v1 Release | 0/TBD | Not started | - |
</content>
</invoke>
