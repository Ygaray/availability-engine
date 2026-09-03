# Phase 1: End-to-End Walking Skeleton (In-Memory) - Pattern Map

**Mapped:** 2026-09-03
**Files analyzed:** 13 (from RESEARCH.md "Recommended Project Structure")
**Analogs found:** 0 / 13

## No Codebase Analogs Exist

This is the **first implementation phase of a brand-new project**. Confirmed via full
repository scan (`find` across the working tree, excluding `.git/`): the only files
present are `.planning/` docs, `graphify-out/` (a code-graph tool's cache, not source),
`.claude/CLAUDE.md`, and `README.md`. There is no `src/`, no `tests/`, and no prior
Python module anywhere in this repo to copy patterns from.

**Consequence for the planner:** every file in this phase is a **new-from-scratch**
file. There is no "closest existing analog" step to perform. Do not invent a fake
analog — instead follow the two things below as the ground truth for conventions and
code shape.

## File Classification

| New File | Role | Data Flow | Analog | Match Quality |
|----------|------|-----------|--------|----------------|
| `pyproject.toml` | config | n/a | none | no analog (greenfield) |
| `src/availability_engine/__init__.py` | config (package export) | n/a | none | no analog |
| `src/availability_engine/contracts.py` | model | request-response (boundary validation) | none | no analog |
| `src/availability_engine/errors.py` | utility | n/a | none | no analog |
| `src/availability_engine/time.py` | utility | transform | none | no analog |
| `src/availability_engine/core/intervals.py` | utility | transform | none | no analog |
| `src/availability_engine/core/availability.py` | service | transform | none | no analog |
| `src/availability_engine/core/grid.py` | service | transform | none | no analog |
| `src/availability_engine/storage/protocol.py` | model (interface) | CRUD | none | no analog |
| `src/availability_engine/storage/memory.py` | service (storage impl) | CRUD | none | no analog |
| `src/availability_engine/engine.py` | service (facade) | request-response | none | no analog |
| `tests/conftest.py` | test | n/a | none | no analog |
| `tests/storage/contract_suite.py` | test | CRUD | none | no analog |

## Ground Truth #1: Reusable-Ecosystem Conventions (from `.claude/CLAUDE.md`)

The project's own CLAUDE.md is the closest thing to a "pattern source" available and
is authoritative over anything invented here:

- **Build backend / packaging:** `uv` + `hatchling`, matching the reusable-ecosystem
  convention so downstream consumers can `uv add --pin` this package by git tag.
- **Layout:** `src/` layout (`src/availability_engine/...`), not a flat top-level
  package — this is what makes hatchling's default wheel-building + git-tag pinning
  work cleanly for consumers.
- **Dependency direction:** one-way only — this package must never import or name
  anything from a consumer (e.g. the parallel chatbot backend). No file in this phase
  should reference consumer-specific concepts.
- **Async storage protocol:** the `StorageBackend` interface and anything that calls
  it must be `async def`, even in the in-memory Phase 1 implementation — the project
  locks async now so a later SQL backend (Phase 4) doesn't change the shape.
- **UTC-internal, TZ-aware from day one:** never use naive `datetime` or
  `datetime.utcnow()` anywhere; always `datetime.now(timezone.utc)`. `zoneinfo` is the
  only timezone import, and it must be confined to the boundary (`time.py`), never
  imported inside `core/`.
- **Two-tier type system (this phase's explicit decision, D-01):** Pydantic v2
  (`BaseModel`, `ConfigDict(frozen=True)`) for public boundary types in `contracts.py`;
  stdlib `@dataclass(frozen=True, slots=True)` for engine-internal value objects
  (`core/intervals.py`'s `Interval`, internal `Slot`/`Hold` state). Do not use Pydantic
  for internal-only objects that never cross the public boundary — that's an explicit
  anti-pattern per the project's STACK.md rationale (perf + unneeded validation
  overhead in hot loops like grid generation).
- **Strict tooling from commit 1 (D-05):** `ruff` + `mypy --strict` on `src/`.

## Ground Truth #2: RESEARCH.md Code Examples (use verbatim as starting shape)

RESEARCH.md (`.planning/phases/01-.../01-RESEARCH.md`) contains fully worked code
examples the planner should treat as the primary pattern source per file, since no
codebase alternative exists:

| File | Pattern source in RESEARCH.md | What to copy |
|------|-------------------------------|---------------|
| `contracts.py` | "Pattern 1: Pydantic v2 boundary type rejecting naive datetimes, enforcing UTC" (lines ~179-211) + "Resource contract" code block (lines ~337-385) + "`AvailabilityResult` output contract" block (lines ~410-439) | `UtcDatetime` Annotated type + `_require_utc` validator; `Resource`/`LocalInterval`/`Weekday` shape; `PublicSlot`/`SlotStatus`/`AvailabilityResult` shape. All use `model_config = ConfigDict(frozen=True)`. |
| `storage/protocol.py` | "Pattern 2: Coarse-grained async `StorageBackend` Protocol" (lines ~213-258) | Full `Protocol` class with `@runtime_checkable`, exact method signatures including reserved `payload`/`idempotency_key` kwargs — copy verbatim, this is a frozen one-way contract (D-04). |
| `storage/memory.py` | "Pattern 3: `asyncio.Lock`-guarded dict-of-lists in-memory store" (lines ~260-287) | `@dataclass` store with a single `asyncio.Lock`; check-and-write for `place_hold` must happen inside one `async with self._lock:` block with no intervening `await` (closes TOCTOU per Pitfall 1). |
| `engine.py` | "Facade signatures" code block (lines ~387-408) | `AvailabilityEngine.__init__(self, storage: StorageBackend)` + the five async facade methods — signatures are frozen (D-04), do not add a `payload` param to the facade's `place_hold`. |
| `errors.py` | Referenced throughout (Pattern 2 docstrings, Anti-Patterns, Security Domain table) but no single code block given | Minimal exception set: `CapacityExhaustedError`, `HoldExpiredError`, `HoldNotFoundError`. Plain Python exception classes (no special base needed for Phase 1); keep opaque `payload` out of exception messages entirely (Security Domain: Information Disclosure mitigation). |
| `time.py` | Architectural Responsibility Map row "Local wall-clock → UTC conversion" + `localize_operating_hours()` reference in the System Architecture Diagram | Only file allowed to import `zoneinfo`; exposes `localize_operating_hours(resource, date_range)` and a `require_utc()` guard function for raw-datetime internal call sites. |
| `core/intervals.py` | Architectural Responsibility Map + Don't-Hand-Roll table | Frozen dataclass `Interval(start, end)` half-open `[start, end)`, `slots=True`; overlap/merge helpers; zero I/O, zero tz-awareness. |
| `core/availability.py` | System Architecture Diagram step `free_fragments(hours, busy, capacity)` + "Pitfall: over-scoping" section | Build the sweep-line primitive's shape now but scope Phase 1's own logic/tests to capacity ≥ 1 straightforward cases only — do not implement Phase 2's capacity-K property tests here. |
| `core/grid.py` | System Architecture Diagram step `grid_slots(fragments, slot_duration)` + Open Question #1 resolution | `grid_slots()` fixed-duration overlay; per Open Question #1's resolution, buffer IS functionally applied in Phase 1 grid generation (not just a schema field) — use the "effective occupied interval" pattern (buffer owned by preceding booking's trailing edge). |
| `tests/storage/contract_suite.py` | Validation Architecture section, "Recommended Project Structure" comment | Shared async parametrized suite, parametrized only over `[InMemoryStore]` in Phase 1, structured so Phase 4 can add `SQLStore` to the parametrize list without rewriting test bodies. |
| `pyproject.toml` / `tests/conftest.py` | "Wave 0 Gaps" checklist (end of RESEARCH.md) | `[tool.pytest.ini_options]` with `asyncio_mode = "auto"`; pytest-asyncio 1.4.0 syntax (no `event_loop` fixture — use `@pytest_asyncio.fixture(loop_scope=...)` if needed); canary `async def test_canary()` test first. |

## Shared Patterns

### UTC enforcement
**Source:** RESEARCH.md Pattern 1 (`_require_utc` validator + `UtcDatetime` Annotated type)
**Apply to:** every `datetime` field in `contracts.py`, and every raw-`datetime`
function parameter in `time.py`/`core/` that isn't already Pydantic-typed (via a
shared `require_utc()` guard, not duplicated ad hoc checks — Don't-Hand-Roll table).

### Async, coarse-grained, atomic storage boundary
**Source:** RESEARCH.md Pattern 2 (`StorageBackend` Protocol) + Pattern 3 (`InMemoryStore`)
**Apply to:** `storage/protocol.py`, `storage/memory.py`, and every call site in
`engine.py` — the engine facade never takes a lock itself; atomicity lives entirely
behind the Protocol (STORE-01 structural rule).

### Domain exception convention
**Source:** RESEARCH.md Security Domain table + Architectural Responsibility Map
**Apply to:** `errors.py` now (`CapacityExhaustedError`, `HoldExpiredError`,
`HoldNotFoundError`), establishing the pattern Phase 4's SQL backend will reuse to
wrap driver exceptions.

## No Analog Found

All 13 files — see rationale above. This is expected and correct for a Phase 1
walking skeleton in a brand-new repository; do not treat this as a gap to escalate.

## Metadata

**Analog search scope:** entire working tree (`find . -not -path '*/.git/*' -type f`)
**Files scanned:** all non-`.git` files in the repo (confirmed: only `.planning/`,
`.claude/`, `graphify-out/`, `README.md` exist — no `src/` or `tests/`)
**Pattern extraction date:** 2026-09-03
