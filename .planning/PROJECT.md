# availability-engine

## What This Is

A reusable, **domain-agnostic Python scheduling library** that models `resources × time-slots × holds`
and emits structured `available` / `booked` outputs. It answers two questions safely and
deterministically — *"what's available?"* and *"can I take this slot, atomically?"* — while naming
**zero** domain concepts (no "room", "escape", "appointment"); the domain is injected by the consumer.
Built **contract-first** so its first consumer, a reusable booking chatbot backend, can code against
the structured contract (stubbed) while this library is built in parallel.

## Core Value

**Atomic, correct availability:** given resources and existing bookings, compute open slots
deterministically, and let one — and only one — booker hold a slot at a time. If everything else
fails, no two bookers can ever double-book the same capacity.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Model resources with capacity (≥1), per-day operating hours, and buffer/reset time between sessions
- [ ] Generate a fixed-duration slot grid per resource from its hours + slot length + buffer
- [ ] Compute structured availability (`available` / `booked` windows, capacity-aware) for a resource over a range
- [ ] Place an atomic hold on a slot (short-lived, TTL); reject if capacity is exhausted
- [ ] Confirm a hold into a booking, carrying an opaque consumer payload
- [ ] Release a hold explicitly, and auto-release expired holds lazily on the next read/attempt
- [ ] Cancel a confirmed booking
- [ ] Accept an idempotency key on hold/confirm so a retried call returns the original result instead of acting twice (enforced via a unique constraint)
- [ ] Define a pluggable async storage protocol; ship an in-memory implementation for tests
- [ ] Ship one SQL storage implementation targeting SQLite (local/dev) and Postgres (prod) with row-lock atomicity
- [ ] Handle timezones TZ-aware, UTC-internal, with a per-resource IANA zone for operating hours + DST
- [ ] Publish the structured output contract the consumer renders (stable, documented shapes)

### Out of Scope

- Recurring rules (RRULE), holidays, one-off closures/overrides — deferred to a later milestone; heavy, and not needed for the first consumer's v1 contract
- Arbitrary-duration / continuous-interval bookings — deferred; v1 is fixed-grid, but the interval math is designed so this can be added without rework
- Any domain vocabulary or consumer-specific logic — violates the one-way, domain-agnostic dependency rule
- Background sweeper / active expiry process — a library should not own a runtime lifecycle; expiry is lazy-on-read
- Redis or other concrete backends beyond in-memory + SQL — not needed for v1; the storage protocol keeps the door open
- Being a general calendar (events-on-a-calendar) — this engine owns the resource/capacity/hold model; external calendars are an optional future sync/export adapter

## Context

- **Ecosystem:** Part of the `~/Projects/Reusable/` hub-and-spoke ecosystem (see `~/.claude/context/deps/`). One-way dependency: consumers import this engine; this engine imports no consumer and names no consumer's domain.
- **First consumer:** `SocialNetwork-Chatbot` — the reusable booking chatbot backend. Built contract-first: the chatbot codes against this engine's stubbed structured contract while this lib is built in parallel, then repins to a real git tag.
- **Distribution:** Consumed via **git-tag pin** (uv source), matching the `YahirReusableBot` convention. Public GitHub by default.
- **Seed brief:** `README.md` in the repo root is the original seed and core-model sketch; this document supersedes it for planning.
- **Why not a general calendar:** Google Calendar et al. model events on a calendar, not resources with capacity and atomic holds — so this engine owns that model directly.

## Constraints

- **Tech stack**: Python 3.12+, `uv` + `hatchling` — matches the reusable-ecosystem convention; enables git-tag pinning by consumers.
- **Dependencies**: One-way only — engine imports no consumer, names no consumer's domain. Keeps it reusable across unrelated booking domains.
- **Correctness**: Timezone/DST correctness is non-negotiable for a scheduling engine — TZ-aware, UTC-internal from day one.
- **Concurrency**: Atomic holds must hold under concurrent bookers; the storage backend is responsible for atomicity, the engine defines the contract.
- **API style**: Storage protocol is async (works with async consumers like the chatbot); the public engine API follows suit where it touches storage.
- **Contract stability**: The structured output contract is the product surface — it must be stable and documented, since a parallel consumer codes against it.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Pluggable async storage backend (protocol + in-memory + SQL impls) | Atomicity becomes a contract the backend satisfies; keeps the engine reusable and testable | — Pending |
| Fixed-duration slot grid in v1, interval math extensible to arbitrary windows | Simplest to reason about/query now; avoids a rewrite when continuous bookings are added later | — Pending |
| v1 calendar scope = per-day hours + buffers + capacity>1; recurrence deferred | Covers the first consumer's real needs without the recurrence iceberg | — Pending |
| TZ-aware, UTC-internal, per-resource IANA zone | Scheduling engines live or die on DST correctness; per-resource zones support co-located or distributed resources | — Pending |
| One SQL impl spanning SQLite + Postgres, row-lock atomicity | Zero-infra local dev (SQLite) + prod (Postgres) from one codebase; matches a typical chatbot deploy | — Pending |
| Lazy-on-read hold expiry (no background sweeper) | Deterministic and easy to test; a library shouldn't own a runtime lifecycle | — Pending |
| Contract-first build against a stubbed structured output | Lets the consumer chatbot progress in parallel; forces an early, stable contract | — Pending |
| Idempotency keys on hold/confirm in v1 | First consumer is network-facing (retries on timeout); without keys a retry double-spends capacity. Cheap now, contract-breaking to retrofit | — Pending |
| Portable atomicity: single INSERT…SELECT + capacity WHERE + rowcount; BEGIN IMMEDIATE (SQLite) / FOR UPDATE (Postgres) | The only pattern truly identical across both backends; SQLite has no row-level locking. Statement atomicity is the lock | — Pending |
| Sweep-line event counting for capacity-aware availability | Binary interval subtraction only works for capacity 1; sweep-line handles capacity ≥ 1 from day one without a v2 rewrite | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-09-02 after initialization*
