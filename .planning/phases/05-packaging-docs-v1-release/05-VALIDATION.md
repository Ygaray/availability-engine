---
phase: 5
slug: packaging-docs-v1-release
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-09-04
finalized: 2026-09-05
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"`) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `uv run pytest tests/packaging/ tests/test_sync_facade.py -x` |
| **Full suite command** | `uv run pytest` |
| **Estimated runtime** | ~30 seconds (full suite, incl. wheel-build/install subprocess tests + 2 real testcontainers Postgres instances) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/packaging/ tests/test_sync_facade.py -x`
- **After every plan wave:** Run `uv run pytest` (full suite, including cross-repo conformance suite)
- **Before `/gsd-verify-work`:** Full suite must be green, INCLUDING the wheel-smoke-install test and the conformance suite, BEFORE tagging `v0.1.0` (tag immutability makes this non-negotiable)
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 05-01-XX | 01 | 0 | PKG-01 | — | Wheel namelist contains `py.typed` and the force-included migration tree | integration | `uv run pytest tests/packaging/test_wheel_contains_migrations.py -x` | ✅ | ✅ green |
| 05-01-XX | 01 | 0 | PKG-01 | T-05-08 | Wheel installs via git-tag pin, migrations bootstrap from the installed wheel, against **both** target backends (SQLite + Postgres) | integration | `uv run pytest tests/packaging/test_bootstrap_installed_wheel.py -x` | ✅ | ✅ green |
| 05-01-XX | 01 | 1 | PKG-01 | T-05-01, T-05-03, T-05-04 | Sync facade safe to call from inside an already-running event loop; fails fast (not hangs) after `close()`; `close()` raises `RuntimeError` on a genuine slow-shutdown join timeout; loop actually closed after join; no leaked payload in exceptions/logs | unit/integration | `uv run pytest tests/test_sync_facade.py -x` | ✅ | ✅ green |
| 05-01-XX | 01 | 1 | PKG-02 | — | `AvailabilityResult` JSON schema still matches the committed golden file (doc-example regression guard) | unit (existing) | `uv run pytest tests/test_contract_conformance.py -x` | ✅ (Phase 2) | ✅ green |
| 05-01-XX | 01 | 2 | PKG-03 | T-05-02, T-05-05, T-05-06 | Example adapter satisfies the consumer's full `AvailabilityContractSuite` at every tested capacity (incl. capacity>1 idempotency-after-confirm, CR-01), rejects malformed `slot_id` with a typed exception (UF-1), guards shared bookkeeping under concurrency (WR-02); uuid4-only id generation preserved | integration (dev-only, cross-repo) | `uv run --group conformance pytest tests/integration/test_chatbot_conformance.py -x` | ✅ | ✅ green |
| 05-04-XX | 04 | — | PKG-02 | T-05-07 | Every README code example is literally copy-paste-runnable and matches the tested/regression-guarded behavior | unit | `uv run pytest tests/test_readme_examples.py -x` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `tests/packaging/test_wheel_contains_migrations.py` — covers PKG-01 (wheel namelist inspection)
- [x] `tests/packaging/test_bootstrap_installed_wheel.py` — covers PKG-01 (build+venv+install+migrate subprocess integration test, **now against both SQLite and Postgres** — see Validation Audit below)
- [x] `tests/test_sync_facade.py` — covers PKG-01/D-04 (includes the loop-in-loop test, post-close fail-fast tests, and a **real (unmocked) slow-shutdown test proving WR-04's `RuntimeError`-on-failed-join path actually fires** — see Validation Audit below)
- [x] `tests/integration/test_chatbot_conformance.py` — covers D-02/PKG-03 (13/13 passing against the real cross-repo `AvailabilityContractSuite`, including capacity>1 and malformed-slot_id regression tests)
- [x] No new test framework dependency needed — `pytest`/`pytest-asyncio`/`testcontainers[postgres]` already present

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `v0.1.0` git tag cut and pushed | PKG-03 | Deliberately human-gated release action (05-05-PLAN.md Task 1 `checkpoint:human-verify`, T-05-08) — not something an automated test or auditor should approve on the phase's behalf | A human reviews the full-suite-green evidence in 05-VERIFICATION.md, types "approved", then Task 2 cuts and pushes the annotated tag; verify with `git ls-remote --tags origin` |

---

## Validation Sign-Off

### Validation Audit 2026-09-05

Ran against HEAD `9d73b82` (post code-review-fix pass `9ef17ad..51ca29d`, post security-audit fix
`b27353a`). Both prior fix passes already added targeted regression tests for CR-01 (capacity>1
idempotency), WR-01/WR-04 unit-level fail-fast behavior, WR-03 (json-encoded slot_id), and UF-1
(malformed slot_id) — this audit's own gap-hunting deliberately looked past those for coverage that
was still only asserted structurally or for a single backend, not proven behaviorally end-to-end.

Two genuine Nyquist gaps were found and filled with new, real, previously-failing-if-broken tests:

1. **WR-04's `RuntimeError`-on-failed-join path had zero test coverage of any kind** — not mocked,
   not real. `tests/test_sync_facade.py` tested the *thread eventually stops* path
   (`test_close_stops_background_thread`) and the *fail-fast-after-close* path
   (`test_call_after_close_raises_immediately_instead_of_hanging`), but no test ever drove `close()`
   into its own timeout-exceeded branch. Added
   `test_close_raises_runtime_error_when_thread_fails_to_join_in_time`: schedules a plain callback
   directly onto the background loop via `call_soon_threadsafe` that does a real, synchronous
   `time.sleep(8)` (blocking the loop's own thread, not mocked), then calls `close()` and asserts it
   raises `RuntimeError` matching "failed to stop" — the actual 5-second join genuinely times out
   because the loop thread is provably busy. First run without ordering care raced and passed
   trivially (stop() could preempt an unstarted coroutine task); fixed by scheduling the blocking
   work as a direct `call_soon_threadsafe` callback (guaranteed FIFO with `close()`'s own
   `call_soon_threadsafe(loop.stop)`) instead of via `run_coroutine_threadsafe`, which schedules
   task creation as an extra indirection. Verified failing against a stubbed always-succeeds join
   before the fix, and passing against the real implementation.
2. **The packaging force-include / installed-wheel migration bootstrap was only proven against
   SQLite**, despite this library explicitly targeting both SQLite and Postgres (asyncpg is a direct
   wheel dependency, and `tests/test_migrations.py` already proves the *source-tree* alembic config
   works against both — but the *installed-wheel* `get_script_location()` path, the actual thing
   PKG-01/T-05-08 packaging change was about, was never exercised against Postgres). Added
   `test_migration_bootstraps_from_installed_wheel_against_postgres` to
   `tests/packaging/test_bootstrap_installed_wheel.py`: builds the real wheel, installs it into a
   fresh venv (factored out of the existing SQLite test into a shared `_build_wheel_into_fresh_venv`
   helper), spins up a real `testcontainers` Postgres 17 instance, and runs
   `get_script_location()` + `alembic upgrade head` + table inspection against it from the
   installed wheel's own site-packages copy — the same real-artifact proof the SQLite test gives,
   for the other backend.

| Metric | Count |
|--------|-------|
| Gaps found | 2 |
| Resolved | 2 |
| Escalated | 0 |

Full suite re-run after both additions: `uv run pytest` → **139 passed** (was 137; +2 new tests),
0 failed, 0 skipped, at HEAD `9d73b82` (tests added on top, no implementation files touched).

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 60s
- [x] `nyquist_compliant: true` — gap analysis found 2 gaps, both resolved with real, passing,
      previously-would-have-failed-if-broken tests; zero gaps remain; the only outstanding item
      (`v0.1.0` tag cut) is Manual-Only by explicit design (human-gated checkpoint, not a coverage gap)

**Approval:** validated 2026-09-05 — NYQUIST COMPLIANT
