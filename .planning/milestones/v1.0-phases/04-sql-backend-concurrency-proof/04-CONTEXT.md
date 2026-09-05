# Phase 4: SQL Backend & Concurrency Proof - Context

**Gathered:** 2026-09-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Ship one SQL storage implementation spanning SQLite + Postgres, mirroring the in-memory model built in Phases 1–3, and prove no-double-booking under genuinely concurrent bookers.

</domain>

<decisions>
## Implementation Decisions

### Locking & Atomicity
- **D-01 [for-update]:** Defer `SELECT ... FOR UPDATE` on Postgres; rely on the single `INSERT ... SELECT ... WHERE (COUNT < capacity)` conditional-write statement (with a `rowcount` check) for correctness — it is already atomic and sufficient. Treat `FOR UPDATE` as a later, optional contention tune. _(source: ai-auto)_
- **D-05 [aiosqlite-safety]:** Treat aiosqlite as confirmed loop-responsive (per-connection background thread makes calls awaitable; writes serialize under SQLite's single-writer but the loop yields) — and verify it with an explicit interleave/yield-point timing test at the pinned aiosqlite version (0.22.x), asserting loop responsiveness rather than parallel write throughput. Do not assume "async API" = "doesn't block." _(source: ai-auto)_

### Schema
- **D-02 [schema]:** A single physical table keyed by a `status` column (`active`/`confirmed`/`released`/`cancelled`) — confirm/cancel are in-place `UPDATE`s and capacity `COUNT` is one predicate — with an idempotency-key unique constraint, a JSON/JSONB opaque-payload column, and a `(resource_id, slot_start, status)` index. _(source: ai-auto)_ _(provisional — refresh at execution; depends on Phase 3)_ — **Reversibility:** one-way — must mirror the in-memory representation Phases 1–3 build; re-validate once that code lands, and a shipped schema needs a migration to change.

### Migrations
- **D-03 [migrations]:** Alembic from the first SQL commit (initial migration = current schema, even if trivial), consumer-run rather than startup auto-applied (auto-apply takes a coarse write lock and violates "library owns no runtime lifecycle"); pin an Alembic version and author the proof migration in `batch_alter_table` mode for SQLite parity. _(source: ai-auto)_

### Concurrency Proof
- **D-04 [concurrency-proof]:** A testcontainers-Postgres proof under `READ COMMITTED` asserting at most K of N genuinely-concurrent OS-level `place_hold`s succeed against a capacity-K resource (session-scoped container + per-test rollback), with the same parametrized contract suite run unmodified against InMemory/SQLite/Postgres; SQLite configured WAL + `busy_timeout ~5000ms` + a single serialized connection (`NullPool`/`pool_size=1`). _(source: ai-auto)_

### Claude's Discretion
Exact SQLAlchemy Core query construction and connection-pool wiring are open provided the atomicity and dialect-parity behavior above holds.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Milestone decisions
- `.planning/v1.0-DECISION-MAP.md` §Phase 4 — the resolved gray areas above (for-update, schema, migrations, aiosqlite-safety, concurrency-proof)
- `.planning/APPROVED-DEPS.md` — pre-approved packages for this phase (sqlalchemy, asyncpg, aiosqlite, alembic, testcontainers)

### Upstream model (must mirror)
- `.planning/phases/03-idempotency-cancellation/03-CONTEXT.md` — the status model (`active`/`confirmed`/`released`/`cancelled`), shared active-entries predicate, and idempotency uniqueness the SQL schema must mirror; `schema` is provisional pending this.
- `.planning/phases/02-capacity-time-correctness/02-CONTEXT.md` — capacity split + sweep semantics the SQL `COUNT` predicate reproduces.
- `.planning/phases/01-end-to-end-walking-skeleton-in-memory/01-CONTEXT.md` — the `StorageBackend` Protocol the SQL impl satisfies.

### Project scope & stack
- `.planning/ROADMAP.md` — Phase 4 scope and success criteria
- `.planning/REQUIREMENTS.md` — concurrency / no-double-booking requirement
- `.claude/CLAUDE.md` — "Row-lock atomicity" pattern: dialect-aware `BEGIN IMMEDIATE` (SQLite) vs Postgres locking; SQLite has no row-level locking; `testcontainers` needs a container runtime in CI.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- The parametrized contract suite from Phases 1–3 runs unmodified against InMemory/SQLite/Postgres — the one-suite/many-backends guarantee. Surfaced at plan time.

### Established Patterns
- Prefer SQLAlchemy Core (`Table`, `select()`, explicit `async with engine.begin()`) over the ORM Session/identity-map for small, explicit atomic transactions (CLAUDE.md).
- Dialect-aware write-lock: `BEGIN IMMEDIATE` on SQLite (whole-DB RESERVED lock) since `FOR UPDATE` is a no-op there.

### Integration Points
- Migrations must be packaged into the wheel for a git-tag-pinned consumer to bootstrap a schema → Phase 5 (`packaging`).

</code_context>

<specifics>
## Specific Ideas

The concurrency proof must use genuinely concurrent OS-level connections (testcontainers-Postgres) — an in-process/asyncio-only proof hides the race and is rejected.

</specifics>

<deferred>
## Deferred Ideas

- `FOR UPDATE` as a contention optimization — deferred as an optional later tune.
- SQL idempotency retention/cleanup reaper — noted from Phase 3; keep minimal for v1.
- Wheel packaging of the Alembic migrations → Phase 5 (`packaging`).

</deferred>

---

## Runtime Decisions

*Refreshed at milestone-execution time from real Phase 1–3 output (provisional → resolved, source: ai-auto).*

- **Schema (was provisional, depends-on Phase 3 — now resolved):** Use **separate `holds` and `bookings` tables**, mirroring the landed in-memory `_holds`/`_bookings` split. They are structurally different: a `Hold` carries `expires_at` (lazy expiry, no TTL eviction — IN-01); a `Booking` carries a `status` column (ACTIVE/CANCELLED) and a JSONB opaque-`payload` column. A confirmed hold is **deleted** and a booking is inserted with the **same id**. A distinct **idempotency table** keyed by `(operation_type, idempotency_key)` stores the fingerprint + a reference to the result row, and needs an explicit retention/cleanup policy (an unbounded idempotency table has real operational cost in SQL). Add a `(resource_id, slot_start, status)`-equivalent index per table for the active-entries scan. Row-lock atomicity is dialect-aware: Postgres `SELECT … FOR UPDATE`, SQLite `BEGIN IMMEDIATE`. **This supersedes the earlier provisional "single physical table keyed by `status`" guess** — the Phase 1–3 code that has now landed uses separate collections, and the provisional resolution explicitly required mirroring that representation once it landed.

---

*Phase: 4-SQL Backend & Concurrency Proof*
*Context gathered: 2026-09-03*
