---
phase: 05-packaging-docs-v1-release
reviewed: 2026-09-04T00:00:00Z
depth: deep
files_reviewed: 17
files_reviewed_list:
  - src/availability_engine/migrations.py
  - src/availability_engine/_migrations/__init__.py
  - src/availability_engine/py.typed
  - src/availability_engine/sync.py
  - src/availability_engine/__init__.py
  - examples/__init__.py
  - examples/chatbot_adapter.py
  - tests/integration/__init__.py
  - tests/integration/conftest.py
  - tests/integration/test_chatbot_conformance.py
  - tests/packaging/__init__.py
  - tests/packaging/test_bootstrap_installed_wheel.py
  - tests/packaging/test_wheel_contains_migrations.py
  - tests/test_readme_examples.py
  - tests/test_sync_facade.py
  - pyproject.toml
  - README.md
findings:
  critical: 2
  warning: 5
  info: 3
  total: 10
status: fixed
fixed_at: 2026-09-05T05:00:00Z
fix_summary:
  fixed: 10
  skipped: 0
  commits:
    - CR-01: 9ef17ad
    - WR-01: fbf2e99
    - WR-04: 334dc72
    - IN-02: 7560051
    - WR-02: c18f302
    - WR-03: 2cc72a4
    - WR-05/IN-01/IN-03: 51ca29d
---

# Phase 5: Code Review Report

**Reviewed:** 2026-09-04
**Depth:** deep
**Files Reviewed:** 17
**Status:** issues_found

## Summary

Phase 5 packages the engine for release: force-included Alembic migrations (05-01), a
background-thread sync facade (05-02), a cross-repo conformance adapter (05-03), and a
documented README with a regression-guarded example (05-04). The wheel-packaging fix
(force-include + `get_script_location()`) is sound and is proven by real
build→install→migrate integration tests — no defects found there.

Two BLOCKER-level defects were found by tracing call chains across files rather than
reading each file in isolation:

1. `examples/chatbot_adapter.py`'s idempotency-after-confirm fix (the specific gap this
   plan was written to close) only actually works for `capacity=1` resources — exactly the
   capacity value the conformance fixture (`tests/integration/conftest.py`) happens to use,
   which is why all 10 inherited `AvailabilityContractSuite` tests pass while the general
   case remains broken. For any `capacity > 1` resource, a `place_hold` retry with the same
   `idempotency_key` after the original hold was confirmed silently mints a **new, distinct
   Hold** instead of raising `HoldConflict` — a direct violation of
   `AvailabilityPort.place_hold`'s own documented contract ("If `idempotency_key` was
   already confirmed into a `Booking`... also raises `HoldConflict`... rather than silently
   minting a new hold").
2. `SyncAvailabilityEngine` (`src/availability_engine/sync.py`) hangs the calling thread
   forever, with no timeout and no exception, if any method is called after `close()`, or
   if `close()` races an in-flight call. This is exactly the deadlock class this review was
   asked to scrutinize in the background-thread bridge.

Five WARNING-level and three INFO-level findings follow below, covering thread-safety of
the adapter's idempotency bookkeeping, a fragile `slot_id` delimiter, silent failure modes
in `close()`/`__init__()`, and documentation-accuracy gaps in README.md (including one
README code block that cannot literally be copy-pasted and run, undercutting this phase's
own "every example is proven to run" claim).

## Structural Findings (fallow)

None provided for this review (no `<structural_findings>` block was supplied).

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: Idempotency-after-confirm fix only works for capacity=1; silently double-holds for capacity>1

**File:** `examples/chatbot_adapter.py:108-136`
**Issue:**
`AvailabilityPort.place_hold`'s contract (see
`SocialNetwork-Chatbot/src/chatbot_engine/availability/port.py:116-128`) states: *"If
`idempotency_key` was already confirmed into a `Booking`... also raises `HoldConflict` —
the original `Hold` no longer exists to replay, so a retried `place_hold` after a
successful confirm must fail loudly rather than silently minting a new hold."*

The adapter only enforces this on the **exception path**:

```python
except (
    CapacityExhaustedError,
    OutsideHoursError,
    ResourceNotFoundError,
) as exc:
    if idempotency_key in self._confirmed_keys:
        raise HoldConflict() from exc
    raise SlotUnavailable() from exc
```

But the underlying engine (`src/availability_engine/storage/memory.py:100-189`) only
raises `CapacityExhaustedError` on a post-confirm retry when the slot's capacity is
**still exhausted** by the live Booking. Tracing the actual storage logic: when
`place_hold` is retried with the same `idempotency_key` and the original Hold no longer
exists (`self._holds.get(existing.result.id)` is `None` because `confirm_hold` deleted it
— `memory.py:248`), it falls through to a **fresh, live capacity check**
(`memory.py:154-189`). For a resource with `capacity > 1`, the confirmed Booking occupies
only one unit; if any capacity remains for that exact slot, the fresh check succeeds and
**mints a brand-new Hold with a new id** — no exception is raised at all, so the adapter's
`except` block (the only place `_confirmed_keys` is ever consulted) never runs. The caller
receives a `ConsumerHold` for a second, independent hold on the same slot, silently
consuming another unit of capacity for what it believes was an idempotent retry of an
already-fulfilled request — the exact double-booking-adjacent failure mode this project's
Core Value promises never to allow.

This is untested because `tests/integration/conftest.py:29-44` defines the conformance
resource with `capacity=1` — at capacity 1, a confirmed Booking always keeps the slot at
zero remaining capacity, so the retry always happens to hit `CapacityExhaustedError` and
never exercises the success path above. The plan's own `<read_first>` for this task even
flagged this exact fall-through ("a same-idempotency-key place_hold retry AFTER confirm
falls through to a live capacity re-check and raises CapacityExhaustedError, not
IdempotencyConflictError — the exact gap this adapter must close") but the shipped fix
only closes it for the specific case where that fall-through happens to fail.

**Fix:** Check `_confirmed_keys` **before** calling the engine at all, so the behavior is
independent of live capacity:

```python
def place_hold(
    self, slot_id: str, ttl_seconds: int, idempotency_key: str
) -> ConsumerHold:
    if idempotency_key in self._confirmed_keys:
        raise HoldConflict()
    resource_id, start_iso, end_iso = slot_id.split("|")
    ...
```

## Warnings

### WR-01: SyncAvailabilityEngine hangs forever on a call made after close() or racing close()

**File:** `src/availability_engine/sync.py:112-115`
**Issue:** `close()` schedules `self._loop.stop()` and joins the thread, but never calls
`self._loop.close()` — the `asyncio.AbstractEventLoop` object is left stopped-but-open.
`_call()` (`sync.py:70-72`) dispatches via
`asyncio.run_coroutine_threadsafe(coro, self._loop).result()` with **no timeout**. If any
method is invoked on the facade after `close()` returns,
`loop.call_soon_threadsafe(...)` still succeeds (the loop isn't *closed*, just stopped),
scheduling a callback that will never run because nothing is driving `run_forever()` on
that thread anymore — `future.result()` then blocks the calling thread **forever**, with no
exception and no way to recover short of killing the thread. The same race exists if
`close()` is called concurrently with an in-flight `_call()`: depending on callback
ordering in the loop's ready queue, `loop.stop()` can take effect before the in-flight
coroutine is scheduled to run, stranding that caller's `future.result()` indefinitely.
This is precisely the deadlock class this facade exists to avoid (per its own module
docstring, its whole purpose is to never let a caller hang on the wrong side of an
event-loop boundary) — it just moved the hang to the shutdown path instead of eliminating
it, and no test in `tests/test_sync_facade.py` calls a method after `close()` to catch it.

**Fix:** Add a `self._closed` flag checked at the top of `_call()` to fail fast with a
clear `RuntimeError` instead of hanging, and pass an explicit timeout to `future.result()`
(or document/enforce a "drain in-flight calls before scheduling stop" ordering):

```python
def _call(self, coro: Coroutine[Any, Any, _T]) -> _T:
    if self._loop.is_closed() or not self._loop.is_running():
        raise RuntimeError("SyncAvailabilityEngine used after close()")
    future = asyncio.run_coroutine_threadsafe(coro, self._loop)
    return future.result(timeout=...)
```

### WR-02: chatbot_adapter's idempotency bookkeeping is unsynchronized shared mutable state

**File:** `examples/chatbot_adapter.py:74-82, 132-133, 150-152`
**Issue:** `self._hold_keys` (dict) and `self._confirmed_keys` (set) are read and mutated
with no lock, yet the module's own docstring instructs a real consumer to "either copy[]
this file into their own composition root or import[] it directly as a worked example" —
i.e., this is presented as a template for production use, where a `ConversationService`
handling concurrent conversations would call `place_hold`/`confirm_hold` from multiple
threads/tasks against the same adapter instance. A read-then-write race between
`place_hold`'s `if idempotency_key in self._confirmed_keys` check and `confirm_hold`'s
`self._confirmed_keys.add(key)` (run in an unrelated call, no ordering guarantee) can
misclassify a concurrent retry.
**Fix:** Guard both structures with a `threading.Lock` (the adapter already crosses a
thread boundary via `SyncAvailabilityEngine`), or explicitly document in the module
docstring that this reference adapter is single-threaded-caller-only and a production copy
must add its own synchronization.

### WR-03: slot_id's unescaped "|" delimiter breaks on a resource_id containing "|"

**File:** `examples/chatbot_adapter.py:96, 111`
**Issue:** `slot_id = f"{s.resource_id}|{s.start.isoformat()}|{s.end.isoformat()}"` and the
inverse `resource_id, start_iso, end_iso = slot_id.split("|")` assume `resource_id` never
contains a `"|"` character. `Resource.id` (`src/availability_engine/contracts.py:84`) is a
plain `str` with no character restriction — a resource id such as `"table|1"` (a
plausible domain-injected id, since the engine names zero domain concepts and lets any
consumer choose ids) makes `slot_id.split("|")` return more than 3 parts, raising an
unhandled `ValueError: too many values to unpack` from `place_hold` instead of a typed
`SlotUnavailable`/`HoldConflict`.
**Fix:** Use a delimiter reserved by validation (or `json.dumps`/base64-encode the tuple),
or reject/validate resource ids containing `"|"` at `define_resource` time.

### WR-04: SyncAvailabilityEngine.close()'s join timeout failure is silent

**File:** `src/availability_engine/sync.py:112-115`
**Issue:** `self._thread.join(timeout=5)` does not check whether the join actually
succeeded. If the background thread doesn't exit within 5 seconds (e.g., a
slow/blocked coroutine still running when `stop()` is scheduled), `close()` returns
normally with no exception or log line, even though the thread may still be alive — this
silently contradicts the documented/tested guarantee ("`close()` stops its background
thread within a bounded timeout, not left running forever" — 05-02-PLAN.md's own
must-have) in the one case (a slow shutdown) that guarantee exists to cover.
**Fix:**
```python
def close(self) -> None:
    self._loop.call_soon_threadsafe(self._loop.stop)
    self._thread.join(timeout=5)
    if self._thread.is_alive():
        raise RuntimeError("SyncAvailabilityEngine failed to stop within timeout")
```

### WR-05: README's Sync example references undefined variables — cannot be copy-pasted as written

**File:** `README.md:74-90`
**Issue:** The "Sync: `SyncAvailabilityEngine`" code block uses
`engine.get_availability("table-1", window_start, window_end)` — `window_start` and
`window_end` are never defined anywhere in the README (the async example just above it
inlines `datetime(2026, 9, 7, 0, 0, tzinfo=UTC)` literals directly into the call, never
binding them to a `window_start`/`window_end` name). A reader who copies only the Sync
section, as the section is written to be read standalone, gets
`NameError: name 'window_start' is not defined`. This directly undercuts this phase's own
stated guarantee: "Every code example below is exercised by an automated test... this is
not a manual-read-through doc" (README.md:12-13) — `tests/test_readme_examples.py`
doesn't actually execute the literal displayed snippet; it hardcodes its own
`WINDOW_START`/`WINDOW_END` module constants (`tests/test_readme_examples.py:23-24`) that
never appear in README.md, so the test can pass while the literal doc text remains broken.
**Fix:** Either inline the same `datetime(...)` literals used in the async example into
the sync example, or introduce `window_start`/`window_end` in the async example first and
reuse them in both blocks.

## Info

### IN-01: README miscounts StorageBackend's method count and cites the wrong test path

**File:** `README.md:97-99, 178`
**Issue:** "`StorageBackend` is a `typing.Protocol` with 6 async methods
(`save_resource`, `get_resource`, `get_active_entries`, `place_hold`, `confirm_hold`,
`release_hold`, `cancel_booking`..." — that list has 7 names, matching the actual Protocol
(`src/availability_engine/storage/protocol.py:14-54`, which has 7 methods), not 6.
Separately, the Concurrency section cites `tests/test_concurrency_proof.py`; the file
actually lives at `tests/storage/test_concurrency_proof.py`.
**Fix:** Change "6 async methods" to "7 async methods"; fix the test path reference.

### IN-02: SyncAvailabilityEngine.close() never closes the underlying event loop

**File:** `src/availability_engine/sync.py:112-115`
**Issue:** `close()` stops the loop (`run_forever()` returns) and joins the thread, but
never calls `self._loop.close()`. The loop object (and any resources it holds, e.g.
selector file descriptors) is never released. Related to WR-01's stopped-but-not-closed
state that makes post-close calls hang instead of raising a clean "loop is closed" error.
**Fix:** `self._loop.close()` after the join (with a guard for the WR-01 fix's early-exit
`RuntimeError` path).

### IN-03: Packaged alembic.ini's relative script_location is unusable from a real install location

**File:** `README.md:124`, `pyproject.toml:43-45`, `alembic.ini:10`
**Issue:** README states: "Equivalently, from a shell with `alembic.ini` available:
`alembic upgrade head`." The force-included `alembic.ini`
(`availability_engine/_migrations/alembic.ini` inside the wheel) contains
`script_location = alembic`, a path relative to the process's current working directory —
it only resolves correctly if the shell's CWD happens to be
`.../site-packages/availability_engine/_migrations/`, which no consumer would ordinarily
`cd` into. The hedge ("from a shell with `alembic.ini` available") is technically
accurate but easy to misread as "just run `alembic upgrade head` after installing the
package," which does not work for an installed wheel — only the documented
`get_script_location()` programmatic path (the paragraph directly above it) actually works
post-install.
**Fix:** Either drop the CLI-shell alternative from the README (it's a dev-checkout-only
convenience) or explicitly state it only applies when running from this repo's own
checkout, not from an installed wheel.

## Fix Notes

All 10 findings were fixed; none were skipped.

- **CR-01** (`examples/chatbot_adapter.py`): moved the `_confirmed_keys` check to the
  top of `place_hold`, before the engine is ever called, so behavior no longer depends
  on live capacity. Added a capacity=2 conformance fixture
  (`tests/integration/conftest.py::capacity2_port`) and a dedicated regression test
  (`tests/integration/test_chatbot_conformance.py::test_place_hold_retry_after_confirm_raises_hold_conflict_on_capacity2`)
  that fails without the fix and passes with it. Commit `9ef17ad`.
- **WR-01** (`src/availability_engine/sync.py`): `_call()` now raises `RuntimeError`
  immediately if the loop is closed/not running, and `future.result()` now takes a
  30s default timeout. Commit `fbf2e99`.
- **WR-04** (`src/availability_engine/sync.py`): `close()` now raises `RuntimeError`
  if the background thread is still alive after the join timeout. Commit `334dc72`.
- **IN-02** (`src/availability_engine/sync.py`): `close()` now calls `self._loop.close()`
  after a successful join, coordinated with WR-01's `is_closed()` guard. Added
  regression tests (`test_close_closes_the_underlying_event_loop`,
  `test_call_after_close_raises_immediately_instead_of_hanging`) in
  `tests/test_sync_facade.py`. Commit `7560051`.
- **WR-02** (`examples/chatbot_adapter.py`): guarded `_hold_keys`/`_confirmed_keys`
  with a `threading.Lock` (`self._keys_lock`). Commit `c18f302`.
- **WR-03** (`examples/chatbot_adapter.py`): `slot_id` now uses `json.dumps`/`json.loads`
  instead of an unescaped `"|"`-joined string. Added a regression test with a
  resource_id containing `"|"` that fails without the fix. Commit `2cc72a4`.
- **WR-05 / IN-01 / IN-03** (`README.md`): fixed the undefined `window_start`/
  `window_end` in the Sync example (now inlines the same `datetime(...)` literals as
  the async example, making the block literally copy-paste-runnable); corrected
  "6 async methods" to "7"; corrected the concurrency-proof test path to
  `tests/storage/test_concurrency_proof.py`; clarified that the CLI-shell
  `alembic upgrade head` shortcut only works from a checkout of this repo, not an
  installed wheel. Commit `51ca29d`.

**Verification after all fixes:** `uv run pytest` — 136 passed (up from 132 baseline,
+4 new regression tests). `uv run --group conformance pytest tests/integration/ -x` —
12 passed (up from 10 baseline, +2 new regression tests). `uv run ruff check` and
`uv run ruff format --check` pass clean on every file touched by these fixes (pre-existing,
unrelated drift on 27 untouched files / 6 untouched lint errors elsewhere in the repo was
verified present in the baseline before these fixes and left out of scope for this review).
`uv run mypy --strict src` — clean, no issues found.

---

_Reviewed: 2026-09-04_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
_Fixed: 2026-09-05_
_Fixer: Claude (gsd-code-fixer)_
