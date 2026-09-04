# Phase 5: Packaging, Docs & v1 Release - Research

**Researched:** 2026-09-04
**Domain:** Python packaging (hatchling wheels, git-tag distribution), cross-repo contract conformance testing, async→sync API bridging, reusable-library documentation
**Confidence:** HIGH

## Summary

This phase has no new algorithmic surface — everything the engine needs to *do* (capacity math,
DST, idempotency, SQL atomicity) is already built and tested in Phases 1–4. Phase 5 is entirely
about the **distribution boundary**: making the already-correct engine installable, documented,
and provably wired to its first real consumer. Three things must land together, in this order,
because later steps depend on earlier ones being correct in the tagged commit:

1. **Fix packaging** — the wheel currently ships the Python package but silently drops the
   Alembic migrations (`git-tag pip install` succeeds, `alembic upgrade head` then has nothing to
   run against). This was independently confirmed twice: once by reading the CONTEXT.md runtime
   decision, and again empirically in this research session by running `uv build` and inspecting
   the actual wheel contents — the built wheel's namelist contains zero `alembic/*` entries.
   `[tool.hatch.build.targets.wheel.force-include]` fixes this. The sibling consumer repo
   (`SocialNetwork-Chatbot`) hit and fixed the *exact same bug* in its own Phase-something (its
   commit history literally has `CR-01` for it) — its `pyproject.toml` and
   `persistence/reconcile.py::_resolve_alembic_ini` are a verified, reusable template.
2. **Ship the sync facade + example adapter, and prove conformance** — the engine's public
   contract is async; the consumer's `AvailabilityPort` is a synchronous `abc.ABC`. A naive
   `asyncio.run()`-per-call sync wrapper will crash the first time it's actually called from
   inside the consumer's own running event loop (its `ConversationService`/`BookingService` are
   async and call the port inline, not via `to_thread` — confirmed by reading `port.py`'s
   docstring). The correct pattern is a dedicated background thread running a persistent event
   loop, dispatched via `asyncio.run_coroutine_threadsafe`. The adapter that implements
   `AvailabilityPort` and imports `chatbot_engine` must live **outside** `src/availability_engine`
   (e.g. `examples/`) — importing the consumer from the shipped package would violate the
   locked one-way dependency rule (CLAUDE.md: "engine imports no consumer"). Conformance is proven
   by dev-depending on the consumer's already-tagged `AvailabilityContractSuite`
   (`chatbot_engine.availability.testing.contract.AvailabilityContractSuite`) via `[tool.uv.sources]`
   + a `[dependency-groups]` (PEP 735) dev-only entry pinned to a real consumer git tag — verified
   to exist locally as `v1.0`, though that tag is **not yet pushed to a remote** (the consumer repo
   currently has no `git remote` configured at all — a real blocker to flag).
3. **Document the contract and cut `v0.1.0`** — no `docs/` convention exists anywhere in this
   ecosystem (neither this repo nor the consumer has one); README-only documentation is the
   established local convention. Both repos use a static `version = "x.y.z"` in `pyproject.toml`
   matched by hand to a manually-created git tag — no `hatch-vcs`/dynamic versioning anywhere in
   this ecosystem. Follow that convention rather than introducing a new one.

**Primary recommendation:** Reuse the consumer's already-proven packaging fix verbatim (force-include
+ `importlib.resources` resolver + a wheel-smoke-test triplet), build the sync facade as a
background-thread event-loop bridge (not `asyncio.run()`), keep the `AvailabilityPort`-implementing
adapter and the conformance subclass entirely in dev/example code outside `src/`, and push the
consumer's `v1.0` tag to a real remote before pinning to it.

## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01 [version-tag]:** Cut `v0.1.0` — matches the consumer's already-committed pin seam
(`tag = "v0.1.0"`, "uncomment once tagged") and the reusable ecosystem's first-tag convention;
cutting `v1.0` would orphan the consumer's one-line repin and overstate maturity.
_(source: human)_ — **Reversibility:** one-way — a published git tag the consumer repins to.

**D-02 [conformance]:** Dev-depend on the consumer's already-packaged `AvailabilityContractSuite`
(via a pinned consumer git tag, not `main`, in a dev-only dependency group) and subclass it against
the engine's real adapter — a re-derived engine-side test can drift silently and defeats the
one-suite/many-backends guarantee. _(source: ai-auto)_

**D-03 [adapter] — refreshed, resolved:** The frozen contract is a **hybrid** — `get_availability`
returns structured `AvailabilityResult` (`available`/`booked` lists of `PublicSlot`); write paths
(`place_hold`, `confirm_hold`, `release_hold`, `cancel_booking`) raise typed exceptions
(`CapacityExhaustedError`, `OutsideHoursError`, `HoldExpiredError`, `HoldNotFoundError`,
`BookingNotFoundError`, `IdempotencyConflictError`, `ResourceNotFoundError`) plus a parallel
`ReasonCode` StrEnum. Ship an example-integration adapter translating: consumer
`query_availability(resource_type, window, party_size)` → `get_availability(resource_id, start, end)`
with `party_size` validated against `PublicSlot.remaining`; engine exceptions → consumer exceptions
(`CapacityExhaustedError`/`OutsideHoursError` → `SlotUnavailable`, `HoldExpiredError` → `HoldExpired`,
`IdempotencyConflictError`/`HoldNotFoundError` → `HoldConflict`); consumer `cancel(ref)` →
`cancel_booking(booking_id)`; ids are uuid4.

**D-04 [async-bridge]:** The engine ships a thin sync facade so the consumer's one-line swap works
(the async→sync bridge lives in this repo, not the consumer's composition root).
_(source: human)_ — **Reversibility:** costly — cross-repo contract.

**D-05 [packaging] — refreshed, resolved:** Phase 4 shipped Alembic migrations at repo-root
`alembic/` (`env.py`, `script.py.mako`, `versions/0001_initial_schema.py`), `alembic.ini` at root —
**outside** `src/availability_engine`. Current wheel config (`packages = ["src/availability_engine"]`)
packages only the src package — root `alembic/` is **not** in the wheel (confirmed risk, and
independently reconfirmed empirically this session — see Common Pitfalls). Fix: keep the explicit
`packages` list, additionally `force-include` the alembic tree under an importable in-package anchor
(`alembic` → `availability_engine/_migrations`), expose a programmatic helper (`importlib.resources`)
to point Alembic's `script_location` at the packaged path post-install, and verify with a smoke test:
build the wheel, pip install into a fresh venv, confirm both `import availability_engine` and a
migration bootstrap work.

### Claude's Discretion

Docs structure and README examples are open provided the contract is documented as the stable
product surface.

### Deferred Ideas (OUT OF SCOPE)

None — this is the release phase; deferrals beyond v1 (continuous-duration bookings via `portion`,
`FOR UPDATE` tuning) are already tracked in earlier phases and out of the v1 scope.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PKG-01 | The library is packaged with `uv` + `hatchling` for Python 3.12+, installable via git-tag pin | `force-include` config verified against the wheel build; wheel-smoke-test template verified from the consumer's own `tests/packaging/`; `py.typed` marker gap identified (consumer hit this exact bug already) |
| PKG-02 | The public API surface (engine facade + storage protocol + output contract + concurrency guarantees + TZ/DST semantics) is documented | Recommended README structure below, grounded in the actual frozen types read from `contracts.py`, `errors.py`, `engine.py`, `storage/protocol.py`, `time.py` |
| PKG-03 | v1 is cut as a git tag / release the first consumer can repin to | `v0.1.0` tag process, remote-push verification (this repo's remote is live; the consumer's is not), release-without-PyPI convention |

</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Wheel packaging (migrations force-include, `packages` list) | Build/Packaging | — | Pure `pyproject.toml` config; no runtime code path |
| `py.typed` marker (PEP 561) | Build/Packaging | Library (typed API) | Ships inside the wheel; makes `mypy --strict` types visible to a consumer's own type checker |
| Async engine facade (`AvailabilityEngine`) | Library (Engine) | — | Already exists (Phase 1); this phase only documents it |
| Sync facade (D-04 bridge) | Library (Engine) | — | New code inside `src/availability_engine`; must be import-safe with no consumer dependency |
| `AvailabilityPort`-conforming adapter | Example/Dev code | — | MUST live outside `src/availability_engine` — it imports the consumer's `chatbot_engine.availability.port.AvailabilityPort`, which is exactly the one-way-dependency rule the engine's shipped code must never violate |
| Conformance subclass (`AvailabilityContractSuite`) | Dev/Test | — | Dev-only dependency group; never installed by a consumer of this library |
| Migration bootstrap (`alembic upgrade head`) | Library (packaged data) + Consumer-run | — | Migration files ship inside the wheel; the consumer's own process invokes `alembic upgrade head` (D-03 from Phase 4: library owns no runtime lifecycle) |
| README / API docs | Docs | — | No `docs/` site convention anywhere in this ecosystem; README is the product surface |
| Git tag `v0.1.0` | Release/Git | — | One-way, published artifact the consumer repins to |

## Standard Stack

### Core

No new production dependencies are needed for this phase. All PKG-01/02/03 work is `pyproject.toml`
configuration, new files under `src/availability_engine/`, `examples/`, `tests/`, and `README.md`.

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `hatchling` | build-system requirement, unpinned (matches current `pyproject.toml`) | Wheel/sdist build backend | Already locked project-wide; `uv build` resolves `hatchling==1.32.0` today `[VERIFIED: PyPI JSON API + uv dry-run resolve, 2026-09-04]` |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `uv` (CLI, not a project dependency) | 0.11.19 present in this environment `[VERIFIED: uv --version]` | `uv build`, `uv venv`, `uv pip install` for the packaging smoke test; `uv add --tag ... --group dev` for the conformance dependency | Wheel build/install verification and dev-dependency management |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Static `version = "0.1.0"` in `[project]` | `hatch-vcs` (dynamic, derived from git tags) | Rejected for this phase: neither this repo nor its sibling consumer uses `hatch-vcs` anywhere in the ecosystem `[VERIFIED: read both repos' pyproject.toml — both use a static version string]`. Introducing it here would be a one-off inconsistency, add a new build-time dependency, and (per hatch-vcs's own docs) requires committing to `.gitignore`-ing a generated `_version.py` — unnecessary churn for a phase whose job is to *match* an already-fixed `v0.1.0` tag, not derive a version from history. |
| `asyncio.run()`-per-call sync facade | Background-thread persistent event loop + `run_coroutine_threadsafe` | `asyncio.run()` raises `RuntimeError: asyncio.run() cannot be called from a running event loop`. The consumer's own `AvailabilityPort` docstring explicitly anticipates being called "inline" from already-async code (`ConversationService`/`BookingService`), not via `to_thread` — so a naive per-call `asyncio.run()` facade WILL crash on first real-world use. See Common Pitfalls. |
| README-only docs | A `docs/` site (mkdocs, Sphinx) | Rejected: no such convention exists anywhere in this project's ecosystem (`~/Projects/Reusable/*`); adding one here would be the first of its kind and increases the release phase's scope beyond what CONTEXT.md's "Claude's Discretion" note implies ("Docs structure ... open provided the contract is documented as the stable product surface" — a README satisfies that). |

**Installation:**
No new `uv add` commands are needed for `[project.dependencies]`. The only new dependency-group
addition is the consumer's package, added dev-only:
```bash
uv add "socialnetwork-chatbot @ git+https://github.com/Ygaray/SocialNetwork-Chatbot" \
  --tag v1.0 --group dev
```
(Verify the exact distribution/import name and confirm the tag is pushed to the remote — see
Open Questions and Common Pitfalls.)

**Version verification:** `hatchling` resolves to `1.32.0` on PyPI as of this session
`[VERIFIED: https://pypi.org/pypi/hatchling/json returned "version": "1.32.0"; corroborated by `uv pip install --dry-run hatchling` resolving `hatchling==1.32.0`]`. The project's `build-system.requires = ["hatchling"]` is already unpinned, matching current convention — no change needed.

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|--------------|---------|-------------|
| `hatchling` | PyPI | Frequent-release official PyPA build backend (this environment resolved `1.32.0`, published 2026-08-11) | Not machine-readable via the legitimacy seam (`weeklyDownloads: null`) | `github.com/pypa/hatch/tree/master/backend` | `SUS` (seam heuristic: "too-new" + "unknown-downloads") | **Approved** — already pre-approved in `.planning/APPROVED-DEPS.md` (Phase 5, Verdict `SUS`, Approved 2026-09-03). The `SUS` verdict is a known false-positive for this package: it is the official `pypa/hatch` build backend, already a locked project dependency since Phase 1, re-released frequently (hence "too-new" on any snapshot date) with no download-count API exposed by the seam. No new checkpoint needed. |

**Packages removed due to `[SLOP]` verdict:** none.
**Packages flagged as suspicious `[SUS]`:** `hatchling` — pre-approved, no action needed (see above).

**Note on the conformance dependency (`socialnetwork-chatbot` / `chatbot_engine`):** this is a
**git-source** dependency, not a registry package — the `package-legitimacy` seam checks
npm/PyPI/crates registries and does not apply. Its legitimacy is instead established by direct
repo inspection: it's a sibling project in the same local ecosystem, authored by the same
developer, with `AvailabilityContractSuite` verified present and importable at
`chatbot_engine.availability.testing.contract` `[VERIFIED: /home/yahir/Projects/Reusable/SocialNetwork-Chatbot/src/chatbot_engine/availability/testing/contract.py — read in full]`. The planner should still add a `checkpoint:human-verify` before this dependency is added, because (a) it pulls in the consumer's full dependency tree (`anthropic`, `structlog`, `pyyaml`, `tenacity`, `sqlalchemy`, `aiosqlite`, `alembic`, `pydantic-settings`) as transitive dev-only installs, and (b) the tag it pins to is **not yet pushed to any remote** (see Open Questions).

## Architecture Patterns

### System Architecture Diagram

```
                    availability-engine repo (this repo)
  ┌─────────────────────────────────────────────────────────────────┐
  │  src/availability_engine/            (SHIPPED IN WHEEL)         │
  │  ├── engine.py         AvailabilityEngine (async facade)        │
  │  ├── sync.py           SyncAvailabilityEngine (NEW, D-04)       │
  │  │                      — background-thread event loop bridge   │
  │  ├── contracts.py      AvailabilityResult / PublicSlot / ...    │
  │  ├── errors.py         typed exceptions + ReasonCode            │
  │  ├── storage/          StorageBackend Protocol + memory/sql     │
  │  ├── migrations.py     NEW — get_script_location() helper       │
  │  │                      (importlib.resources, D-05)             │
  │  ├── _migrations/      NEW — package anchor (near-empty,        │
  │  │                      mirrors chatbot_engine/_alembic/)       │
  │  └── py.typed          NEW — PEP 561 marker (currently MISSING) │
  │                                                                   │
  │  alembic/               (repo-root source of truth, unchanged)  │
  │  ├── env.py, script.py.mako, versions/0001_initial_schema.py    │
  │  └── force-included into the wheel at build time only ─────┐    │
  │                                                              │    │
  │  examples/              (NOT SHIPPED — dev/reference only)  │    │
  │  └── chatbot_adapter.py  AvailabilityEngineAdapter(          │    │
  │       AvailabilityPort)  — imports chatbot_engine.availability.port
  │                                                               │    │
  │  tests/                 (dev-only, not shipped)              │    │
  │  ├── packaging/          wheel-smoke-install-and-migrate      │    │
  │  └── integration/         subclasses consumer's                │    │
  │       test_chatbot_conformance.py  AvailabilityContractSuite   │    │
  └──────────────────────────────────────────────────────────────┼────┘
                                                                    │
                          uv build (hatchling)                     │
                                   │                                │
                                   ▼                                │
                     built wheel: availability_engine-0.1.0-py3-none-any.whl
                     ├── availability_engine/*.py  (existing)      │
                     └── availability_engine/_migrations/  ◄───────┘
                          (alembic.ini, env.py, script.py.mako, versions/)

  ════════════════════ git tag v0.1.0, pushed to origin ════════════════

                    SocialNetwork-Chatbot repo (consumer, sibling)
  ┌─────────────────────────────────────────────────────────────────┐
  │  pyproject.toml                                                  │
  │  [tool.uv.sources]                                                │
  │  availability-engine = { git = "https://github.com/Ygaray/       │
  │                           availability-engine", tag = "v0.1.0" } │
  │                          ── currently COMMENTED OUT, uncomment    │
  │                             once this repo's tag exists           │
  │                                                                    │
  │  consumers/escaperoom/build_runtime.py                            │
  │  — the ONE swap-point line:                                       │
  │    from chatbot_engine.availability.stub import                  │
  │         InMemoryAvailabilityStub as _StubPort                    │
  │  → becomes (after this phase):                                    │
  │    from availability_engine.examples... import                   │
  │         AvailabilityEngineAdapter as _StubPort  (or a copy of it) │
  └─────────────────────────────────────────────────────────────────┘
```

### Recommended Project Structure

```
availability-engine/
├── pyproject.toml                    # force-include, py.typed picked up automatically
├── README.md                         # documents engine facade, storage protocol,
│                                      # output contract, concurrency, TZ/DST
├── alembic/                          # UNCHANGED — stays at repo root for CLI ergonomics
├── src/availability_engine/
│   ├── py.typed                      # NEW — empty file, PEP 561 marker
│   ├── sync.py                       # NEW — SyncAvailabilityEngine (D-04)
│   ├── migrations.py                 # NEW — get_script_location() (D-05)
│   └── _migrations/
│       └── __init__.py               # NEW — near-empty importlib.resources anchor
├── examples/
│   └── chatbot_adapter.py            # NEW — AvailabilityPort-conforming reference adapter
│                                      # (imports chatbot_engine; NOT part of the wheel)
├── tests/
│   ├── packaging/
│   │   ├── test_wheel_contains_migrations.py   # NEW — namelist assertion
│   │   └── test_bootstrap_installed_wheel.py   # NEW — build+venv+install+migrate
│   └── integration/
│       └── test_chatbot_conformance.py         # NEW — subclasses AvailabilityContractSuite
└── CHANGELOG.md                      # optional (see Claude's Discretion) — no ecosystem
                                       # precedent either way; light-touch if added
```

### Pattern 1: force-include migrations into an importable in-package anchor

**What:** Map the repo-root `alembic/` tree into the wheel under
`availability_engine/_migrations/`, with a near-empty `__init__.py` package anchor already
committed in `src/` so `importlib.resources.files(...)` has something real to resolve against.

**When to use:** Any time build-tooling files (migrations, non-Python data) must ship inside a
package but are deliberately kept outside `src/` in the working tree for CLI ergonomics
(`alembic revision --autogenerate` from repo root).

**Example — directly adapted from the consumer's own verified, already-shipped fix:**
```toml
# pyproject.toml
[tool.hatch.build.targets.wheel]
packages = ["src/availability_engine"]

[tool.hatch.build.targets.wheel.force-include]
"alembic.ini" = "availability_engine/_migrations/alembic.ini"
"alembic" = "availability_engine/_migrations/alembic"
```
```python
# src/availability_engine/_migrations/__init__.py
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
```python
# src/availability_engine/migrations.py
"""Programmatic Alembic script_location resolver (D-05).

Consumer usage:
    from alembic.config import Config
    from alembic import command
    from availability_engine.migrations import get_script_location

    cfg = Config()
    cfg.set_main_option("script_location", str(get_script_location()))
    cfg.set_main_option("sqlalchemy.url", "<consumer's real DB URL>")
    command.upgrade(cfg, "head")
"""
from __future__ import annotations

from importlib.resources import files
from pathlib import Path

# Mirrors chatbot_engine/persistence/reconcile.py::_resolve_alembic_ini —
# same dual-layout resolution: installed wheel first, repo checkout fallback.
_REPO_ROOT = Path(__file__).resolve().parents[2]


def get_script_location() -> Path:
    """Resolve the Alembic ``script_location`` directory wherever it landed.

    1. Installed package: force-included under
       ``availability_engine._migrations/alembic`` -- resolved via
       ``importlib.resources`` so it works regardless of install location.
    2. Repo checkout (running tests from source): falls back to the
       repo-root ``alembic/`` directory.
    """
    packaged = files("availability_engine._migrations").joinpath("alembic")
    if packaged.is_dir():
        return Path(str(packaged))
    return _REPO_ROOT / "alembic"
```
Source: adapted from `SocialNetwork-Chatbot/pyproject.toml` lines 41-52 and
`SocialNetwork-Chatbot/src/chatbot_engine/persistence/reconcile.py::_resolve_alembic_ini`
(both read in full this session) `[VERIFIED: local sibling repo, same author, same pattern already shipped and tested]`.

### Pattern 2: safe async→sync bridge (D-04's "thin sync facade")

**What:** A background thread runs one persistent `asyncio` event loop for the lifetime of the
facade instance; every sync method dispatches its coroutine via
`asyncio.run_coroutine_threadsafe(coro, loop).result()`. This is safe to call from **any**
context, including from inside the caller's own already-running event loop — unlike
`asyncio.run()`, which raises if a loop is already running on the calling thread.

**When to use:** Exactly this situation — a synchronous ABC (`AvailabilityPort`) must be
satisfied by an async engine, and the caller (the consumer's `ConversationService`/
`BookingService`) is itself async and calls the port inline (not via `asyncio.to_thread`).

**Example:**
```python
# src/availability_engine/sync.py
"""Thin synchronous facade over AvailabilityEngine (D-04).

Runs the async engine on a dedicated background thread with its own
persistent event loop, dispatched via run_coroutine_threadsafe. This is
deliberately NOT `asyncio.run()` per call: `asyncio.run()` raises
`RuntimeError: asyncio.run() cannot be called from a running event loop`
the first time this facade is invoked from inside a caller that is ITSELF
async and calls this sync API inline (exactly the consumer's documented
calling convention -- see the consumer's `availability/port.py` docstring:
"[the booking core] calls this sync, in-process port inline ... would wrap
it in asyncio.to_thread only if a genuinely blocking real adapter ever
lands" -- i.e. the bridge is this engine's responsibility, not the
caller's).
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any

from availability_engine.contracts import AvailabilityResult, Booking, Hold, Resource, UtcDatetime
from availability_engine.engine import AvailabilityEngine
from availability_engine.storage.protocol import StorageBackend


class SyncAvailabilityEngine:
    def __init__(self, storage: StorageBackend) -> None:
        self._engine = AvailabilityEngine(storage)
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._ready.wait()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        self._loop.run_forever()

    def _call(self, coro: Any) -> Any:
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    def define_resource(self, resource: Resource) -> None:
        self._call(self._engine.define_resource(resource))

    def get_availability(
        self, resource_id: str, start: UtcDatetime, end: UtcDatetime
    ) -> AvailabilityResult:
        return self._call(self._engine.get_availability(resource_id, start, end))

    def place_hold(
        self, resource_id: str, slot_start: UtcDatetime, slot_end: UtcDatetime,
        ttl_seconds: int, idempotency_key: str | None = None,
    ) -> Hold:
        return self._call(
            self._engine.place_hold(resource_id, slot_start, slot_end, ttl_seconds, idempotency_key)
        )

    def confirm_hold(
        self, hold_id: str, payload: dict[str, Any], idempotency_key: str | None = None
    ) -> Booking:
        return self._call(self._engine.confirm_hold(hold_id, payload, idempotency_key))

    def release_hold(self, hold_id: str) -> None:
        self._call(self._engine.release_hold(hold_id))

    def cancel_booking(self, booking_id: str) -> None:
        self._call(self._engine.cancel_booking(booking_id))

    def close(self) -> None:
        """Stop the background loop cleanly -- call at consumer shutdown."""
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
```
Pattern source: `[CITED: https://death.andgravity.com/asyncio-bridge]` (persistent background-thread
loop + `run_coroutine_threadsafe`, with the startup-race and clean-shutdown caveats this example
implements) and `[CITED: https://docs.python.org/3/library/asyncio-eventloop.html]` (`run_coroutine_threadsafe` is the documented thread-safe cross-thread scheduling primitive). Class shape (which
engine methods to wrap) is `[VERIFIED: src/availability_engine/engine.py:27-136]` — every
`AvailabilityEngine` public method read in full this session; the sync facade wraps exactly those
six methods (`define_resource`, `get_availability`, `place_hold`, `confirm_hold`, `release_hold`,
`cancel_booking`).

### Pattern 3: example adapter kept outside `src/`, subclassing the consumer's ABC

**What:** The `AvailabilityPort`-conforming class imports `chatbot_engine.availability.port` and
therefore MUST live in `examples/` (or `tests/`), never in `src/availability_engine/`, so the
shipped wheel never has an import-time or structural dependency on the consumer.

**Example (illustrative — planner fills in exact exception/uuid mapping from D-03 above):**
```python
# examples/chatbot_adapter.py
"""Reference AvailabilityPort adapter — NOT part of the installed package.

Demonstrates satisfying the consumer's synchronous AvailabilityPort contract
using this engine's SyncAvailabilityEngine (D-04). A real consumer either
copies this file into their own composition root (mirroring
consumers/escaperoom/build_runtime.py's single-import swap-point pattern) or
imports it directly if this engine later decides to ship it as an optional
extra -- NOT done in v1 (see Open Questions).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from availability_engine import (
    CapacityExhaustedError,
    HoldExpiredError,
    HoldNotFoundError,
    IdempotencyConflictError,
    OutsideHoursError,
)
from availability_engine.sync import SyncAvailabilityEngine

from chatbot_engine.availability.port import (
    AvailabilityPort,
    Booking as ConsumerBooking,
    Hold as ConsumerHold,
    HoldConflict,
    HoldExpired,
    Slot as ConsumerSlot,
    SlotUnavailable,
)


class AvailabilityEngineAdapter(AvailabilityPort):
    def __init__(self, engine: SyncAvailabilityEngine) -> None:
        self._engine = engine

    def query_availability(
        self, resource_type: str, window: tuple[datetime, datetime], party_size: int
    ) -> list[ConsumerSlot]:
        result = self._engine.get_availability(resource_type, window[0], window[1])
        return [
            ConsumerSlot(
                slot_id=f"{s.resource_id}:{s.start.isoformat()}",
                resource_id=s.resource_id,
                starts_at=s.start,
                ends_at=s.end,
                capacity=s.remaining,
            )
            for s in result.available
            if s.remaining >= party_size
        ]

    def place_hold(self, slot_id: str, ttl_seconds: int, idempotency_key: str) -> ConsumerHold:
        resource_id, start_iso = slot_id.split(":", 1)
        start = datetime.fromisoformat(start_iso)
        # end computed from the resource's slot_duration in a real implementation
        try:
            hold = self._engine.place_hold(
                resource_id, start, start, ttl_seconds, idempotency_key=idempotency_key
            )
        except (CapacityExhaustedError, OutsideHoursError) as exc:
            raise SlotUnavailable(str(exc)) from exc
        except IdempotencyConflictError as exc:
            raise HoldConflict(str(exc)) from exc
        return ConsumerHold(hold_id=hold.id, slot_id=slot_id, expires_at=hold.expires_at)

    def confirm_hold(self, hold_id: str, details: dict[str, str]) -> ConsumerBooking:
        try:
            booking = self._engine.confirm_hold(hold_id, dict(details))
        except HoldExpiredError as exc:
            raise HoldExpired(str(exc)) from exc
        except HoldNotFoundError as exc:
            raise HoldExpired(str(exc)) from exc
        return ConsumerBooking(
            booking_id=booking.id,
            slot_id=f"{booking.resource_id}:{booking.slot_start.isoformat()}",
            confirmation_ref=str(uuid.uuid4()),
        )

    def cancel(self, ref: str) -> None:
        try:
            self._engine.cancel_booking(ref)
        except Exception:
            pass  # AvailabilityPort.cancel is a no-oracle idempotent no-op
```
`[ASSUMED]` — this snippet is illustrative scaffolding written this session to demonstrate the
mapping shape, not verified against a real end-to-end test run; the `slot_id` encoding scheme,
`release_hold`/timeout race between `place_hold`'s `HoldConflict` semantics (same-slot-key replay
vs different-slot-key conflict — the consumer's port has *richer* idempotency semantics than the
engine's `IdempotencyConflictError` alone expresses) and `confirm_hold`'s double-confirm-returns-same-
booking replay behavior all need concrete design work at plan/execution time, informed by running
the actual `AvailabilityContractSuite` against a first draft. Flag for `checkpoint:human-verify`
or at minimum a dedicated plan-review pass before treating this mapping as final.

### Anti-Patterns to Avoid

- **`asyncio.run()` per sync-facade call:** works in every manual/interactive test, then raises
  `RuntimeError: asyncio.run() cannot be called from a running event loop` the first time it's
  called from inside the consumer's real async runtime. See Pattern 2 and Common Pitfalls.
- **Putting `AvailabilityPort`-importing code inside `src/availability_engine/`:** even if it only
  fails at import time for users without `chatbot_engine` installed, it structurally violates the
  locked one-way dependency rule and makes the wheel's import graph nondeterministic depending on
  what else happens to be installed.
- **Assuming `hatchling`'s `packages` list also handles non-Python files outside `src/`:** it does
  not — `packages`/`only-include` only reach into declared source trees; `force-include` is the
  only mechanism for pulling in files that live entirely outside them.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|--------------|-----|
| Wheel-content verification | A manual `python -m zipfile -l dist/*.whl` check run by hand before each release | A `tests/packaging/test_wheel_contains_migrations.py` assertion on `zipfile.ZipFile(wheel).namelist()`, run in CI | The consumer's own `tests/packaging/test_wheel_contains_both_packages.py` is the exact, already-proven template — CI catches a packaging regression the moment it's introduced, not at release time |
| Async→sync bridging | A bespoke `asyncio.run()`-based wrapper or manual thread-per-call pattern | The documented persistent-background-thread + `run_coroutine_threadsafe` pattern (Pattern 2) | This is a well-known, previously-solved problem with documented pitfalls (thread startup races, `asyncio.run()`-inside-a-running-loop failures); reinventing it under time pressure risks shipping a facade that silently deadlocks or crashes under the consumer's real (async) calling convention |
| Alembic script-location resolution | A hardcoded, repo-relative path | `importlib.resources.files(...)`-based dual-layout resolver (installed-package path first, repo-checkout fallback second) | The consumer's own `_resolve_alembic_ini` already solved exactly this problem and is a verified, working reference implementation — re-deriving it risks reintroducing the bug it fixed (CR-01) |

**Key insight:** every non-trivial piece of "new" work in this phase — force-include syntax, the
async/sync bridge, the migration-path resolver, the wheel-smoke-test shape — has already been
solved once in this exact local ecosystem (the sibling consumer repo) or is a well-documented
general Python pattern. The risk in this phase is re-deriving a worse version of an
already-verified solution under release-deadline pressure, not a lack of prior art.

## Common Pitfalls

### Pitfall 1: The wheel silently omits the migrations (CONFIRMED, reproduced this session)
**What goes wrong:** `uv add git+... --tag v0.1.0` succeeds, `import availability_engine` works,
but `alembic upgrade head` (using the packaged migration path) has no migrations to find — the
consumer's schema bootstrap silently does nothing or errors.
**Why it happens:** `packages = ["src/availability_engine"]` only packages that one src tree; the
repo-root `alembic/` directory is invisible to hatchling's default file selection.
**How to avoid:** `force-include` (Pattern 1) + a wheel-content assertion test in CI.
**Warning signs:** `[VERIFIED: this session — ran `uv build --out-dir <tmp>` against the current
repo state and inspected the wheel with `python3 -m zipfile -l`; the resulting namelist contains
`availability_engine/*.py` and `availability_engine/storage/**` but zero `alembic` entries]` — this
is not hypothetical, it is the current, reproducible state of the repo as of this research session.

### Pitfall 2: `py.typed` marker is currently missing (the sibling repo already hit this exact bug)
**What goes wrong:** A consumer running `mypy` against their own code that imports
`availability_engine` gets `import-untyped` errors for every `availability_engine.*` import,
even though the library is fully typed and passes `mypy --strict` internally — PEP 561 requires an
explicit `py.typed` marker file shipped inside the package for a type checker to trust its inline
types once installed as a third-party dependency.
**Why it happens:** No marker file exists yet: `[VERIFIED: find src/availability_engine -iname
py.typed → no output]`.
**How to avoid:** Add an empty `src/availability_engine/py.typed` file. Because the existing
`packages = ["src/availability_engine"]` already includes the whole directory tree, no additional
`pyproject.toml` change is needed — confirmed by the consumer's own fix, which touched only the
marker file and one test, no `pyproject.toml` edit `[VERIFIED: git show f77687c --stat in the
SocialNetwork-Chatbot repo]`.
**Warning signs:** `mypy` treats `availability_engine` imports as untyped in a fresh consumer
project; this is silent until someone actually runs a type checker against real consumer code.

### Pitfall 3: `asyncio.run()`-based sync facade crashes under the consumer's real calling convention
**What goes wrong:** The sync facade works in every manual smoke test (a plain script, a
synchronous pytest test) and then raises `RuntimeError: asyncio.run() cannot be called from a
running event loop` the moment the consumer's actual async `ConversationService`/`BookingService`
calls it inline.
**Why it happens:** The consumer's own `AvailabilityPort` docstring documents that its async
booking core calls this sync port "inline," anticipating `asyncio.to_thread` only "if a genuinely
blocking real adapter ever lands" — i.e. the consumer's calling code assumes the port itself is
safe to call from within its own running loop `[VERIFIED: SocialNetwork-Chatbot/src/chatbot_engine/
availability/port.py lines 9-11, read in full this session]`.
**How to avoid:** Pattern 2 (background-thread persistent loop + `run_coroutine_threadsafe`), never
`asyncio.run()` inside the facade's hot path.
**Warning signs:** Passes in isolation; fails only once wired into the consumer's real, async
composition root — exactly the kind of bug a wheel-level or unit-level test won't catch, only an
integration test that actually calls the adapter from inside a running event loop will.

### Pitfall 4: the consumer's `AvailabilityContractSuite` tag isn't pushed anywhere
**What goes wrong:** `uv add "socialnetwork-chatbot @ git+<url>" --tag v1.0 --group dev` fails to
resolve, because `uv` needs to fetch that ref from a real git remote.
**Why it happens:** The `SocialNetwork-Chatbot` repo currently has **no `git remote` configured at
all** `[VERIFIED: git remote -v in that repo returned nothing; git branch -a shows only local
`master`]`, even though it does have a local tag `v1.0` `[VERIFIED: git tag -l in that repo returned
`v1.0`]`. By contrast, this repo (`availability-engine`) already has a live GitHub remote
(`https://github.com/Ygaray/availability-engine.git`) `[VERIFIED: git remote -v in this repo]`,
matching what the consumer's own commented-out `pyproject.toml` seam already expects.
**How to avoid:** This is a cross-repo, human-owned prerequisite: the consumer repo needs a GitHub
remote created and the `v1.0` tag (or whatever tag actually carries `AvailabilityContractSuite`)
pushed to it before the dev-dependency in this repo's `pyproject.toml` can resolve. Flag as a
`checkpoint:human-verify` / blocking task early in the plan, not discovered late during `uv sync`.
**Warning signs:** `uv add`/`uv sync` fails with a git fetch error referencing the consumer's URL.

### Pitfall 5: `hatchling`'s `packages` collapses the shipped path — don't also add `only-include`
**What goes wrong:** Combining `packages = ["src/availability_engine"]` with a separate,
overlapping `only-include`/`sources` entry for the same tree either double-declares the same
config (harmless but confusing) or, if paths don't match exactly, silently changes what gets
collapsed into the wheel root.
**Why it happens:** `packages` is documented as sugar for
`only-include = [...] + sources = ["src"]` — mixing raw `only-include`/`sources` with `packages`
targeting the same directory is redundant and a likely source of subtle path mistakes.
**How to avoid:** Keep the existing `packages = ["src/availability_engine"]` line unchanged; add
**only** the new `force-include` table for the migrations — don't touch `only-include`/`sources`.
**Warning signs:** wheel namelist has an unexpected top-level `src/` prefix, or the package
directory structure doesn't collapse the way `import availability_engine` expects.

### Pitfall 6: order-of-operations — packaging must be fixed and verified in the tagged commit
**What goes wrong:** Cutting `v0.1.0` before the packaging fix lands means the consumer's git-tag
pin resolves to a broken wheel forever (tags are meant to be immutable) — a re-tag or a `v0.1.1`
becomes necessary immediately.
**Why it happens:** `uv add git+... --tag v0.1.0` builds the wheel from the exact tagged commit's
`pyproject.toml`, not from a later fix on `master`.
**How to avoid:** Sequence the plan so that packaging (force-include, `py.typed`), the sync facade,
the wheel-smoke-test, and the conformance-suite pass ALL land and are verified green BEFORE the
`v0.1.0` tag is created and pushed. PKG-03 (cut the tag) must be the last task, gated on the others.
**Warning signs:** N/A — this is a sequencing risk, not a runtime symptom; catching it requires
plan-time ordering discipline, not a test.

## Code Examples

Verified patterns from local, already-shipped, first-party sources:

### Wheel-smoke-install-and-migrate test (direct template)
```python
# tests/packaging/test_bootstrap_installed_wheel.py
# Adapted from SocialNetwork-Chatbot/tests/packaging/test_bootstrap_installed_wheel.py
# (read in full this session — reused near-verbatim, swapping bootstrap_booking_core
# for a direct alembic upgrade + `import availability_engine` check).
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    shutil.which("uv") is None, reason="uv is required to build/install the wheel under test"
)

_CHECK_SCRIPT = '''
import availability_engine

assert "site-packages" in availability_engine.__file__, (
    f"expected the installed wheel's site-packages copy, got "
    f"{availability_engine.__file__!r}"
)

from alembic import command
from alembic.config import Config
from availability_engine.migrations import get_script_location

cfg = Config()
cfg.set_main_option("script_location", str(get_script_location()))
cfg.set_main_option("sqlalchemy.url", "sqlite+aiosqlite:///./smoke_migrate.db")
command.upgrade(cfg, "head")
print("MIGRATE_OK")
'''


def _run(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    assert result.returncode == 0, (
        f"command {cmd} failed (exit {result.returncode})\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return result


def test_migration_bootstraps_from_installed_wheel(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    _run(["uv", "build", "--wheel", "-o", str(dist_dir)], cwd=_REPO_ROOT)
    wheels = sorted(dist_dir.glob("*.whl"))
    assert len(wheels) == 1, f"expected exactly one built wheel, found {wheels}"

    venv_dir = tmp_path / "venv"
    _run(["uv", "venv", str(venv_dir), "--python", sys.executable])
    venv_python = venv_dir / "bin" / "python"

    _run(["uv", "pip", "install", "--python", str(venv_python), str(wheels[0])])

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    script_path = run_dir / "check_bootstrap.py"
    script_path.write_text(_CHECK_SCRIPT)

    result = _run([str(venv_python), str(script_path)], cwd=run_dir)
    assert "MIGRATE_OK" in result.stdout
```

### Wheel-content namelist assertion (direct template)
```python
# tests/packaging/test_wheel_contains_migrations.py
# Adapted from SocialNetwork-Chatbot/tests/packaging/test_wheel_contains_both_packages.py
from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    shutil.which("uv") is None, reason="uv is required to build the wheel under test"
)


def test_built_wheel_contains_migrations(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    result = subprocess.run(
        ["uv", "build", "--wheel", "-o", str(dist_dir)],
        capture_output=True, text=True, cwd=_REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr

    wheels = sorted(dist_dir.glob("*.whl"))
    assert len(wheels) == 1

    with zipfile.ZipFile(wheels[0]) as zf:
        names = zf.namelist()

    assert "availability_engine/py.typed" in names, f"py.typed missing; namelist={names}"
    assert any(
        n.startswith("availability_engine/_migrations/alembic/") for n in names
    ), f"migrations not force-included; namelist={names}"
    assert "availability_engine/_migrations/alembic/env.py" in names
    assert any(
        n.startswith("availability_engine/_migrations/alembic/versions/") for n in names
    ), f"migration versions missing; namelist={names}"
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|-------------------|---------------|--------|
| `setuptools`/`setup.py` manual `MANIFEST.in` for non-Python file inclusion | `hatchling`'s declarative `[tool.hatch.build.targets.wheel.force-include]` | Already this project's convention (Phase 1 build-system choice) | No `MANIFEST.in` needed; force-include is the modern equivalent for this exact class of problem |
| PyPI-published releases with SemVer + PyPI trove classifiers | Git-tag-pinned distribution (`uv add git+... --tag`) with no PyPI publish step | This is this ecosystem's established model (`YahirReusableBot` convention, per this repo's own README) | "Release" here means: packaging verified + tag pushed, not `twine upload`. Verified no PyPI-specific tooling (`twine`, `build`+`twine`) exists in either repo's dependency set. |

**Deprecated/outdated:** N/A — no deprecated APIs in scope for this phase's actual work.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|----------------|
| A1 | The example adapter's exact field-mapping code (Pattern 3's `chatbot_adapter.py` snippet) — particularly `slot_id` encoding, the `place_hold`/`confirm_hold` idempotency-replay semantics gap between the engine's `IdempotencyConflictError` and the consumer's richer same-slot-replay-vs-different-slot-conflict distinction, and `cancel`'s tri-token (`hold_id`/`booking_id`/`confirmation_ref`) resolution — is illustrative scaffolding, not a tested design. | Architecture Patterns, Pattern 3 | Medium — the conformance suite (D-02) will fail against a naive first draft of this mapping; expect at least one plan-review or execution-time iteration before `AvailabilityContractSuite` passes fully. Not a blocker to planning, but the plan should budget a verification/iteration loop here rather than treating the mapping as a single mechanical task. |
| A2 | Recommending README-only docs (no `docs/` site) is the right call for this phase | Standard Stack, Alternatives Considered | Low — grounded in verified absence of any `docs/` convention in either sibling repo; if the human wants a docs site later, that's an easy post-v1 addition, not a breaking change to reverse. |
| A3 | Whether to add a `CHANGELOG.md` at all is undecided — no ecosystem precedent found in either repo | Recommended Project Structure | Low — purely a discretion item per CONTEXT.md; the planner can decide either way without contract or correctness impact. |
| A4 | `socialnetwork-chatbot`'s exact PyPI-style distribution name for `uv add "<name> @ git+..."` — inferred from `[project] name = "socialnetwork-chatbot"` in its `pyproject.toml`, not confirmed by an actual successful `uv add` dry run against it in this session (blocked by Pitfall 4's missing remote) | Standard Stack, Installation | Low — the name is read directly from the consumer's own `pyproject.toml` `[project]` table, so it should be correct, but the actual `uv add` was not executed end-to-end this session because the tag isn't pushed to a remote yet. |

**If this table is empty:** N/A — see rows above.

## Open Questions

1. **Is the consumer's `v1.0` tag the right one to pin `AvailabilityContractSuite` to, or does a
   more specific tag exist for when that suite was frozen?**
   - What we know: the consumer repo has exactly one tag, `v1.0`, and `AvailabilityContractSuite`
     is present at `HEAD` `[VERIFIED: git tag -l + file read this session]`.
   - What's unclear: whether `v1.0` is stable/final for the consumer's own purposes, or whether a
     `v1.0.1`/`v1.1` is expected before this engine's release — the consumer's own milestone
     history (`docs: add retrospective for v1.0`, `chore: archive v1.0 milestone files`) suggests
     `v1.0` is a genuinely closed, archived milestone, which is a good sign.
   - Recommendation: pin to `v1.0` explicitly (not `main`), matching D-02's own instruction; treat
     re-pinning as a normal, low-risk maintenance bump if the consumer later tags something newer.

2. **Does the consumer repo need a GitHub remote created and `v1.0` pushed as a prerequisite task
   in THIS phase's plan, or is that entirely out of this repo's control/scope?**
   - What we know: `availability-engine` already has a live remote at
     `github.com/Ygaray/availability-engine.git`; the consumer does not have any remote configured.
   - What's unclear: whether creating/pushing to the consumer's remote is something the planner
     should schedule as a cross-repo task in this phase, or whether it's assumed to already be
     handled outside this GSD project's scope by the time this phase executes.
   - Recommendation: surface this explicitly as a blocking `checkpoint:human-verify` task early in
     the plan — "confirm SocialNetwork-Chatbot has a pushed remote + tag before adding the dev
     dependency" — rather than letting `uv sync` fail unexplained mid-execution.

3. **Should the example adapter (`examples/chatbot_adapter.py`) be considered part of this
   library's supported surface (documented, tested indefinitely) or a one-time proof artifact?**
   - What we know: CONTEXT.md's Integration Points note says "the tag, the conformance subclass,
     and the sync facade are the hand-off surface" — the adapter itself isn't listed as a
     long-term-supported artifact, only as this phase's proof mechanism.
   - What's unclear: whether the consumer will literally copy this file into their own repo
     (matching `build_runtime.py`'s single-swap-point pattern) or whether it stays purely as this
     repo's own conformance-test fixture.
   - Recommendation: keep it in `examples/` (documented in the README as "reference
     implementation"), covered by the conformance suite in CI, but don't over-invest in making it
     a polished, separately-versioned public API — that's explicitly not what D-04's "thin sync
     facade lives in this repo" decision asked for (the *facade* is the supported surface; the
     *adapter* is a worked example).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|--------------|-----------|---------|-----------|
| `uv` | wheel build, venv smoke test, git-tag dev dependency | ✓ | 0.11.19 `[VERIFIED: uv --version]` | — |
| `docker` | not required for this phase's own new tests (SQLite is sufficient for the wheel-smoke test); Postgres migration bootstrap is already proven by Phase 4's `test_migrations.py` | ✓ (daemon running) `[VERIFIED: docker info succeeded]` | 29.1.3 | N/A — only needed if the planner chooses to also re-run the Postgres migration path against the *installed wheel* specifically (recommended as a stretch, not required — Phase 4 already proves migrations work against the repo checkout) |
| Consumer repo git remote (`SocialNetwork-Chatbot`) | D-02 conformance dependency (`uv add ... --tag v1.0`) | ✗ (no remote configured) `[VERIFIED: git remote -v in that repo returned nothing]` | — | None — this is a genuine cross-repo blocker; must be resolved (push a remote + the tag) before the dev-dependency can be added. See Open Questions #2. |

**Missing dependencies with no fallback:**
- Consumer repo remote + pushed tag — blocks D-02's conformance dev-dependency until resolved.

**Missing dependencies with fallback:**
- None beyond the above.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | `pytest` 9.1.1 + `pytest-asyncio` 1.4.0 (`asyncio_mode = "auto"`) `[VERIFIED: pyproject.toml]` |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `uv run pytest tests/packaging/ -x` (packaging-only, ~seconds once wheel-caching warm) |
| Full suite command | `uv run pytest` (114 tests collected today `[VERIFIED: uv run pytest --collect-only -q]`, plus this phase's additions) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|---------------------|--------------|
| PKG-01 | Wheel installs via git-tag pin, migrations bootstrap from the installed wheel | integration (subprocess: build+venv+install) | `uv run pytest tests/packaging/test_bootstrap_installed_wheel.py -x` | ❌ Wave 0 |
| PKG-01 | Wheel namelist contains `py.typed` and the force-included migration tree | integration (subprocess: build+zip inspect) | `uv run pytest tests/packaging/test_wheel_contains_migrations.py -x` | ❌ Wave 0 |
| PKG-01 | Sync facade is safe to call from inside an already-running event loop | unit/integration | `uv run pytest tests/test_sync_facade.py -x` | ❌ Wave 0 |
| PKG-02 | `AvailabilityResult` JSON schema still matches the committed golden file (regression guard for any doc example drift) | unit (existing) | `uv run pytest tests/test_contract_conformance.py -x` | ✅ (Phase 2) |
| PKG-02 | README code examples actually run against the real API (no doctest drift) | manual / doc-example smoke script, not automated in CI this phase | N/A — recommend a `checkpoint:human-verify` reading pass rather than a doctest harness, given phase scope | N/A |
| PKG-03 | Example adapter satisfies the consumer's full `AvailabilityContractSuite` | integration (dev-only, cross-repo) | `uv run pytest tests/integration/test_chatbot_conformance.py -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/packaging/ tests/test_sync_facade.py -x` (fast subset touching this phase's new code)
- **Per wave merge:** `uv run pytest` (full suite, including the cross-repo conformance suite once the dev dependency resolves)
- **Phase gate:** Full suite green, INCLUDING the wheel-smoke-install test and the conformance suite, BEFORE tagging `v0.1.0` (see Pitfall 6 — tag immutability makes this non-negotiable)

### Wave 0 Gaps
- [ ] `tests/packaging/test_wheel_contains_migrations.py` — covers PKG-01
- [ ] `tests/packaging/test_bootstrap_installed_wheel.py` — covers PKG-01
- [ ] `tests/test_sync_facade.py` — covers PKG-01/D-04 (a dedicated test that calls the sync facade
      FROM INSIDE a running event loop via `asyncio.run(async_caller())` where `async_caller`
      invokes a sync-facade method — this is the one test that actually proves Pitfall 3 is fixed,
      not just that the facade works when called from plain sync code)
- [ ] `tests/integration/test_chatbot_conformance.py` — covers D-02/PKG-03 (blocked on the Open
      Questions #2 remote/tag prerequisite)
- [ ] Framework install: none — `pytest`/`pytest-asyncio` already present; no new test framework
      dependency needed

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|----------------|---------|--------------------|
| V2 Authentication | No | This phase adds no auth surface |
| V3 Session Management | No | N/A |
| V4 Access Control | Indirectly | The example adapter re-derives the same "opaque id as bearer capability token" pattern the consumer's own `port.py` already documents (uuid4 ids, no separate auth layer) — the adapter must preserve uuid4-only id generation, never a predictable id, matching the existing engine's own id generation in `storage/sql/store.py`/`storage/memory.py` (already established, not new to this phase) |
| V5 Input Validation | Indirectly | The sync facade and adapter must not weaken the engine's existing Pydantic-validated `UtcDatetime` boundary (`_require_utc` in `contracts.py`) — the sync facade wraps calls but must not accept or produce naive datetimes at its own boundary |
| V6 Cryptography | No | No new cryptographic surface in this phase |

### Known Threat Patterns for this phase's stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|------------------------|
| Consumer payload leaking into logs/exception messages via the new adapter | Information Disclosure | The engine's own `errors.py` already documents and enforces "never accept or store a payload argument" in exception constructors (T-01-01) — the example adapter must not introduce a new code path that logs or interpolates `payload`/`details` dicts into exception messages or log lines |
| Force-included build artifacts accidentally shipping unintended files (e.g. `.pyc`, local dev config) | Tampering / Information Disclosure | `force-include` maps exact declared sources only — the wheel-content namelist test (Code Examples) is the concrete guard against an over-broad glob accidentally including unwanted files |
| The sync facade's background thread leaking across process forks or not shutting down cleanly, holding a stale event loop | Denial of Service (resource exhaustion in long-running consumer processes) | Explicit `close()` method (Pattern 2) using `loop.call_soon_threadsafe(loop.stop)` + `thread.join()`; document that consumers using the sync facade in a long-lived process must call `close()` at shutdown |

## Sources

### Primary (HIGH confidence)
- `src/availability_engine/{contracts.py,errors.py,engine.py,time.py,__init__.py}` — read in full this session (the frozen contract this phase documents)
- `src/availability_engine/storage/protocol.py` — read in full this session
- `alembic.ini`, `alembic/env.py`, `tests/test_migrations.py` — read in full this session (current migration layout + existing bootstrap-verification pattern)
- `pyproject.toml` (this repo) — read in full this session
- `uv build` executed against this repo this session, wheel inspected via `python3 -m zipfile -l` — directly reproduces the packaging bug described in CONTEXT.md
- `SocialNetwork-Chatbot/pyproject.toml`, `.../src/chatbot_engine/persistence/reconcile.py`, `.../src/chatbot_engine/_alembic/__init__.py`, `.../src/chatbot_engine/availability/port.py`, `.../src/chatbot_engine/availability/testing/contract.py`, `.../src/consumers/escaperoom/build_runtime.py`, `.../tests/packaging/test_bootstrap_installed_wheel.py`, `.../tests/packaging/test_wheel_contains_both_packages.py`, `.../tests/packaging/test_core_imports_without_api.py` — all read in full this session (the sibling repo's already-proven templates for every hard part of this phase)
- `git remote -v` / `git tag -l` in both repos — run this session, confirmed the remote/tag mismatch (Pitfall 4)
- `git log`/`git show` in the consumer repo — confirmed the `py.typed` fix history (Pitfall 2)

### Secondary (MEDIUM confidence)
- [Build configuration - Hatch](https://hatch.pypa.io/latest/config/build/) — `force-include` and `packages` exact TOML syntax
- [hatch-vcs README](https://github.com/ofek/hatch-vcs/blob/master/README.md) — dynamic-versioning shape, not adopted (see Alternatives Considered)
- [uv: Managing dependencies](https://docs.astral.sh/uv/concepts/projects/dependencies/) — git-tag source + dependency-groups syntax
- [Event loop — Python docs](https://docs.python.org/3/library/asyncio-eventloop.html) — `run_coroutine_threadsafe` documented behavior and thread-safety caveats
- [Running async code from sync code in Python — death and gravity](https://death.andgravity.com/asyncio-bridge) — the background-thread bridge pattern, pitfalls (asyncio.run() failures, startup race, shutdown ordering)

### Tertiary (LOW confidence)
- General web-search summaries on PEP 735 dependency-groups and git-tag-pin "release" conventions — used only for framing, not for any load-bearing syntax claim (all syntax claims are cross-checked against the Secondary sources above or this repo's own verified `pyproject.toml`/wheel contents)

## Metadata

**Confidence breakdown:**
- Packaging fix (force-include, py.typed, script-location resolver): HIGH — directly reproduced the bug this session and have a verified, already-shipped template from the sibling repo
- Sync facade / async-bridge design: HIGH on the pattern itself (well-documented, cross-checked against two independent sources), MEDIUM on the exact method-wrapping code (written this session, not yet executed/tested)
- Example adapter field mapping: MEDIUM — grounded in the frozen contract types (verified) but the exact idempotency/id-mapping edge cases are `[ASSUMED]` scaffolding (see Assumptions Log A1)
- Docs structure recommendation: HIGH — grounded in verified absence of any competing convention in this ecosystem
- Release/tag process: HIGH on the mechanics, MEDIUM on the cross-repo remote prerequisite (a real, unresolved blocker — see Open Questions #2)

**Research date:** 2026-09-04
**Valid until:** 30 days (stable packaging tooling; the cross-repo remote/tag state (Pitfall 4) should be re-verified immediately before execution, as it may change independently of this research)
