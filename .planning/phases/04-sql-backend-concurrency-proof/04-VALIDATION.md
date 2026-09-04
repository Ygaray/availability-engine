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

*Filled in by the planner against the final task breakdown — placeholders below anchor the plan-checker's Dimension 8 review to the phase's four requirements until PLAN.md exists.*

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | TBD | TBD | STORE-03 | — | SQLStore satisfies StorageBackend against both dialects | integration | `uv run pytest tests/storage/contract_suite.py` | ✅ / ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | STORE-04 | — | Parametrized contract suite passes unmodified across InMemory/SQLite/Postgres | integration | `uv run pytest tests/storage/contract_suite.py` | ✅ / ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | STORE-05 | — | Alembic initial migration applies cleanly to both SQLite and Postgres | integration | `uv run alembic upgrade head` (both dialects) | ✅ / ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | HOLD-02 | T-04-01 | N concurrent OS-level `place_hold` calls against capacity-K never exceed K successes | integration (real Postgres, real concurrency) | `uv run pytest tests/storage/test_concurrency_proof.py` | ✅ / ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/storage/test_sql_store.py` (or planner-chosen path) — stubs for STORE-03/STORE-04 SQLStore contract conformance
- [ ] `tests/storage/test_concurrency_proof.py` — stub for HOLD-02's dedicated real-connection concurrency test (must NOT reuse the rollback-isolated contract-suite fixture — RESEARCH.md's Common Pitfalls warns this defeats the proof)
- [ ] `tests/conftest.py` additions — testcontainers-Postgres session-scoped fixture, SQLite WAL/busy_timeout/NullPool fixture
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
