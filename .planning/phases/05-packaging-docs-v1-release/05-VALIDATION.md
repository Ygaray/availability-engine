---
phase: 5
slug: packaging-docs-v1-release
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-09-04
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
| **Estimated runtime** | ~30-60 seconds (full suite, incl. wheel-build/install subprocess tests) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/packaging/ tests/test_sync_facade.py -x`
- **After every plan wave:** Run `uv run pytest` (full suite, including cross-repo conformance suite once the dev dependency resolves)
- **Before `/gsd-verify-work`:** Full suite must be green, INCLUDING the wheel-smoke-install test and the conformance suite, BEFORE tagging `v0.1.0` (tag immutability makes this non-negotiable)
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 05-01-XX | 01 | 0 | PKG-01 | — | Wheel namelist contains `py.typed` and the force-included migration tree | integration | `uv run pytest tests/packaging/test_wheel_contains_migrations.py -x` | ❌ W0 | ⬜ pending |
| 05-01-XX | 01 | 0 | PKG-01 | — | Wheel installs via git-tag pin, migrations bootstrap from the installed wheel | integration | `uv run pytest tests/packaging/test_bootstrap_installed_wheel.py -x` | ❌ W0 | ⬜ pending |
| 05-01-XX | 01 | 1 | PKG-01 | T-05-01 | Sync facade safe to call from inside an already-running event loop; no leaked payload in exceptions/logs | unit/integration | `uv run pytest tests/test_sync_facade.py -x` | ❌ W0 | ⬜ pending |
| 05-01-XX | 01 | 1 | PKG-02 | — | `AvailabilityResult` JSON schema still matches the committed golden file (doc-example regression guard) | unit (existing) | `uv run pytest tests/test_contract_conformance.py -x` | ✅ (Phase 2) | ⬜ pending |
| 05-01-XX | 01 | 2 | PKG-03 | T-05-02 | Example adapter satisfies the consumer's full `AvailabilityContractSuite`; uuid4-only id generation preserved | integration (dev-only, cross-repo) | `uv run pytest tests/integration/test_chatbot_conformance.py -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/packaging/test_wheel_contains_migrations.py` — covers PKG-01 (wheel namelist inspection)
- [ ] `tests/packaging/test_bootstrap_installed_wheel.py` — covers PKG-01 (build+venv+install+migrate subprocess integration test)
- [ ] `tests/test_sync_facade.py` — covers PKG-01/D-04 (must include a test that calls the sync facade FROM INSIDE a running event loop via `asyncio.run(async_caller())` — the one test that proves the background-thread bridge is actually needed and works, not just that the facade works from plain sync code)
- [ ] `tests/integration/test_chatbot_conformance.py` — covers D-02/PKG-03 (blocked on resolving the consumer repo's missing git remote/tag push — flag as a plan dependency/checkpoint if unresolved at execution time)
- [ ] No new test framework dependency needed — `pytest`/`pytest-asyncio` already present

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| README/docs code examples actually run against the real API | PKG-02 | No doctest harness in scope for this phase; drift risk is low-frequency and doc-example execution isn't wired into CI | Read through README + docs examples after writing them; manually run each code snippet in a scratch REPL against the real installed package before tagging |

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
- [ ] Feedback latency < 60s
- [ ] _(finalizer-only, post-execution)_ `nyquist_compliant` — leave `false` at plan time; the
      finalizer sets `true` iff its gap analysis finds zero gaps

**Approval:** pending — finalizer-owned, not set at plan time
