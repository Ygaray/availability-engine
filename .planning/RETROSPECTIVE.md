# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v1.0 — v1 Release

**Shipped:** 2026-09-05
**Phases:** 5 | **Plans:** 17 | **Tasks:** 37

### What Was Built
- A domain-agnostic Python scheduling library: importable async `AvailabilityEngine` + a `SyncAvailabilityEngine` background-thread bridge over a coarse-grained async `StorageBackend` protocol.
- Two interchangeable backends behind one Protocol — `InMemoryStore` and a SQLite+Postgres `SQLStore` — proven swappable with `engine.py`/`contracts.py` byte-identical across the swap.
- Correctness core: capacity-aware sweep-line availability (capacity ≥1), DST/midnight-crossing correctness on real 2026 transition dates, lazy-on-read hold expiry, a closed `ReasonCode` enum, idempotency keys, and cancellation.
- A frozen, golden-file-tested two-list `available`/`booked` output contract; a real-Postgres no-overbook concurrency proof (K=1/N=25, K=3/N=30); Alembic migrations force-included in the wheel; and the `v0.1.0` git tag the first consumer (`SocialNetwork-Chatbot`) repins to, with a passing cross-repo conformance suite.

### What Worked
- **Contract-first, walking-skeleton-first sequencing.** Phase 1 stood up the whole facade over in-memory storage so later phases hardened correctness *underneath an already-working library* — the SQL backend swapped in (Phase 4) with zero facade change, exactly as designed.
- **Adversarial verification over trust.** Gate-1 self-UAT and phase verification independently re-probed critical code-review findings (e.g. CR-01 stale/phantom idempotency replay) against live source rather than accepting the fixer's word — catching a flaky regression test in Phase 4 before it shipped.
- **The parametrized storage contract suite** run identically across in-memory/SQLite/Postgres was the single highest-leverage artifact: it proved backend parity for free on every change.

### What Was Inefficient
- **The v1.0-vs-v0.1.0 version split** surfaced late (at milestone close) as a tagging ambiguity — GSD's internal milestone is "v1.0" but the shipped semver is `v0.1.0`. Worth stating the release version explicitly in the roadmap up front next milestone.
- **Cosmetic E501 lint findings were deferred three times** across Phase 4 tasks (correctly, as out-of-scope) but then required an explicit resolve pass at milestone close. A one-line `# noqa`/wrap at first sighting would have avoided the round trip.

### Patterns Established
- **Facade calls Protocol only; boundary guards live in the facade, never a concrete backend.** This is the load-bearing convention that makes backends swappable — preserve it.
- **Dialect-aware atomicity:** `pg_advisory_xact_lock` (Postgres) / `BEGIN IMMEDIATE` (SQLite), auto-attached on construction — supersedes bare `FOR UPDATE`, which can't lock a not-yet-existing row.
- **Deferred-items ledger** (`deferred-items.md`) with per-entry `status: resolved` is the clean way to close out out-of-scope discoveries at milestone close without rewriting execution history.

### Key Lessons
1. Decide and record the **actual release version** (semver git tag) separately from GSD's milestone label at roadmap time — they are not the same thing, and consumers pin by the git tag.
2. **Fix cosmetic lint at first sighting** even when out of task scope, or it compounds into a close-time resolve pass.
3. A **parametrized cross-backend contract suite** pays for itself many times over in a pluggable-backend design — build it in the walking skeleton, not the backend phase.

### Cost Observations
- Model mix: predominantly Opus (planning/verification/orchestration) with Sonnet-class executors under the `adaptive` model profile.
- Notable: heavy use of isolated git worktrees for wave-parallel plan execution; cross-phase integration verified once at close via a single `gsd-integration-checker` pass (INTEGRATION_CLEAN).

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Plans | Key Change |
|-----------|--------|-------|------------|
| v1.0 | 5 | 17 | First milestone — established contract-first walking-skeleton sequencing and the parametrized cross-backend contract suite |

### Cumulative Quality

| Milestone | Tests | Requirements | Zero-Dep Additions |
|-----------|-------|--------------|-------------------|
| v1.0 | 139 core + 13 conformance | 29/29 validated | Hand-rolled `Interval` type (no `portion` dep in v1) |

### Top Lessons (Verified Across Milestones)

1. *(Pending a second milestone to cross-validate.)*
