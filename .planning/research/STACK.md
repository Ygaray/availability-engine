# Stack Research

**Domain:** Domain-agnostic Python scheduling/availability library (resources × time-slots × holds), consumed via git-tag pin
**Researched:** 2026-09-02
**Confidence:** MEDIUM (versions and library-status claims via web search — cross-check exact pinned versions against PyPI at implementation time; architectural rationale is HIGH confidence, grounded in documented SQLite/Postgres locking semantics)

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Python | 3.12+ (locked) | Runtime | Already decided. `zoneinfo` (3.9+), modern typing (`Self`, generics), and `tomllib` are all available; no version-driven blockers for this stack. |
| stdlib `datetime` + `zoneinfo` | stdlib | TZ-aware datetime type, UTC-internal representation, per-resource IANA operating hours | This is a **library**, not an app — every consumer's app boundary must interoperate with plain `datetime` objects, SQLAlchemy's `DateTime(timezone=True)` columns, and JSON. Adding a third-party datetime type (pendulum/whenever) at the public contract would force every consumer to adopt it too, violating the domain-agnostic/zero-friction-integration goal. Do the internal engine math in aware stdlib `datetime` (always UTC), resolve per-resource IANA zones via `zoneinfo.ZoneInfo` only at the operating-hours→UTC-slot-grid boundary. |
| SQLAlchemy | 2.0.x (latest stable, currently 2.0.5x line) — pin `>=2.0,<2.1` | Async Core/ORM spanning SQLite + Postgres from one codebase, with a dialect-aware locking strategy | Only actively-maintained option that gives one query-building layer over both `sqlite+aiosqlite` and `postgresql+asyncpg` async dialects. See "Row-lock atomicity" pattern below — this is the crux of the hard constraint and needs explicit handling, not just "SQLAlchemy handles it." |
| asyncpg | 0.31.x+ | Async Postgres driver (SQLAlchemy dialect: `postgresql+asyncpg`) | Fastest, most actively maintained async Postgres driver in the ecosystem; the de facto standard under SQLAlchemy async for Postgres. |
| aiosqlite | 0.22.x+ | Async SQLite driver (SQLAlchemy dialect: `sqlite+aiosqlite`) | Only viable async SQLite driver; thin asyncio wrapper around stdlib `sqlite3` via a background thread. Actively maintained (0.22.1, Dec 2025). |
| Pydantic | v2, 2.x latest (2.13.x line) | Validation + serialization for the **public contract** types only (availability query outputs, and any type the consumer's untrusted input flows through, e.g. hold-request payloads) | v2's Rust core gives fast JSON schema + serialization for the structured output contract this library exists to publish. Reserve it for the trust/serialization boundary — see rationale below on why NOT to use it for every internal value object. |
| `dataclasses` (stdlib, `frozen=True, slots=True`) | stdlib | Internal value objects: `Slot`, internal `Hold` state, interval endpoints, anything constructed only by the engine itself (never raw external input) | 2–3x faster to instantiate than Pydantic v2 models and substantially lower memory (Pydantic's own validation machinery is dead weight once inputs are already engine-internal and type-correct by construction). `slots=True` removes the per-instance `__dict__`, which matters when generating a full slot grid (potentially thousands of `Slot` objects per resource per day). |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| A hand-rolled `Interval` type (half-open `[start, end)`, frozen dataclass) | n/a — write ~50 lines | Core interval math: overlap, containment, adjacency, grid generation | v1 is a fixed-duration grid. A hand-rolled type keeps the public/internal interval representation exactly as simple as v1 needs, has zero dependency-version risk on the public contract, and is trivial to extend later (see `portion` below) without a rewrite — the constraint explicitly asks for "interval math designed to extend to arbitrary/continuous windows later," which a minimal half-open type satisfies without pulling in a full algebra library prematurely. |
| `portion` (formerly `python-intervals`) | 2.6.x | Interval-set algebra (union/intersection/complement/difference over sets of intervals) | **Defer to the milestone that adds arbitrary/continuous-duration bookings.** `portion` is the actively maintained successor to `python-intervals` (which stopped receiving updates and now points users to `portion`). It's the right tool once you need to compute "free time = operating hours minus the union of all booked intervals" over continuous windows rather than a fixed grid. Do not adopt it in v1 — it would be solving a problem the grid model doesn't have yet. |
| SQLAlchemy `Table`/Core (not full ORM) | via SQLAlchemy 2.0 | Schema definition + queries for the SQL storage impl | Prefer Core (`Table`, `select()`, `insert()`, explicit transactions) over the ORM's unit-of-work/`Session` identity map for this use case: the storage layer is a thin protocol implementation around explicit, short atomic transactions (hold placement, confirm, release) — ORM session/identity-map semantics add complexity (detached instances, flush ordering) without benefit when every operation is already a hand-written, tightly-scoped SQL statement. |
| `Protocol` (stdlib `typing`) + `abc.ABC` | stdlib | Define the async storage backend contract | Matches the locked "storage protocol" decision. `typing.Protocol` gives structural typing (consumers/backends don't need to inherit from a base class) which fits a pluggable-backend design; use it for the interface, with an internal `ABC` only if shared default method bodies are needed. |
| `pytest-asyncio` | 0.24.x+ (compatible with pytest 8.x) | Run async test functions/fixtures | The storage protocol and public API are async-only (asyncio, not Trio/multi-backend) — `pytest-asyncio`'s single-purpose, minimal design is the right scope. Do not add AnyIO's plugin unless Trio support becomes an actual requirement (see rejected alternatives). |
| `time-machine` | 2.16.x+ | Time mocking for hold-expiry (TTL) and DST-boundary tests | ~100–200x faster than `freezegun` (C-layer libc patching vs. scanning every imported reference) and equally precise. Lazy-on-read expiry logic and DST edge cases will be tested heavily — this matters at scale. |
| `hypothesis` | 6.x latest | Property-based tests for interval math and grid generation | No off-the-shelf "interval strategy" exists, but composing `st.datetimes(timezones=...)` + custom strategies to generate random `(resource, hours, slot_length, buffer, existing_bookings)` tuples and asserting invariants (no overlap, no negative duration, capacity never exceeded, grid alignment holds across DST transitions) is exactly the failure class that hand-written examples under-cover. High-value given how safety-critical "atomic, no double-booking" is stated to be. |
| `testcontainers[postgres]` (`testcontainers-python`) | 4.x latest | Spin up a real Postgres in CI/integration tests | SQLite cannot validate the Postgres `SELECT ... FOR UPDATE` row-lock path at all (SQLite has no row-level locks — see below). The one-SQL-impl design is only actually verified against Postgres via a real Postgres instance; `testcontainers` gives that without a shared external DB dependency. Use a session-scoped container fixture + per-test schema reset or transaction rollback for isolation. |
| `ruff` | 0.9.x+ latest | Lint + format (single tool) | Standard 2025 replacement for `flake8` + `black` + `isort`; one dependency, one config block, sub-second runs. |
| `mypy` | 1.13.x+ latest, `--strict` | Static typing for the public API surface | A library's public contract lives and dies by its type signatures being trustworthy for consumers doing `uv add --pin`. `--strict` (or close to it) on `src/` catches contract drift before it reaches a consumer. `pyright` is an equally valid alternative (see below) — pick one, don't run both. |
| `pre-commit` | 4.x latest | Enforce ruff + mypy at commit time | Standard hygiene gate; `astral-sh/ruff-pre-commit` + `pre-commit/mirrors-mypy` is the current canonical hook set. |
| `hatchling` | latest (locked already) | Build backend | Already decided in constraints — no change. |

## Installation

```bash
# Core runtime deps
uv add sqlalchemy pydantic

# Backend drivers (both installed — the one SQL impl targets both)
uv add asyncpg aiosqlite

# Dev / test dependencies
uv add --dev pytest pytest-asyncio pytest-cov time-machine hypothesis "testcontainers[postgres]"

# Lint / type / format
uv add --dev ruff mypy pre-commit
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|--------------------------|
| stdlib `datetime` + `zoneinfo` | `pendulum` | If this were an application (not a library) with full control over every datetime touchpoint, pendulum's stricter naive/aware handling and nicer arithmetic API would be a reasonable app-level convenience. As a library, imposing a third-party datetime type on every consumer's boundary is a needless coupling cost. |
| stdlib `datetime` + `zoneinfo` | `whenever` | `whenever` has the strongest correctness guarantees (typed aware/naive split, DST-safe, Rust-backed speed) of any option researched — genuinely the most "correct" choice technically. Rejected for v1 because it is pre-1.0 (0.x version line) with a small ecosystem footprint; adopting a pre-1.0 dependency as the datetime backbone of a library other teams pin by git-tag is a stability risk not worth taking yet. Revisit once it reaches 1.0 and gets broader adoption — it may be the right call for a v2 rewrite of the interval layer if `whenever` proves out. |
| stdlib `datetime` + `zoneinfo` | `arrow` | Rejected outright — not DST-safe, documented erratic parsing/comparison behavior. No scenario in this project favors it. |
| Hand-rolled `Interval` type (v1) | `portion` (v1) | Once continuous/arbitrary-duration bookings are added (explicitly deferred), `portion`'s interval-set algebra (union/complement/difference) becomes the right tool — don't hand-roll set operations at that point. |
| SQLAlchemy 2.x async | `encode/databases` | Never — see "What NOT to Use." |
| SQLAlchemy 2.x async | raw `asyncpg`/`aiosqlite` (no query builder) | If the storage layer only ever needed to target Postgres, raw `asyncpg` would be lighter and faster. Rejected because the constraint requires ONE implementation spanning two different SQL dialects/lock models — SQLAlchemy Core's dialect abstraction (query compilation, parameter binding, `with_for_update()` dialect-awareness) is exactly what removes hand-written dialect branching from every query, not just the lock acquisition. |
| Pydantic v2 (contract only) | Pydantic v2 (everywhere, including internal value objects) | If the internal object count stays small and instantiation is never in a hot loop (e.g., a handful of `Hold`/`Booking` objects per request), the performance gap is irrelevant and using Pydantic everywhere reduces the number of type systems in the codebase. Given grid generation can produce many `Slot` objects per query, this project should keep the split. |
| `pytest-asyncio` | AnyIO pytest plugin | If a future requirement needs the engine or its test suite to run under Trio (or if the codebase already depends on AnyIO for other reasons), switch — AnyIO's plugin is a superset and would remove the extra dependency. Not justified today. |
| `mypy --strict` | `pyright` | `pyright` is faster and has arguably better inference in some cases, and is a fine substitute — pick either, but standardize on one. Slight edge to `mypy` here only because it's the default paired with `pre-commit/mirrors-mypy` and has marginally wider adoption in pure-library (non-editor-tooling) contexts; this is a low-stakes choice. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|--------------|
| `encode/databases` | Archived (read-only) by its maintainer on 2025-08-19; classified Inactive with no releases in 12+ months. Adopting an archived dependency as the async SQL layer of a new library is a non-starter. | SQLAlchemy 2.x async (`AsyncEngine`/`AsyncSession` or Core) |
| Naive `datetime` objects anywhere in the engine or storage layer | The single most common scheduling-engine bug class: silent UTC/local mixing, comparison `TypeError`s at odd times, DST double-counted or skipped hours. Directly violates the locked "UTC-internal, TZ-aware" constraint. | Always construct/compare `datetime` objects with `tzinfo` set (UTC internally; `zoneinfo.ZoneInfo(resource.timezone)` only at the operating-hours boundary) |
| Relying on `with_for_update()` alone to get atomicity on SQLite | **SQLite has no row-level locking at all** — it locks at the whole-database-file level (SHARED/RESERVED/EXCLUSIVE), and `SELECT ... FOR UPDATE` is silently a no-op/unsupported on SQLite. If the SQL impl only issues `with_for_update()` and assumes it "just works" on both backends, the SQLite path has **zero** actual concurrency protection at the row level. | Use a dialect-aware strategy: on Postgres, `with_for_update()` (or `nowait=True`/`skip_locked=True` per the hold-atomicity semantics needed); on SQLite, open the write transaction with `BEGIN IMMEDIATE` (acquires the RESERVED/write lock upfront on the whole DB) so all hold-placement/confirm/release transactions are serialized against each other — for a single-file SQLite DB this achieves equivalent atomicity to row-level locking, since there is effectively one writer at a time anyway. This needs an explicit `if dialect == "sqlite": connection.execute(text("BEGIN IMMEDIATE"))` / SQLAlchemy event-listener branch in the storage impl — it will not happen "for free." |
| A full ORM Session/identity-map usage pattern for the storage backend | Adds flush-ordering, detached-instance, and identity-map complexity to what should be small, explicit, auditable atomic transactions (place-hold, confirm, release) — the exact code paths where correctness under concurrency matters most and where implicit ORM behavior is the last thing you want. | SQLAlchemy Core (`Table`, `select()`, explicit `async with engine.begin()`) |
| `freezegun` as the primary time-mocking tool | 100–200x slower than `time-machine` because it monkeypatches every module-level reference to time/date objects at import-scan time, cost scaling with codebase size — this project's test suite will need heavy time manipulation (TTL expiry, DST boundaries, multi-timezone resources). | `time-machine` |
| `python-intervals` (the old PyPI name) | Explicitly deprecated/renamed by its own maintainer — "won't be updated anymore," points users to its successor. | `portion` (same author, actively maintained, when/if interval-set algebra is needed) |
| Background sweeper thread/task for hold expiry | Explicitly out of scope per the locked "lazy-on-read" decision — a library should not own a runtime lifecycle (a background task needs a host event loop, a shutdown hook, error handling for a process the library doesn't control). | Check-and-lazily-expire on every read path that touches a hold (already the locked design) |

## Stack Patterns by Variant

**If a future milestone adds arbitrary/continuous-duration bookings (already flagged as intentionally deferred):**
- Swap the hand-rolled `Interval` type's internals to delegate to (or be replaced by) `portion.Interval`/`portion.IntervalDict` for the free/busy computation.
- Because the v1 half-open interval type should already have the same overlap/containment semantics `portion` uses — if it does, swapping the implementation is contained to the interval module, not the whole engine.

**If SocialNetwork-Chatbot (or any consumer) needs sync (non-async) access:**
- Do not add a sync storage protocol variant. Provide a documented pattern for the consumer to call the async engine via `asyncio.run()` / an existing event loop at their boundary. Keeping the protocol async-only avoids doubling the storage implementation surface (the locked decision already specifies async).

**If Postgres-only deployments become the norm and SQLite dev/test parity stops mattering:**
- Reconsider whether the `BEGIN IMMEDIATE` SQLite branch is still worth maintaining vs. dropping SQLite support entirely — but this is explicitly against the current locked constraint ("targeting BOTH SQLite and Postgres"), so out of scope unless that constraint changes.

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|------------------|-------|
| `sqlalchemy>=2.0,<2.1` | `python>=3.12` | SQLAlchemy 2.1 is in RC as of this research (mid-2026) with API changes (e.g., new async patterns); pin to the 2.0 line for stability, revisit 2.1 once it's GA and its migration notes are reviewed. |
| `sqlalchemy` async | `asyncpg` (postgres) + `aiosqlite` (sqlite) | Both drivers are SQLAlchemy's officially documented async dialect targets — no compatibility surprises expected at the versions above. |
| `pydantic>=2.0` | `python>=3.12` | No known conflicts; v2's Rust core (`pydantic-core`) ships prebuilt wheels for 3.12/3.13. |
| `hypothesis` | `pytest-asyncio` | Hypothesis's async support needs `pytest.mark.asyncio` (or the `hypothesis[pytest-asyncio]` extra pattern) when testing async functions directly — verify current Hypothesis docs for the exact async-strategy integration at implementation time, since this is an area that has shifted across Hypothesis versions. |
| `testcontainers[postgres]` | Docker (or Podman) available in CI/dev environment | Requires a running container runtime; ensure CI runners and local dev machines both have Docker available before adopting — this is an environmental dependency, not just a pip package. |

## Sources

- WebSearch: "Python zoneinfo vs pendulum vs arrow vs whenever" — whenever GitHub (ariebovenberg/whenever), comparison articles — MEDIUM confidence (cross-referenced across multiple independent sources agreeing on DST-safety ranking)
- WebSearch: "python-intervals portion library" — AlexandreDecan/portion GitHub, PyPI — MEDIUM confidence (GitHub README + PyPI listing agree python-intervals → portion migration)
- WebSearch: "SQLAlchemy 2.0 async SELECT FOR UPDATE SQLite Postgres" — SQLAlchemy GitHub issues, community threads — MEDIUM confidence on the core fact (SQLite lacks FOR UPDATE support is well-established, longstanding SQLite documentation fact); LOW confidence on exact current SQLAlchemy patch version, verify at implementation time
- WebSearch: "SQLite BEGIN IMMEDIATE vs SELECT FOR UPDATE" — sqlite.org forum, official SQLite locking docs (sqlite.org/lockingv3.html) — HIGH confidence, this is documented SQLite core behavior, not a third-party claim
- WebSearch: "encode/databases maintenance status" — GitHub repo (archived 2025-08-19), Snyk package health — HIGH confidence, directly observable repo state
- WebSearch: "pydantic v2 vs attrs vs dataclasses slots performance" — multiple independent benchmark articles — MEDIUM confidence (magnitude of overhead is consistent across sources; exact percentages vary by benchmark methodology)
- WebSearch: "pytest-asyncio vs anyio" — AnyIO official docs (anyio.readthedocs.io) — HIGH confidence, official documentation
- WebSearch: "time-machine vs freezegun benchmark" — time-machine official docs comparison page, Adam Johnson's published benchmark — HIGH confidence, includes a named, reproducible benchmark
- WebSearch: current version lookups (SQLAlchemy, pydantic, asyncpg, aiosqlite, portion) — PyPI listings, official release blogs — MEDIUM confidence; **re-verify exact pinned versions against PyPI immediately before writing `pyproject.toml`**, as web search snapshots can lag or reflect dates beyond this research's actual cutoff

---
*Stack research for: Python domain-agnostic scheduling/availability library*
*Researched: 2026-09-02*
