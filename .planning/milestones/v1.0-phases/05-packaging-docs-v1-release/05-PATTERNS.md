# Phase 5: Packaging, Docs & v1 Release - Pattern Map

**Mapped:** 2026-09-04
**Files analyzed:** 10 (new/modified)
**Analogs found:** 9 / 10 (all from the sibling consumer repo `SocialNetwork-Chatbot`, already-proven templates; 1 has no analog — README)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `pyproject.toml` (modify: `[tool.hatch.build.targets.wheel.force-include]`) | config | file-I/O (build packaging) | `SocialNetwork-Chatbot/pyproject.toml` lines ~41-52 | exact |
| `src/availability_engine/py.typed` | config | n/a (empty marker) | `SocialNetwork-Chatbot/src/chatbot_engine/py.typed` (per git show `f77687c`) | exact |
| `src/availability_engine/_migrations/__init__.py` | utility (package anchor) | file-I/O | `SocialNetwork-Chatbot/src/chatbot_engine/_alembic/__init__.py` | exact |
| `src/availability_engine/migrations.py` | utility (path resolver) | file-I/O | `SocialNetwork-Chatbot/src/chatbot_engine/persistence/reconcile.py::_resolve_alembic_ini` | exact |
| `src/availability_engine/sync.py` | service (facade) | request-response (async→sync bridge) | `src/availability_engine/engine.py` (method shape to wrap) + general asyncio bridge pattern (no direct repo analog for the bridge itself — consumer doesn't have one) | role-match |
| `examples/chatbot_adapter.py` | service (adapter, dev-only) | request-response (protocol translation) | `SocialNetwork-Chatbot/src/consumers/escaperoom/build_runtime.py` (swap-point pattern) + `SocialNetwork-Chatbot/src/chatbot_engine/availability/port.py` (`AvailabilityPort` ABC being satisfied) | role-match |
| `tests/packaging/test_wheel_contains_migrations.py` | test | file-I/O (subprocess + zip inspect) | `SocialNetwork-Chatbot/tests/packaging/test_wheel_contains_both_packages.py` | exact |
| `tests/packaging/test_bootstrap_installed_wheel.py` | test | file-I/O (subprocess: build+venv+install+migrate) | `SocialNetwork-Chatbot/tests/packaging/test_bootstrap_installed_wheel.py` | exact |
| `tests/test_sync_facade.py` | test | event-driven (asyncio loop-in-loop) | `tests/test_migrations.py` (existing async bootstrap test structure in this repo) — no direct sync-facade analog exists anywhere; pattern is novel to this phase | partial |
| `tests/integration/test_chatbot_conformance.py` | test | CRUD (subclassing a shared contract suite) | `SocialNetwork-Chatbot/src/chatbot_engine/availability/testing/contract.py` (`AvailabilityContractSuite` base being subclassed) | role-match |
| `README.md` | docs | n/a | none (no `docs/` or structured README convention in either repo — see "No Analog Found") | none |

## Pattern Assignments

### `pyproject.toml` (config, file-I/O)

**Analog:** `SocialNetwork-Chatbot/pyproject.toml` lines 41-52 (already read and cited in RESEARCH.md)

**Core pattern — force-include migrations without disturbing `packages`:**
```toml
[tool.hatch.build.targets.wheel]
packages = ["src/availability_engine"]   # already exists — DO NOT touch

[tool.hatch.build.targets.wheel.force-include]
"alembic.ini" = "availability_engine/_migrations/alembic.ini"
"alembic" = "availability_engine/_migrations/alembic"
```
**Current state verified this session** (`/home/yahir/Projects/Reusable/availability-engine/pyproject.toml` lines 30-31):
```toml
[tool.hatch.build.targets.wheel]
packages = ["src/availability_engine"]
```
Only the `force-include` table is new — do not add `only-include`/`sources` (Pitfall 5 in RESEARCH.md).

Also add the conformance dev-dependency group entry (PEP 735 `[dependency-groups]`, already used in this file for `dev`) — new group, e.g. `conformance`, sourced via `[tool.uv.sources]` git+tag, mirroring the consumer's own commented-out seam:
```toml
[tool.uv.sources]
socialnetwork-chatbot = { git = "https://github.com/Ygaray/SocialNetwork-Chatbot", tag = "v1.0" }
```
This is a **blocking cross-repo prerequisite** (consumer repo currently has no git remote — RESEARCH.md Pitfall 4) — flag `checkpoint:human-verify` before this task.

---

### `src/availability_engine/py.typed` (config marker)

**Analog:** consumer's own fix, `git show f77687c --stat` in `SocialNetwork-Chatbot` — touched only the marker file + one test, no `pyproject.toml` change (because `packages = [...]` already includes the whole tree).

**Pattern:** empty file, path `src/availability_engine/py.typed`. No content to extract — just create it.

---

### `src/availability_engine/_migrations/__init__.py` (utility, file-I/O)

**Analog:** `SocialNetwork-Chatbot/src/chatbot_engine/_alembic/__init__.py`

**Core pattern** — near-empty docstring-only package anchor (verbatim template from RESEARCH.md, already adapted to this repo's naming):
```python
"""Package anchor for the force-included Alembic assets.

This package is intentionally near-empty. Its sole purpose is to give
``importlib.resources.files("availability_engine._migrations")`` a real,
importable anchor to resolve against. The actual ``alembic.ini``/``alembic/``
content is NOT written here in the source tree -- it is copied into this
package's directory *inside the built wheel only*, via
``[tool.hatch.build.targets.wheel.force-include]``, from the canonical
repo-root locations (kept there for `alembic` CLI ergonomics).
"""
```

---

### `src/availability_engine/migrations.py` (utility, file-I/O)

**Analog:** `SocialNetwork-Chatbot/src/chatbot_engine/persistence/reconcile.py::_resolve_alembic_ini`

**Core pattern** — dual-layout resolver, installed-wheel-first then repo-checkout fallback (verbatim template from RESEARCH.md):
```python
from __future__ import annotations

from importlib.resources import files
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def get_script_location() -> Path:
    """Resolve the Alembic ``script_location`` directory wherever it landed."""
    packaged = files("availability_engine._migrations").joinpath("alembic")
    if packaged.is_dir():
        return Path(str(packaged))
    return _REPO_ROOT / "alembic"
```
Verified against this repo's actual `alembic/` layout at repo root (`alembic/env.py`, `alembic/script.py.mako`, `alembic/versions/0001_initial_schema.py`, `alembic.ini` at root) — confirmed via 05-CONTEXT.md Runtime Decisions.

---

### `src/availability_engine/sync.py` (service, request-response async→sync bridge)

**Analog (method shape to wrap):** `src/availability_engine/engine.py` — read in full this session.

**Imports pattern to mirror** (`engine.py` lines 10-24 — same project-relative import style, no path aliases):
```python
from availability_engine import time as time_boundary
from availability_engine.contracts import (
    AvailabilityResult, Booking, Hold, PublicSlot, Resource, SlotStatus, UtcDatetime,
)
from availability_engine.storage.protocol import StorageBackend
```

**Core pattern — every public method on `AvailabilityEngine` gets a synchronous mirror** (`engine.py` lines 27-136 — exactly 6 public methods, verified by direct read this session: `define_resource`, `get_availability`, `place_hold`, `confirm_hold`, `release_hold`, `cancel_booking`). Signatures to preserve verbatim (only sync-ify):
```python
async def define_resource(self, resource: Resource) -> None: ...
async def get_availability(self, resource_id: str, start: UtcDatetime, end: UtcDatetime) -> AvailabilityResult: ...
async def place_hold(self, resource_id: str, slot_start: UtcDatetime, slot_end: UtcDatetime,
                      ttl_seconds: int, idempotency_key: str | None = None) -> Hold: ...
async def confirm_hold(self, hold_id: str, payload: dict[str, Any], idempotency_key: str | None = None) -> Booking: ...
async def release_hold(self, hold_id: str) -> None: ...
async def cancel_booking(self, booking_id: str) -> None: ...
```

**Bridge pattern (background-thread persistent loop + `run_coroutine_threadsafe`)** — full working template already written in 05-RESEARCH.md ("Pattern 2"); copy near-verbatim. No `asyncio.run()` anywhere (see Anti-Patterns / Pitfall 3).

**Error handling pattern:** the sync facade does NOT translate exceptions — it lets the engine's typed exceptions (`CapacityExhaustedError`, `OutsideHoursError`, etc., all defined in `src/availability_engine/errors.py`, re-exported via `src/availability_engine/__init__.py` lines 16-23) propagate unchanged through `future.result()`, which re-raises the original exception from the coroutine. Exception *translation* only happens in the adapter (see below), not the facade.

---

### `examples/chatbot_adapter.py` (service, request-response protocol translation, dev-only — NOT shipped)

**Analog 1 (swap-point pattern):** `SocialNetwork-Chatbot/src/consumers/escaperoom/build_runtime.py` — the single-import composition-root swap point the adapter is designed to replace.

**Analog 2 (ABC being satisfied):** `SocialNetwork-Chatbot/src/chatbot_engine/availability/port.py` — `AvailabilityPort` ABC, `Slot`/`Hold`/`Booking` dataclasses, and the exceptions `SlotUnavailable`, `HoldExpired`, `HoldConflict`.

**Imports pattern** — this file is the one place allowed to cross the one-way dependency boundary (imports both this engine's public API and the consumer's `chatbot_engine` package):
```python
from availability_engine import (
    CapacityExhaustedError, HoldExpiredError, HoldNotFoundError,
    IdempotencyConflictError, OutsideHoursError,
)
from availability_engine.sync import SyncAvailabilityEngine

from chatbot_engine.availability.port import (
    AvailabilityPort, Booking as ConsumerBooking, Hold as ConsumerHold,
    HoldConflict, HoldExpired, Slot as ConsumerSlot, SlotUnavailable,
)
```

**Core translation pattern (field mapping, D-03 resolved):**
- `query_availability(resource_type, window, party_size)` → `get_availability(resource_type, window[0], window[1])`, filter `result.available` by `s.remaining >= party_size`
- `place_hold` → engine `place_hold`; catch `(CapacityExhaustedError, OutsideHoursError)` → raise `SlotUnavailable`; catch `IdempotencyConflictError` → raise `HoldConflict`
- `confirm_hold` → engine `confirm_hold`; catch `HoldExpiredError`/`HoldNotFoundError` → raise `HoldExpired`
- `cancel(ref)` → engine `cancel_booking(ref)`, swallow exceptions (idempotent no-op per consumer's port contract)
- ids: `uuid.uuid4()` for `confirmation_ref`

Full illustrative code is in 05-RESEARCH.md "Pattern 3" — copy as starting point, but this mapping is `[ASSUMED]`/not yet validated against `AvailabilityContractSuite` (RESEARCH.md Assumptions Log A1). Budget an iteration loop: implement → run `AvailabilityContractSuite` → adjust `slot_id` encoding and idempotency-replay semantics until green.

**Error handling pattern:** never log or interpolate `payload`/`details` dicts into exception messages (mirrors `src/availability_engine/errors.py`'s existing T-01-01 rule — never accept/store payload in exception constructors).

---

### `tests/packaging/test_wheel_contains_migrations.py` (test, file-I/O)

**Analog:** `SocialNetwork-Chatbot/tests/packaging/test_wheel_contains_both_packages.py` (read in full this session)

Full working template already in 05-RESEARCH.md "Code Examples" section — copy near-verbatim, adjusting asserted namelist entries to `availability_engine/py.typed` and `availability_engine/_migrations/alembic/**`.

**Core pattern:** `uv build --wheel` via subprocess → `zipfile.ZipFile(wheel).namelist()` → assert expected paths present. Skip via `pytest.mark.skipif(shutil.which("uv") is None, ...)`.

---

### `tests/packaging/test_bootstrap_installed_wheel.py` (test, file-I/O)

**Analog:** `SocialNetwork-Chatbot/tests/packaging/test_bootstrap_installed_wheel.py` (read in full this session)

Full working template already in 05-RESEARCH.md "Code Examples" — build wheel → `uv venv` → `uv pip install` the wheel → run a subprocess script asserting `import availability_engine` resolves from `site-packages` AND `alembic upgrade head` against `get_script_location()` succeeds (`MIGRATE_OK` marker).

---

### `tests/test_sync_facade.py` (test, event-driven)

**Analog (structure only — async test conventions in this repo):** existing `tests/test_migrations.py` (`pytest-asyncio`, `asyncio_mode = "auto"` per `pyproject.toml` `[tool.pytest.ini_options]`).

**Core pattern (novel — no direct analog):** must prove the facade is safe when called from *inside* an already-running event loop (the exact scenario `asyncio.run()` cannot handle):
```python
import asyncio

def test_sync_facade_callable_from_inside_running_loop():
    engine = SyncAvailabilityEngine(storage=...)

    async def caller():
        # calling a *sync* method from inside async code — mirrors the
        # consumer's ConversationService/BookingService calling the port inline
        return engine.get_availability(resource_id, start, end)

    result = asyncio.run(caller())
    assert result is not None
    engine.close()
```
This is the one test that actually proves Pitfall 3 (RESEARCH.md) is fixed — not just that the facade works from plain sync code.

---

### `tests/integration/test_chatbot_conformance.py` (test, CRUD)

**Analog:** `SocialNetwork-Chatbot/src/chatbot_engine/availability/testing/contract.py` (`AvailabilityContractSuite`) — the shared base class being subclassed, verified present/importable this session per RESEARCH.md.

**Core pattern:** subclass the consumer's shared suite, wiring its required fixture(s)/factory hook up to `AvailabilityEngineAdapter(SyncAvailabilityEngine(storage))` from `examples/chatbot_adapter.py`:
```python
from chatbot_engine.availability.testing.contract import AvailabilityContractSuite
from availability_engine.sync import SyncAvailabilityEngine
from examples.chatbot_adapter import AvailabilityEngineAdapter

class TestChatbotConformance(AvailabilityContractSuite):
    @pytest.fixture
    def port(self) -> AvailabilityPort:
        return AvailabilityEngineAdapter(SyncAvailabilityEngine(storage=...))
```
Exact fixture hook name/signature must be confirmed by reading `contract.py`'s actual fixture contract at execution time (not yet read line-by-line in this pattern pass — RESEARCH.md confirms only its existence/importability, not its exact fixture API).

**Note:** this test requires the dev-only `socialnetwork-chatbot` dependency (PATTERNS.md `pyproject.toml` section above) — blocked on the consumer repo remote/tag prerequisite (RESEARCH.md Pitfall 4 / Open Question #2).

---

## Shared Patterns

### One-way dependency boundary (structural rule, applies to `sync.py` vs `examples/chatbot_adapter.py`)
**Source:** CLAUDE.md ("engine imports no consumer") + RESEARCH.md Anti-Patterns
**Apply to:** `src/availability_engine/sync.py` (must NOT import anything from `chatbot_engine`) vs `examples/chatbot_adapter.py` (the only file allowed to import `chatbot_engine`, and it must live outside `src/`)

### Never log/store raw payload in exceptions
**Source:** `src/availability_engine/errors.py` (existing T-01-01 rule, already established in Phase 1-2)
**Apply to:** `sync.py`, `examples/chatbot_adapter.py` — neither may interpolate `payload`/`details` dicts into exception messages or log lines.

### UTC-aware datetime boundary enforcement
**Source:** `src/availability_engine/time.py::require_utc` + `engine.py` lines 41-42 (`time_boundary.require_utc(start)` / `(end)`)
**Apply to:** `sync.py` — must not accept/produce naive datetimes at its own boundary; it simply forwards to the async engine which already enforces this, so no new validation code needed in the facade itself, but tests should assert naive datetimes still raise through the sync path.

### Wheel packaging: `force-include` for non-`src/` build assets
**Source:** `SocialNetwork-Chatbot/pyproject.toml` lines 41-52
**Apply to:** `pyproject.toml` — the only mechanism for pulling in the repo-root `alembic/` tree; `packages`/`only-include` cannot reach outside declared source trees.

### `uv`-based packaging smoke tests (subprocess build+venv+install)
**Source:** `SocialNetwork-Chatbot/tests/packaging/test_bootstrap_installed_wheel.py` and `test_wheel_contains_both_packages.py`
**Apply to:** `tests/packaging/test_wheel_contains_migrations.py`, `tests/packaging/test_bootstrap_installed_wheel.py` — both skip via `pytest.mark.skipif(shutil.which("uv") is None, ...)`.

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `README.md` | docs | n/a | No `docs/` or structured-README convention exists in either repo (RESEARCH.md verified this explicitly). Planner should structure it around the frozen contract types read from `contracts.py`, `errors.py`, `engine.py`, `storage/protocol.py`, `time.py` (all already read/verified in RESEARCH.md) — document `AvailabilityEngine` (async) + `SyncAvailabilityEngine` (new), `StorageBackend` Protocol, `AvailabilityResult`/`PublicSlot` output contract, typed exceptions + `ReasonCode`, concurrency guarantees (row-lock/`BEGIN IMMEDIATE` dialect split from Phase 4), and TZ/DST semantics (`UtcDatetime`, `zoneinfo` boundary). No code excerpt to copy — this is original writing grounded in existing source, not a pattern transplant. |
| `CHANGELOG.md` (optional, Claude's Discretion) | docs | n/a | No ecosystem precedent either way in either repo (RESEARCH.md Assumptions Log A3) — low-stakes, planner's call. |

## Metadata

**Analog search scope:** `/home/yahir/Projects/Reusable/availability-engine` (this repo, current state) and `/home/yahir/Projects/Reusable/SocialNetwork-Chatbot` (sibling consumer repo — all analogs already read in full during RESEARCH.md's session and re-verified against this repo's current `pyproject.toml`/`engine.py`/`__init__.py` in this pass)
**Files scanned:** `pyproject.toml`, `src/availability_engine/{engine.py,__init__.py,errors.py,contracts.py,time.py}`, `tests/packaging/` (consumer repo, listed), plus every file already cited in 05-RESEARCH.md's Sources section
**Pattern extraction date:** 2026-09-04
