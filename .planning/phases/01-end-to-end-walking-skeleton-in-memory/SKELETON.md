# Walking Skeleton — availability-engine

**Phase:** 1
**Generated:** 2026-09-03

## Capability Proven End-to-End

> A developer can `import AvailabilityEngine`, construct it over `InMemoryStore`, `define_resource()` a `Resource` (capacity, per-weekday hours, buffer, IANA timezone, slot length), call `get_availability()` to get a real structured slot grid, `place_hold()` a slot, `confirm_hold()` it into a `Booking` whose opaque payload round-trips untouched, and `release_hold()` — every hop real, none of it stubbed.

## Architectural Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Runtime & packaging | Python 3.12+, `uv` + `hatchling`, `src/` layout (`src/availability_engine/`) | Locked in `.claude/CLAUDE.md` — matches the reusable-ecosystem git-tag-pin convention |
| Boundary vs. internal types | Pydantic v2 (`contracts.py`) for every public input/output type; `@dataclass(frozen=True, slots=True)` for engine-internal value objects (`core/intervals.py::Interval`) | D-01 (locked, one-way) — gives the parallel booking-chatbot consumer an exportable JSON schema to stub against, while grid generation avoids Pydantic validation overhead in a hot loop |
| Time model | UTC-internal everywhere; `zoneinfo` imported only in `time.py` | Locked project constraint + GRID-04 — `Annotated[AwareDatetime, AfterValidator(_require_utc)]` rejects naive/non-UTC input at every boundary field |
| Storage protocol | `typing.Protocol` + `@runtime_checkable` async `StorageBackend`, six coarse-grained atomic methods | D-04 (locked, costly) — structural typing lets Phase 4's SQL backend satisfy the interface without inheriting from anything |
| Reference backend | `InMemoryStore` — single `asyncio.Lock` guarding dict-of-`contracts`-typed state | STORE-02 — the hold-placement check-and-write happens inside one lock with no intervening `await`, closing the TOCTOU window even though asyncio is single-threaded |
| Resource contract | `id`, `capacity`, `operating_hours` (per-weekday list of half-open local intervals, D-03), `buffer`, `timezone`, and `slot_duration` | MODEL-01..05, D-03 (locked, one-way). **Design note:** RESEARCH.md's `Resource` code sample omits `slot_duration`; this phase adds it as a required field because GRID-01 needs "slot length" as an input and the frozen `get_availability(resource_id, start, end)` facade signature (D-04) takes no such parameter — slot length has to live on the Resource itself, alongside the already-declared `operating_hours`/`buffer` fields. This is authoring the Resource contract for the first time (no consumer has pinned to it yet), not changing an already-published shape. |
| Tooling | `ruff` + `mypy --strict` enforced on `src/` from commit 1 | D-05 (locked) — catches contract drift and naive-datetime leaks before they accumulate across four more phases |

## Stack Touched in Phase 1

- [x] Project scaffold — `pyproject.toml` (`uv` + `hatchling`), `ruff`, `mypy --strict`, `pytest` + `pytest-asyncio` (`asyncio_mode = "auto"`)
- [x] Routing — N/A (library, not a web app); the equivalent "real entry point" is the five async `AvailabilityEngine` facade methods, called directly by the integration test
- [x] Database — N/A (no external DB in Phase 1); one real read (`get_availability` → `storage.get_resource` + `storage.get_active_entries`) AND one real write (`place_hold`/`confirm_hold`/`release_hold` → `storage.*`) against `InMemoryStore`
- [x] UI — N/A (library, no UI); the "interactive element" is the consumer's own async call, proven by `tests/test_engine.py::test_get_availability_end_to_end`
- [x] Deployment — N/A (library, not deployed); documented local full-stack run command: `uv run pytest tests/ -x -q`

## Out of Scope (Deferred to Later Slices)

- Capacity-K sweep-line correctness proof / property-based edge-case tests (Phase 2, AVAIL-02)
- Correct DST-transition and midnight-crossing grid generation (Phase 2, GRID-02/GRID-03) — Phase 1's `time.py` does a straightforward same-day local→UTC conversion only
- Lazy expiry as the one shared active-entries primitive used by every read (Phase 2, AVAIL-03/HOLD-05) — Phase 1 only checks expiry at `confirm_hold` time
- Machine-readable reason codes / closed enum (Phase 2, HOLD-08)
- Frozen, documented, conformance-tested output contract (Phase 2, AVAIL-04)
- Idempotency keys (Phase 3, HOLD-07) and booking cancellation (Phase 3, HOLD-06)
- Real SQL backend — SQLite + Postgres, concurrency proof (Phase 4)
- Packaging, docs, v1 git tag (Phase 5)

## Subsequent Slice Plan

Each later phase adds one vertical slice on top of this skeleton without altering its architectural decisions:

- Phase 2: Capacity & Time Correctness — capacity-aware sweep-line hardening, DST/midnight-crossing fixtures, lazy expiry, reason codes, frozen+documented contract
- Phase 3: Idempotency & Cancellation — retry-safe hold/confirm via idempotency keys, booking cancellation
- Phase 4: SQL Backend & Concurrency Proof — SQLite+Postgres backend swap-in, testcontainers-Postgres overbooking proof
- Phase 5: Packaging, Docs & v1 Release — `uv`+`hatchling` packaging, public API docs, example integration, v1 git tag
