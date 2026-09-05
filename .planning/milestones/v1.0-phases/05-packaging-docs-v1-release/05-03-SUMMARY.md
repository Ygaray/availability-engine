---
phase: 05-packaging-docs-v1-release
plan: 03
subsystem: examples/integration
tags: [cross-repo, conformance-suite, availability-port, idempotency, dependency-groups]

# Dependency graph
requires:
  - "05-01: packaged wheel (py.typed, force-included migrations)"
  - "05-02: src/availability_engine/sync.py::SyncAvailabilityEngine"
provides:
  - "examples/chatbot_adapter.py::AvailabilityEngineAdapter -- AvailabilityPort-conforming reference adapter"
  - "tests/integration/test_chatbot_conformance.py -- proves the frozen contract against the consumer's real AvailabilityContractSuite"
  - "pyproject.toml [dependency-groups] conformance -- dev-only, opt-in git-pinned dependency group"
affects: [release, README-worked-example]

# Actuals (#2632)
actuals:
  tokens: 3113
  tasks: 2
  commits: 2

# Tech tracking
tech-stack:
  added:
    - "socialnetwork-chatbot (dev-only, git-pinned to v1.0, conformance dependency group)"
  patterns:
    - "PEP 735 dependency-groups: a second, distinct opt-in group (conformance) alongside dev, isolating a large transitive dev tree so a plain `uv sync` never pulls it in"
    - "pytest pythonpath = ['.'] so a dev-only, never-shipped examples/ package is importable by the test suite without polluting the wheel"
    - "idempotency-key bookkeeping (dict + set) in an adapter to translate a storage-layer idempotency guarantee into a richer consumer-contract guarantee (place_hold retry after confirm -> HoldConflict, not a misleading SlotUnavailable)"

key-files:
  created:
    - examples/__init__.py
    - examples/chatbot_adapter.py
    - tests/integration/__init__.py
    - tests/integration/conftest.py
    - tests/integration/test_chatbot_conformance.py
  modified:
    - pyproject.toml
    - uv.lock

key-decisions:
  - "Task 1 (cross-repo remote/visibility decision) was resolved by the operator before this execution began: SocialNetwork-Chatbot was pushed as a PRIVATE GitHub repo (github.com/Ygaray/SocialNetwork-Chatbot), v1.0 tag pushed and confirmed live via git ls-remote"
  - "Added `pythonpath = ['.']` to [tool.pytest.ini_options] -- the only way to make examples/chatbot_adapter.py importable by tests/integration/conftest.py without shipping examples/ in the wheel (it deliberately has no other importable path per D-03)"
  - "confirm_hold passes hold_id itself as the engine's own idempotency_key -- this is what makes 'repeated confirm_hold(same hold_id) returns the SAME booking' work for free via the engine's existing fingerprint-based idempotency, with zero extra bookkeeping needed for that specific guarantee"
  - "booking.id (the engine's own already-uuid4() id, which storage/memory.py sets equal to the original hold.id) is reused as BOTH booking_id and confirmation_ref -- this is what makes cancel(ref) work uniformly regardless of which of the three bearer tokens the caller holds"

patterns-established:
  - "Exception translation in the adapter never passes a message to the raised consumer exception (HoldConflict()/SlotUnavailable()/HoldExpired() with no args) -- the simplest possible guarantee of zero details/payload interpolation (T-05-06)"

requirements-completed: [PKG-03]

coverage:
  - id: D1
    description: "socialnetwork-chatbot's AvailabilityContractSuite is dev-depended via a pinned v1.0 git tag (not main), resolvable by uv sync --group conformance"
    requirement: "PKG-03"
    verification:
      - kind: integration
        ref: "git -C SocialNetwork-Chatbot ls-remote --tags origin | grep refs/tags/v1.0; uv sync --group conformance; uv run --group conformance python -c 'import chatbot_engine.availability.testing.contract'"
        status: pass
    human_judgment: false
  - id: D2
    description: "AvailabilityEngineAdapter satisfies every AvailabilityContractSuite test method against the real engine, including the reused-idempotency-key-after-confirm case raising HoldConflict rather than a misleading SlotUnavailable"
    requirement: "PKG-03"
    verification:
      - kind: integration
        ref: "tests/integration/test_chatbot_conformance.py::TestChatbotConformance (10/10 inherited AvailabilityContractSuite methods pass, including test_place_hold_reused_idempotency_key_after_confirm_raises_hold_conflict)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Every id (hold_id/booking_id/confirmation_ref) the adapter surfaces is the engine's own already-uuid4() id -- never a newly-minted or predictable value"
    requirement: "PKG-03"
    verification:
      - kind: integration
        ref: "AvailabilityContractSuite.test_place_hold_then_confirm_succeeds asserts uuid.UUID(hold.hold_id, version=4), uuid.UUID(booking.booking_id, version=4), uuid.UUID(booking.confirmation_ref, version=4) -- passes"
        status: pass
    human_judgment: false
  - id: D4
    description: "The consumer repo's git remote visibility (public/private) was an explicit human decision, not a silent default picked by automation"
    requirement: "PKG-03"
    verification:
      - kind: manual
        ref: "Task 1 checkpoint:decision -- operator selected option-b (private); orchestrator executed gh repo create --private, git push origin v1.0, verified via gh repo view --json visibility"
        status: pass
    human_judgment: true

duration: 35min
completed: 2026-09-04
status: complete
---

# Phase 5 Plan 3: Cross-Repo Conformance -- AvailabilityEngineAdapter Summary

**Proved D-02/D-03/PKG-03 end to end: dev-depended on the consumer's `AvailabilityContractSuite` via a pinned, pushed `v1.0` git tag, and shipped `examples/chatbot_adapter.py` -- a real `AvailabilityPort`-conforming adapter over `SyncAvailabilityEngine` that passes all 10 inherited contract tests, including the idempotency-after-confirm edge case the research flagged as an open gap.**

## Performance

- **Duration:** 35 min
- **Tasks:** 2 (Task 1, the cross-repo checkpoint:decision, was resolved by the operator and executed by the orchestrator before this execution started)
- **Files modified:** 8 (5 created, 3 modified: pyproject.toml, uv.lock, and one pytest-config addition folded into pyproject.toml)

## Accomplishments

- Task 1 (prerequisite, already done): `SocialNetwork-Chatbot` pushed as a private GitHub repo with `v1.0` tag live, confirmed via `git ls-remote --tags origin` and `gh repo view --json visibility`
- `pyproject.toml`: added `[tool.uv.sources]` pinning `socialnetwork-chatbot` to `https://github.com/Ygaray/SocialNetwork-Chatbot.git` at tag `v1.0`, plus a new PEP 735 `conformance` dependency group distinct from `dev` -- `uv sync --group conformance` resolves and locks the consumer's full transitive dev tree (anthropic, structlog, sqlalchemy, aiosqlite, alembic, pydantic-settings, tenacity, pyyaml) without ever polluting a plain `uv sync`
- `examples/chatbot_adapter.py`: `AvailabilityEngineAdapter(AvailabilityPort)` -- the one file in this repo allowed to import `chatbot_engine`, wrapping a `SyncAvailabilityEngine` instance. Encodes `slot_id` as `resource_id|start_iso|end_iso` (both boundaries, not just start); translates engine exceptions to the consumer's exception hierarchy; closes the idempotency-semantics gap RESEARCH.md flagged via `_hold_keys`/`_confirmed_keys` bookkeeping so a `place_hold` retry whose original hold was already confirmed raises `HoldConflict`, not a misleading `SlotUnavailable`
- `tests/integration/conftest.py`: `port`/`one_available_slot`/`no_available_slot`/`held_slot` fixtures -- a resource with all-seven-weekday, near-full-day operating hours (so the fixture works regardless of which calendar day the suite runs on), snapshotting one shared query window per test so no two fixtures see drifted `datetime.now()` calls
- `tests/integration/test_chatbot_conformance.py`: `TestChatbotConformance(AvailabilityContractSuite)` with zero test methods of its own -- all 10 inherited tests pass against the real adapter (the plan's `<behavior>` block enumerated 10 method names under a "9" heading; all 10 that actually exist in the consumer's shared suite pass)
- Added `pythonpath = ["."]` to `[tool.pytest.ini_options]` -- the only way to make the dev-only, never-shipped `examples/` package importable by `tests/integration/conftest.py` without adding it to the wheel
- Full suite verified green: `uv run --group conformance pytest` -- 132 passed (122 pre-existing + 10 new); `ruff check`/`ruff format --check` clean on all new files

## Task Commits

1. **Task 2:** `f9343e6` (feat) -- `[tool.uv.sources]` + `conformance` dependency group added; `uv sync --group conformance` resolved and locked
2. **Task 3:** `e445cf8` (test) -- `examples/chatbot_adapter.py`, `tests/integration/conftest.py`, `tests/integration/test_chatbot_conformance.py` added; all 10 inherited `AvailabilityContractSuite` tests pass

## Files Created/Modified

- `examples/__init__.py` - empty package marker (dev/reference only, never shipped in the wheel)
- `examples/chatbot_adapter.py` - `AvailabilityEngineAdapter`: the `AvailabilityPort`-conforming reference adapter
- `tests/integration/__init__.py` - empty package marker
- `tests/integration/conftest.py` - `port`/`one_available_slot`/`no_available_slot`/`held_slot` fixtures
- `tests/integration/test_chatbot_conformance.py` - `TestChatbotConformance(AvailabilityContractSuite)`, zero own test methods
- `pyproject.toml` - `[tool.uv.sources]`, `[dependency-groups] conformance`, `pythonpath = ["."]`
- `uv.lock` - relocked to include the resolved `conformance` group

## Decisions Made

- Task 1's cross-repo visibility decision (public vs. private vs. already-handled) was resolved by the operator as option-b (private) before this execution began; this executor treated it as done per the dispatch instructions and did not re-decide or re-run `gh repo create`
- `pythonpath = ["."]` added to pytest config rather than any `sys.path` manipulation inside `conftest.py` -- keeps the import-path fix declarative and centralized in one place, consistent with how the rest of this project's pytest config already lives entirely in `pyproject.toml`
- Exception re-raises in the adapter (`HoldConflict()`, `SlotUnavailable()`, `HoldExpired()`) carry no message at all, rather than `str(exc)` from the underlying engine error -- the simplest possible guarantee that no message content (even opaque ids) is echoed, exceeding the T-05-06 threat mitigation's bar rather than just meeting it
- Test resource in `conftest.py` declares operating hours for all seven `Weekday` values (near-full-day, `00:00`-`23:59`) rather than mirroring `tests/conftest.py`'s Monday-only `sample_resource` verbatim -- necessary so the conformance suite passes deterministically regardless of which real calendar weekday it happens to run on (the plan's own `<action>` text anticipated this: "mirror `tests/conftest.py`'s existing `sample_resource` shape... spanning enough of the current UTC day/week")

## TDD Gate Compliance

Task 3 was executed test-first in intent (`tdd="true"` in the plan), but landed as a single commit rather than a RED/GREEN pair: the adapter implementation and the conformance test file were both new, and the very first test run (after writing both together, following the plan's fully-specified design) passed all 10 tests without an intermediate failing-test commit. Per the plan's own instruction ("Run it, and iterate on `examples/chatbot_adapter.py` / `tests/integration/conftest.py` until every inherited test passes -- this is the acceptance criterion, not the first draft"), the design was detailed enough (exact `slot_id` encoding, exact idempotency bookkeeping, exact id-reuse rules) that zero iteration was needed against the real suite. No RED commit exists for this task; documented here per the TDD Gate Compliance protocol rather than silently omitted.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking issue] Added `pythonpath = ["."]` to pytest config**
- **Found during:** Task 3, first `pytest` run against the new `tests/integration/` files
- **Issue:** `ModuleNotFoundError: No module named 'examples'` -- `tests/integration/conftest.py` imports `examples.chatbot_adapter`, but pytest's default import-mode inserts `tests/` (the nearest ancestor directory without an `__init__.py`) onto `sys.path`, not the repo root, so the root-level `examples/` package was never importable
- **Fix:** Added `pythonpath = ["."]` under `[tool.pytest.ini_options]` in `pyproject.toml` -- a pytest-only config addition (via pytest's built-in `pythonpath` plugin, pytest 7+), zero effect on the built wheel
- **Files modified:** `pyproject.toml`
- **Verification:** `uv run --group conformance pytest tests/integration/test_chatbot_conformance.py -x` -- 10 passed; full suite (`uv run --group conformance pytest`) -- 132 passed
- **Committed in:** `e445cf8` (Task 3 commit)

**2. [Rule 1 - Bug] Fixed ruff import-sort and line-length findings on new files**
- **Found during:** Task 3, running `ruff check` before committing
- **Issue:** Unsorted/unformatted import blocks in `examples/chatbot_adapter.py` and `tests/integration/conftest.py` (I001); one line over 88 chars in `chatbot_adapter.py`'s `place_hold` return statement (E501)
- **Fix:** `ruff check --fix` for the import sort; manually wrapped the long `ConsumerHold(...)` construction across three lines
- **Files modified:** `examples/chatbot_adapter.py`, `tests/integration/conftest.py`
- **Verification:** `uv run ruff check examples/ tests/integration/` -- all checks passed; `uv run ruff format --check examples/ tests/integration/` -- 5 files already formatted; full suite still green after the fix
- **Committed in:** `e445cf8` (Task 3 commit)

---
**Total deviations:** 2 auto-fixed (one blocking-issue fix, one lint cleanup; neither changed adapter behavior)
**Impact on plan:** None beyond the pytest-config addition, which is scoped entirely to test discoverability and has zero effect on the shipped wheel.

## Issues Encountered

None beyond the two auto-fixed deviations above.

## User Setup Required

None for this plan's own scope. The Task 1 cross-repo prerequisite (creating and pushing the `SocialNetwork-Chatbot` remote) was a one-time human decision + orchestrator-executed action completed before this execution began; no further setup is needed to re-run `uv sync --group conformance` or the conformance test suite going forward, as long as GitHub access to the private `Ygaray/SocialNetwork-Chatbot` repo is available to whoever runs it.

## Next Phase Readiness

- The conformance dependency group, the example adapter, and the passing conformance suite together constitute PKG-03's core release-readiness proof -- a later plan (05-05, cutting the `v1.0` tag) can now proceed knowing the frozen contract genuinely matches what the consumer already coded against
- `examples/chatbot_adapter.py` is a candidate worked example for the README's documentation of the public API surface, if not already covered by 05-04
- Full suite verified green: `uv run --group conformance pytest` -- 132 passed, `ruff check`/`ruff format --check` clean on all new/modified files

---
*Phase: 05-packaging-docs-v1-release*
*Completed: 2026-09-04*

## Self-Check: PASSED

All created files verified present on disk (`examples/__init__.py`, `examples/chatbot_adapter.py`, `tests/integration/__init__.py`, `tests/integration/conftest.py`, `tests/integration/test_chatbot_conformance.py`); both task commit hashes (`f9343e6`, `e445cf8`) verified present in `git log`.
