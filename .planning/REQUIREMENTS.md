# Requirements — availability-engine

Scope for **v1.0**. All v1 requirements are hypotheses until shipped and validated.
Derived from `.planning/PROJECT.md` and `.planning/research/` (STACK, FEATURES, ARCHITECTURE, PITFALLS, SUMMARY).

REQ-ID format: `[CATEGORY]-[NN]`. Consumer of these requirements: the parallel booking chatbot,
which codes contract-first against the stubbed structured output.

---

## v1 Requirements

### Domain Model (`MODEL`)

- [x] **MODEL-01**: Consumer can define a Resource with a capacity of ≥ 1 concurrent bookings
- [x] **MODEL-02**: Consumer can set a Resource's per-day operating hours (per weekday), expressed in the resource's local wall-clock time
- [x] **MODEL-03**: Consumer can set a Resource's buffer/reset time enforced between consecutive sessions
- [x] **MODEL-04**: Consumer can assign a Resource an IANA timezone (e.g. `America/Chicago`) that governs its operating hours and DST
- [x] **MODEL-05**: All domain value objects (Resource, Slot, Hold, Booking, availability outputs) are immutable and use half-open `[start, end)` time intervals throughout

### Time & Slot Grid (`GRID`)

- [x] **GRID-01**: Engine generates a fixed-duration slot grid for a Resource from its operating hours + slot length + buffer
- [x] **GRID-02**: Grid generation is correct across DST transitions — spring-forward gaps and fall-back ambiguity produce no missing, duplicated, or hour-shifted slots (fixture-tested on real transition dates)
- [x] **GRID-03**: Engine handles operating hours that cross midnight without truncating or double-counting slots
- [x] **GRID-04**: All engine inputs/outputs at the public boundary are UTC-aware datetimes; the engine rejects naive datetimes; timezone conversion happens only at the facade edge

### Availability Query (`AVAIL`)

- [x] **AVAIL-01**: Consumer can query a Resource's availability over a date range and receive structured `available` / `booked` windows
- [x] **AVAIL-02**: Availability is capacity-aware — a slot reports remaining capacity as a count (never collapsed to a boolean), computed via sweep-line event counting so capacity ≥ 1 is correct
- [x] **AVAIL-03**: Availability reads exclude expired holds (lazy expiry: active = `expires_at > now`), via the one shared active-entries primitive used by every read and write path
- [x] **AVAIL-04**: The structured output contract is stable and documented, so the parallel consumer's stub matches the real output (conformance-testable)

### Holds & Bookings (`HOLD`)

- [x] **HOLD-01**: Consumer can place a short-lived, atomic hold on a slot with a TTL; the hold is rejected if the slot's capacity is already exhausted
- [ ] **HOLD-02**: Concurrent hold placement never exceeds capacity — under N concurrent bookers on a capacity-K slot, at most K holds succeed (proven against real Postgres, not only in-memory)
- [x] **HOLD-03**: Consumer can confirm an active, unexpired hold into a Booking, attaching an opaque consumer payload that round-trips untouched
- [x] **HOLD-04**: Consumer can explicitly release a hold, freeing its capacity immediately
- [x] **HOLD-05**: Expired holds auto-release lazily — they stop counting against capacity on the next read or hold attempt, with no background sweeper
- [x] **HOLD-06**: Consumer can cancel a confirmed Booking, freeing its capacity
- [x] **HOLD-07**: `place_hold` and `confirm` accept an optional idempotency key; a retry with the same key returns the original result instead of acting twice (enforced by a unique constraint / conditional write)
- [x] **HOLD-08**: Rejections carry machine-readable reason codes (e.g. `capacity_exhausted`, `outside_hours`, `hold_expired`, `not_found`, `idempotency_conflict`)

### Storage (`STORE`)

- [x] **STORE-01**: Engine defines a coarse-grained async storage protocol whose methods are each exactly one atomic operation; the engine is written against the protocol, never a concrete backend
- [x] **STORE-02**: An in-memory storage implementation ships as the reference/test backend
- [ ] **STORE-03**: One SQL storage implementation targets both SQLite (dev) and Postgres (prod), using the portable atomic conditional-write pattern (`BEGIN IMMEDIATE` on SQLite, `FOR UPDATE` / row locks on Postgres)
- [ ] **STORE-04**: The same parametrized contract test suite passes unmodified against in-memory, SQLite, and Postgres backends
- [ ] **STORE-05**: The SQL schema is versioned with migrations from the first commit (initial migration = current schema)

### Packaging & Contract (`PKG`)

- [ ] **PKG-01**: The library is packaged with `uv` + `hatchling` for Python 3.12+, installable via git-tag pin
- [ ] **PKG-02**: The public API surface (engine facade + storage protocol + output contract) is documented, including concurrency guarantees and TZ/DST semantics
- [ ] **PKG-03**: v1 is cut as a git tag / release the first consumer can repin to

---

## v2 Requirements (deferred)

- **AVAIL-v2-01**: Multi-resource / next-available query (fan-out + merge)
- **AVAIL-v2-02**: Free/busy merged-window output mode alongside the slot-list mode
- **HOLD-v2-01**: Rescheduling as a first-class atomic operation (not cancel + rebook)
- **MODEL-v2-01**: Blackout dates / one-off closures beyond per-day operating hours
- **GRID-v2-01**: Arbitrary-duration / continuous-interval bookings (v1's half-open interval math is designed to extend into this without rework)

---

## Out of Scope

- **Recurrence (RRULE), holidays, recurring overrides** — heavy; not needed for the first consumer's v1 contract. Deferred beyond v2 planning.
- **Any domain vocabulary or consumer-specific logic** — violates the one-way, domain-agnostic dependency rule.
- **Background sweeper / active expiry process** — a library should not own a runtime lifecycle; expiry is lazy-on-read.
- **Pricing, payments, notifications, user/auth, UI, waitlists** — consumer concerns, not availability-correctness concerns.
- **Redis or other concrete backends** beyond in-memory + SQL — not needed for v1; the storage protocol keeps the door open.
- **General calendar (events-on-a-calendar) semantics and external calendar-provider sync** — this engine owns the resource/capacity/hold model; calendar sync is a possible future adapter.

---

## Traceability

Requirement → phase mapping. Phases defined in `.planning/ROADMAP.md`.

| REQ-ID | Phase | Status |
|--------|-------|--------|
| MODEL-01 | Phase 1 | Complete |
| MODEL-02 | Phase 1 | Complete |
| MODEL-03 | Phase 1 | Complete |
| MODEL-04 | Phase 1 | Complete |
| MODEL-05 | Phase 1 | Complete |
| GRID-01 | Phase 1 | Complete |
| GRID-04 | Phase 1 | Complete |
| AVAIL-01 | Phase 1 | Complete |
| STORE-01 | Phase 1 | Complete |
| STORE-02 | Phase 1 | Complete |
| HOLD-01 | Phase 1 | Complete |
| HOLD-03 | Phase 1 | Complete |
| HOLD-04 | Phase 1 | Complete |
| AVAIL-02 | Phase 2 | Complete |
| AVAIL-03 | Phase 2 | Complete |
| AVAIL-04 | Phase 2 | Complete |
| GRID-02 | Phase 2 | Complete |
| GRID-03 | Phase 2 | Complete |
| HOLD-05 | Phase 2 | Complete |
| HOLD-08 | Phase 2 | Complete |
| HOLD-06 | Phase 3 | Complete |
| HOLD-07 | Phase 3 | Complete |
| STORE-03 | Phase 4 | Pending |
| STORE-04 | Phase 4 | Pending |
| STORE-05 | Phase 4 | Pending |
| HOLD-02 | Phase 4 | Pending |
| PKG-01 | Phase 5 | Pending |
| PKG-02 | Phase 5 | Pending |
| PKG-03 | Phase 5 | Pending |
