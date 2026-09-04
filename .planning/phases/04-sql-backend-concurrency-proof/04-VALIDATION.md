---
phase: 4
slug: sql-backend-concurrency-proof
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-09-04
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio 1.4.0 (existing, pinned since Phase 1) |
| **Config file** | `pyproject.toml` (existing `[tool.pytest.ini_options]`) |
| **Quick run command** | `uv run pytest tests/storage/contract_suite.py -k "not postgres"` |
| **Full suite command** | `uv run pytest` (includes SQLite + Postgres-via-testcontainers parametrizations and the dedicated HOLD-02 concurrency test) |
| **Estimated runtime** | ~30-90s (Postgres testcontainers boot dominates; container is session-scoped) |

---

## Sampling Rate

- **After every task commit:** Run the quick command (excludes Postgres container boot for fast iteration)
- **After every plan wave:** Run the full suite command (SQLite + Postgres + concurrency proof)
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 90 seconds

---

## Per-Task Verification Map

*Filled in against the final task breakdown (Plans 04-01 through 04-04).*

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 04-01-T1 | 04-01 | 1 | STORE-03 | T-04-01, T-04-02 | SQLStore's place_hold satisfies capacity gating end-to-end on SQLite via a real SQL round-trip | integration | `uv run pytest tests/storage/test_sql_store.py -x` | ❌ W0 (created by this task) | ⬜ pending |
| 04-01-T2 | 04-01 | 1 | STORE-03, STORE-04 | T-04-02, T-04-03 | Full CRUD (confirm/release/cancel) proven via the shared contract suite for in-memory + sqlite | integration | `uv run pytest tests/storage/ -x && uv run mypy --strict src && uv run ruff check` | ❌ W0 (modifies existing contract_suite.py) | ⬜ pending |
| 04-02-T1 | 04-02 | 2 | STORE-03, STORE-04 | T-04-01, T-04-06 | Shared contract suite passes against real testcontainers Postgres | integration (real Postgres) | `uv run pytest tests/storage/contract_suite.py -k postgres -x` | ❌ W0 (new pg fixtures) | ⬜ pending |
| 04-02-T2 | 04-02 | 2 | STORE-03, STORE-04 | — | Three-way (in-memory/sqlite/postgres) regression green; dialect-specific JSON/DateTime/IntegrityError parity fixed | integration | `uv run pytest tests/storage/ -x && uv run mypy --strict src && uv run ruff check` | ✅ (extends 04-02-T1's fixtures) | ⬜ pending |
| 04-03-T1 | 04-03 | 2 | STORE-05 | T-04-05 | Alembic initial migration applies cleanly to a fresh SQLite file | integration | `uv run pytest tests/test_migrations.py -k sqlite -x` | ❌ W0 (new alembic/ scaffold) | ⬜ pending |
| 04-03-T2 | 04-03 | 2 | STORE-05 | T-04-05, T-04-06 | Alembic initial migration applies cleanly to a fresh throwaway Postgres | integration (real Postgres) | `uv run pytest tests/test_migrations.py -x` | ✅ (extends 04-03-T1's file) | ⬜ pending |
| 04-03-T3 | 04-03 | 2 | — (D-05) | — | aiosqlite query does not block the asyncio event loop | integration | `uv run pytest tests/test_aiosqlite_loop_responsiveness.py -x` | ❌ W0 (new file) | ⬜ pending |
| 04-04-T1 | 04-04 | 3 | HOLD-02 | T-04-01 | N genuinely concurrent OS-level `place_hold` calls against capacity-K never exceed K successes (K=1/N=25 and K=3/N=30) | integration (real Postgres, real concurrency) | `uv run pytest tests/storage/test_concurrency_proof.py -x` | ❌ W0 (new file) | ⬜ pending |
| 04-04-T2 | 04-04 | 3 | STORE-03, STORE-04, STORE-05, HOLD-02 | — | Full project-wide regression (all phases, all backends) — Phase 4 completion gate | integration | `uv run pytest && uv run mypy --strict src && uv run ruff check` | ✅ (whole suite) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/storage/test_sql_store.py` (or planner-chosen path) — stubs for STORE-03/STORE-04 SQLStore contract conformance
- [ ] `tests/storage/test_concurrency_proof.py` — stub for HOLD-02's dedicated real-connection concurrency test (must NOT reuse the rollback-isolated contract-suite fixture — RESEARCH.md's Common Pitfalls warns this defeats the proof)
- [ ] `tests/storage/conftest.py` additions (not root `tests/conftest.py` — storage-only fixtures live alongside `contract_suite.py`) — testcontainers-Postgres session-scoped fixture, SQLite WAL/busy_timeout/NullPool fixture, `backend_factory` indirect-parametrize fixture
- [ ] `alembic/` scaffold (`alembic init`, `env.py` wired to the SQLAlchemy Core metadata) — no framework currently installed for migrations

*Existing infrastructure (pytest, pytest-asyncio, the `backend_factory` parametrize seam in `contract_suite.py`) covers everything else.*

---

## Manual-Only Verifications

*If none: "All phase behaviors have automated verification."*

All phase behaviors have automated verification.

---

## Validation Sign-Off

> **Plan-time state is a DRAFT.** Leave frontmatter `status: draft` and `nyquist_compliant: false`.
> These are finalized ONLY post-execution by the Nyquist finalizer (the `verify:post` →
> `validate-phase` hook, invoked by execute-phase `finalize_nyquist_validation` after Gate-1). Never
> set `nyquist_compliant: true` — or otherwise "sign off" compliance — at plan time, and do not let
> the plan-checker do so (INC-2026-07-27-01: a premature plan-time flip is what caused inconsistent
> COMPLIANT/PARTIAL milestone-audit states).

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] _(finalizer-only, post-execution)_ `nyquist_compliant` — leave `false` at plan time; the
      finalizer sets `true` iff its gap analysis finds zero gaps

**Approval:** pending — finalizer-owned, not set at plan time
