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

- [x] Model resources with capacity (≥1), per-day operating hours, and buffer/reset time between sessions — Validated in Phase 1: End-to-End Walking Skeleton (MODEL-01..05)
- [x] Generate a fixed-duration slot grid per resource from its hours + slot length + buffer — Validated in Phase 1: End-to-End Walking Skeleton (GRID-01, GRID-04)
- [x] Confirm a hold into a booking, carrying an opaque consumer payload — Validated in Phase 1: End-to-End Walking Skeleton (HOLD-03)
- [x] Define a pluggable async storage protocol; ship an in-memory implementation for tests — Validated in Phase 1: End-to-End Walking Skeleton (STORE-01, STORE-02)
- [x] Compute structured availability (`available` / `booked` windows) for a resource over a range, capacity-aware (remaining as a count, never a boolean, via sweep-line event counting) — Validated in Phase 2: Capacity & Time Correctness (AVAIL-02, AVAIL-04)
- [x] Handle timezones TZ-aware, UTC-internal, with a per-resource IANA zone for operating hours + DST, correct across spring-forward/fall-back and midnight-crossing operating hours — Validated in Phase 2: Capacity & Time Correctness (GRID-02, GRID-03)
- [x] Auto-release expired holds lazily on the next read/attempt via one shared active-entries primitive, no background sweeper — Validated in Phase 2: Capacity & Time Correctness (AVAIL-03, HOLD-05)
- [x] Publish the structured output contract the consumer renders (stable, documented shapes, machine-readable reason codes on rejection) — Validated in Phase 2: Capacity & Time Correctness (AVAIL-04, HOLD-08)
- [x] Cancel a confirmed booking, freeing its capacity immediately — never a silent no-op on an unknown or already-cancelled booking — Validated in Phase 3: Idempotency & Cancellation (HOLD-06)
- [x] Accept an idempotency key on hold/confirm so a retried call returns the original result instead of acting twice; a genuinely conflicting key surfaces a dedicated reason code, and a concurrent same-key race is proven never to double-spend capacity — Validated in Phase 3: Idempotency & Cancellation (HOLD-07)
- [x] Place an atomic hold on a slot (short-lived, TTL); reject if capacity is exhausted, proven under real concurrent load against Postgres (not merely in-memory) — Validated in Phase 4: SQL Backend & Concurrency Proof (HOLD-02)
- [x] Ship one SQL storage implementation targeting SQLite (local/dev) and Postgres (prod), with versioned migrations from the first commit — Validated in Phase 4: SQL Backend & Concurrency Proof (STORE-03, STORE-04, STORE-05)
- [x] Package the library with `uv` + `hatchling` for Python 3.12+, installable via git-tag pin, with Alembic migrations force-included so a pinned consumer can bootstrap a schema — Validated in Phase 5: Packaging, Docs & v1 Release (PKG-01)
- [x] Document the public API surface (engine facade, storage protocol, output contract, concurrency guarantees, TZ/DST semantics) as the stable product surface, with an automated doc-example regression test — Validated in Phase 5: Packaging, Docs & v1 Release (PKG-02)
- [x] Cut v0.1.0 as the first git tag a consumer repins to, gated by full-suite-green and an explicit human-verify checkpoint — Validated in Phase 5: Packaging, Docs & v1 Release (PKG-03)

### Active

*No active (in-progress) requirements — Phase 5 (Packaging, Docs & v1 Release) is complete. All v1.0 milestone phases (1-5) are done.*

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
- **Phase 1 complete (2026-09-03):** A working, importable `AvailabilityEngine` over `InMemoryStore` — define a Resource, generate a fixed-duration slot grid, answer structured availability, and place/confirm/release a hold, end to end, TZ-aware at the boundary. All 5 roadmap success criteria and all 13 mapped requirement IDs verified; code review (2 critical + 3 warning + 3 info findings, all resolved), security audit (6 threats, all mitigated/accepted, `threats_open: 0`), and Nyquist validation (zero coverage gaps, 22/22 tests green) all passed.
- **Phase 2 complete (2026-09-04):** Capacity ≥1 availability is provably correct via sweep-line event counting; DST spring-forward/fall-back and midnight-crossing operating hours are fixture-proven correct on real 2026 transition dates; expired holds auto-release lazily through one shared active-entries primitive; all domain exceptions carry machine-readable `.reason_code`; the public output contract is frozen behind a golden-file conformance test. Executed as 3 plans across 2 waves via isolated git worktrees, merged with one cross-plan integration fix (a hold-expiry test's slot fell outside a fixture resource's operating hours once the new `OutsideHoursError` check landed). Code review then found and fixed 2 further critical cross-plan integration bugs — an overnight-hours `OutsideHoursError` false-rejection and an uncaught crash from reducing capacity below the active-hold count — plus 2 warnings (unvalidated overlapping/zero-length `LocalInterval`s) and 1 info finding, all resolved with regression tests. Security audit: 6 threats (4 accepted per locked project decisions, 2 mitigated and verified in code), `threats_open: 0`. Nyquist validation: zero coverage gaps, 46/46 tests green, `ruff`/`mypy --strict` clean. All 7 roadmap success criteria and all 7 mapped requirement IDs verified.
- **Phase 3 complete (2026-09-04):** The write-side lifecycle a network-facing consumer needs is complete — `cancel_booking` is wired end-to-end as a distinct, non-idempotent terminal-status operation (never routed through `release_hold`'s silent no-op path), and `place_hold`/`confirm_hold` both accept an optional `idempotency_key` that makes a duplicated network retry safe, fingerprinted and lock-guarded inside `InMemoryStore`'s existing critical section (no new lock, no TOCTOU window). Executed as 2 sequential plans (03-02 depended on 03-01) via isolated git worktrees. Code review found and the code-fixer resolved 1 critical finding — cached idempotency records were returned verbatim even after the underlying `Hold`/`Booking` changed state (released, expired, confirmed, or cancelled), producing stale/phantom replay results; the fix re-validates against live `_holds`/`_bookings` state on every cache hit — plus 4 warnings (missing `confirm_hold` contract-suite coverage, non-deterministic payload fingerprinting for non-JSON-native payloads, `ReasonCode` not re-exported from the top-level package, `place_hold`'s `payload` param silently discarded) and 2 info findings, all resolved with dedicated regression tests (test suite grew 58→69). Security audit: 7 threats (6 mitigated and verified in code, 1 — unbounded idempotency-dict growth — explicitly accepted per the project's no-background-sweeper design rule), `threats_open: 0`. Nyquist validation: zero coverage gaps, 69/69 tests green. Gate-1 self-UAT (headless, driven via the real `AvailabilityEngine` facade against `InMemoryStore` in fresh Python processes, including an adversarial re-probe of the CR-01 staleness class of bug): all 3 roadmap success criteria PASS. All 3 roadmap success criteria and both mapped requirement IDs (HOLD-06, HOLD-07) verified.
- **Phase 4 complete (2026-09-04):** A production SQL backend (`SQLStore`) swaps in beneath `AvailabilityEngine` with zero consumer-visible change — `engine.py`/`contracts.py` are byte-for-byte identical to the in-memory path across the whole phase's diff. Dialect-aware locking (`pg_advisory_xact_lock` on Postgres, `BEGIN IMMEDIATE` on SQLite, the latter now auto-attached on construction) supersedes the earlier bare `FOR UPDATE` design (D-01), and is empirically proven — not just reasoned about — via `test_concurrency_proof.py`'s real, independently-connected concurrent clients (K=1/N=25 and K=3/N=30, exact success counts, 5/5 clean runs). The same 18-method contract suite passes unmodified against in-memory/SQLite/Postgres (54/54 cases), and Alembic migrations ship from the first commit with `env.py` importing `models.py`'s `MetaData` directly (zero schema-drift risk). Executed as 4 plans across 3 waves via isolated git worktrees; the only cross-plan wave-2 conflict was a `REQUIREMENTS.md` merge (both parallel plans marked different requirement rows complete), resolved by taking the union. Code review found 2 critical cross-cutting bugs beyond the plan's literal scope — `confirm_hold` never checked its `DELETE`'s rowcount before materializing a `Booking`, letting a concurrently-released hold still produce a phantom booking (CR-01); and the SQLite `BEGIN IMMEDIATE` serialization fix was only ever wired into test fixtures, leaving the "obvious" `SQLStore(engine)` construction path unprotected by default (CR-02) — plus 4 warnings (unguarded `save_resource` race, a "private" cross-module import, an undocumented capacity-fallback edge case, an empty package `__init__.py`), all fixed with regression tests. Phase-goal verification then caught the new CR-01 regression test itself was flaky (~86% failure rate, a test-only bug — never freed the slot after a legitimate "confirm wins" outcome, poisoning every subsequent loop iteration); fixed and re-verified reliable (20/20 clean runs across two independent re-verification passes). Security audit: 7 threats (6 mitigated and verified in code, 1 — unbounded idempotency-table growth — accepted per the existing no-background-sweeper design rule), `threats_open: 0`. Nyquist validation: zero coverage gaps, 114/114 tests green, `mypy --strict` clean. All 4 roadmap success criteria and all 4 mapped requirement IDs (STORE-03, STORE-04, STORE-05, HOLD-02) verified.
- **Phase 5 complete (2026-09-05):** The library is packaged, documented, and cut as the `v0.1.0` git tag the first consumer repins to. The confirmed packaging gap (Alembic migrations living outside the wheel) was fixed via `force-include` into an importable in-package anchor, proven by a real build+install+migrate round trip. A thin `SyncAvailabilityEngine` background-thread facade bridges the async engine for sync consumer call sites. An example `AvailabilityPort` adapter (`examples/chatbot_adapter.py`) was proven against `SocialNetwork-Chatbot`'s own shipped `AvailabilityContractSuite` (10/10 conformance tests pass, dev-only dependency group pinned to that consumer's tagged release, not `main`), closing the cross-repo contract loop end to end. `README.md` was rewritten as the frozen, documented product surface — both facades, the storage protocol, the two-list output contract, the exact dialect-aware locking guarantees Phase 4 proved (`pg_advisory_xact_lock`/`BEGIN IMMEDIATE`), and fixture-tested TZ/DST semantics — with every code example proven against the real installed API by an automated regression test. Executed as 5 sequential/parallel plans; code review found and fixed 10 findings (2 critical, incl. a malformed-slot-id crash instead of a typed exception); security audit closed all 9 threats (`threats_open: 0`); Nyquist validation reported zero coverage gaps (139/139 tests green). The `v0.1.0` release tag (Task 2 of the final plan) was cut and pushed to `origin` only after an explicit human-verify checkpoint confirmed every prior gate was green — reconfirmed live against the tagged commit (`3fc81b2`) immediately before the one-way push. All 4 roadmap success criteria and all 3 mapped requirement IDs (PKG-01, PKG-02, PKG-03) verified. This is the milestone's final phase — v1.0 milestone execution is now complete.

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
| Pluggable async storage backend (protocol + in-memory + SQL impls) | Atomicity becomes a contract the backend satisfies; keeps the engine reusable and testable | Validated — Phase 1 shipped the Protocol + `InMemoryStore` |
| Fixed-duration slot grid in v1, interval math extensible to arbitrary windows | Simplest to reason about/query now; avoids a rewrite when continuous bookings are added later | Validated — Phase 1 shipped `grid_slots()` |
| v1 calendar scope = per-day hours + buffers + capacity>1; recurrence deferred | Covers the first consumer's real needs without the recurrence iceberg | Validated — Phase 1 `Resource` contract |
| TZ-aware, UTC-internal, per-resource IANA zone | Scheduling engines live or die on DST correctness; per-resource zones support co-located or distributed resources | Validated — Phase 1 UTC-boundary enforcement (both `place_hold` and `get_availability`); Phase 2 fixture-proved DST-transition + midnight-crossing correctness on real 2026 dates |
| One SQL impl spanning SQLite + Postgres, row-lock atomicity | Zero-infra local dev (SQLite) + prod (Postgres) from one codebase; matches a typical chatbot deploy | Validated — Phase 4 shipped `SQLStore` implementing all 7 `StorageBackend` Protocol methods against both dialects via one shared query-construction path |
| Lazy-on-read hold expiry (no background sweeper) | Deterministic and easy to test; a library shouldn't own a runtime lifecycle | Validated — Phase 2 collapsed the duplicated active-entries scan into one shared, expiry-filtering primitive (`get_active_entries`) used by every read and write path; Phase 3 extended the same primitive with a `BookingStatus.CANCELLED`-skip branch, still zero background processes |
| Contract-first build against a stubbed structured output | Lets the consumer chatbot progress in parallel; forces an early, stable contract | Validated — Phase 1 shipped `AvailabilityResult`/`Hold`/`Booking`; Phase 2 restructured to the two-list capacity-shape contract (D-04) and froze it behind a golden-file conformance test |
| Idempotency keys on hold/confirm in v1 | First consumer is network-facing (retries on timeout); without keys a retry double-spends capacity. Cheap now, contract-breaking to retrofit | Validated — Phase 3 shipped fingerprinted, lock-guarded replay + conflict detection on `InMemoryStore`, scoped per `(operation_type, key)`; a concurrent same-key race (`asyncio.gather`) is proven to serialize to one stored result, never double-spending capacity |
| Portable atomicity: `pg_advisory_xact_lock` (Postgres) / `BEGIN IMMEDIATE` (SQLite) — supersedes D-01's original bare `FOR UPDATE` design | Phase 4 research found `FOR UPDATE` cannot lock a row that does not yet exist, so it cannot prevent the phantom-insert race on an empty slot; a transaction-scoped advisory lock closes that gap on Postgres, `BEGIN IMMEDIATE` does the equivalent on SQLite (which has no row-level locking) | Validated — Phase 4 empirically proved this via real concurrent Postgres clients (K=1/N=25, K=3/N=30, exact success counts); Phases 1-3's `InMemoryStore` uses an `asyncio.Lock`-guarded critical section as the in-memory analog |
| Sweep-line event counting for capacity-aware availability | Binary interval subtraction only works for capacity 1; sweep-line handles capacity ≥ 1 from day one without a v2 rewrite | Validated — Phase 1 shipped `free_fragments()`; Phase 2 hardened it with a hypothesis property test proving `0 <= remaining <= capacity` and clamped `remaining` to 0 (rather than crashing) when a capacity reduction drops below the active-hold count (code review CR-02) |
| Closed `ReasonCode` enum + `AvailabilityEngineError` exception hierarchy | HOLD-08 requires every rejection to carry a machine-readable reason code the consumer can branch on | Validated — Phase 2 shipped `ReasonCode(StrEnum)` and rebased all domain exceptions onto it, with an exhaustiveness test; Phase 3 added `BookingNotFoundError`/`IdempotencyConflictError` onto the same closed enum (`NOT_FOUND`, pre-seeded `IDEMPOTENCY_CONFLICT`) without widening it |
| `cancel_booking` as a distinct, non-idempotent operation (never routed through `release_hold`) | `release_hold`'s pop-and-ignore no-op semantics are correct for holds but would silently mask a double-cancel or wrong-id call on a confirmed booking (D-04) | Validated — Phase 3 shipped `cancel_booking` raising `BookingNotFoundError` on unknown/already-cancelled/Hold-id inputs, never a silent no-op |
| Idempotency cache re-validates against live state on every replay, never trusts a frozen snapshot | A cached `Hold`/`Booking` can go stale after the first call succeeds (released, expired, confirmed, or cancelled by a later operation) — returning the frozen snapshot verbatim produces a phantom result | Validated — Phase 3 code review caught this (CR-01) before it shipped; fixed to re-check `self._holds`/`self._bookings` on every cache hit, with dedicated regression tests for replay-after-release/expiry/confirm/cancel |
| Release as `v0.1.0`, not `v1.0`, matching the consumer's already-committed pin seam | Cutting `v1.0` would orphan `SocialNetwork-Chatbot`'s one-line repin and overstate maturity for a first release | Validated — Phase 5 cut and pushed the `v0.1.0` annotated tag to `origin` only after a human-verify checkpoint confirmed the full suite (packaging smoke-install, sync facade, cross-repo conformance, doc-examples — 139/139 tests) was green |

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
*Last updated: 2026-09-05 after Phase 5 completion (v1.0 milestone execution complete)*
