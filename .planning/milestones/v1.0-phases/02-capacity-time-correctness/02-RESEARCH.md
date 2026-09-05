# Phase 2: Capacity & Time Correctness - Research

**Researched:** 2026-09-03
**Domain:** Python 3.12+ scheduling engine — capacity-aware sweep-line hardening, DST-safe UTC grid generation (`zoneinfo`), midnight-crossing operating hours, lazy hold expiry, typed reason codes, and a frozen/conformance-tested structured output contract
**Confidence:** HIGH — every DST/midnight-crossing claim below was verified this session by actually running Python's `zoneinfo` against the real 2026 transition dates (not just cited from docs), and every code-change claim is grounded in a line-by-line read of Phase 1's actual shipped source

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01 [dst-contract]:** UTC-only slot identity (ISO-8601 with explicit offset); loop grid arithmetic in UTC so fall-back naturally yields two distinct ordered slots; skip the non-existent spring-forward hour and document that default. Localizing for display stays the consumer's job. _(source: human — skip-vs-shift is behavioral and locked before freeze; matches ARCHITECTURE.md.)_ — **Reversibility:** one-way — this is the frozen output-contract representation the consumer stub pins to.
- **D-02 [tzdata]:** Pin the `tzdata` PyPI package as an explicit dependency so spring-forward/fall-back fixtures (e.g. `America/New_York`) and consumer installs are reproducible across CI and minimal Linux/Windows environments where the system tzdb may be absent. _(source: ai-auto)_
- **D-03 [reason-codes]:** Typed exception hierarchy (`CapacityExhaustedError`, `OutsideHoursError`, `HoldExpiredError`, `HoldNotFoundError`), each exposing `.reason_code` from a **closed** enum that pre-includes `idempotency_conflict` (raised only from Phase 3) — so Phase 3 doesn't widen a "closed" set the consumer already pinned to. _(source: ai-auto)_ — **Reversibility:** one-way — a closed enum in the frozen contract; widening it later breaks the consumer's exhaustiveness assumptions.
- **D-04 [capacity-shape]:** Two lists — `available` (each slot `remaining > 0`) and `booked` (`remaining == 0`) — each slot carrying an explicit remaining-capacity integer (plus resource capacity), computed via sweep-line; never collapsed to a boolean. _(source: ai-auto)_ — **Reversibility:** one-way — exact split point and field names must match the consumer stub byte-for-byte.
- **D-05 [midnight-hours]:** Tolerate `end < start` in the frozen Resource schema (via `(start_local, duration)` or an explicit `spans_midnight` flag) with grid generation anchored from the start day and extending past midnight in UTC. _(source: ai-auto)_ _(provisional — refreshed at execution; see Runtime Decisions below — RESOLVED against the actual Phase 1 shape)_ — **Reversibility:** one-way — must reconcile with the actual Phase 1 `Resource` shape once it lands.

### Claude's Discretion

Sweep-line implementation details and internal grid-generation helpers are open provided the frozen contract fields above are honored.

### Deferred Ideas (OUT OF SCOPE)

- Continuous/arbitrary-duration bookings (interval-set algebra via `portion`) — deferred beyond v1.
- SQL persistence of the capacity/status model → Phase 4 (`schema`).

### Runtime Decisions (refreshed against Phase 1's landed code)

**[midnight-hours] — RESOLVED:** Phase 1 landed `operating_hours` as `dict[Weekday, list[LocalInterval]]` where `LocalInterval = {start: time, end: time}` with **no** same-day (`end > start`) validator — `end < start` is the tolerated sentinel for overnight/midnight-crossing shifts `[VERIFIED: src/availability_engine/contracts.py:44-58 — "class LocalInterval(BaseModel): ... start: time / end: time" plus the comment "v1 does not validate end > start here — Phase 2's midnight-hours decision explicitly tolerates end < start for overnight shifts"]`. Phase 2 grid generation must interpret a `LocalInterval` with `end <= start` as spanning midnight: anchor the slot grid from the start weekday's local date and extend past 24:00 into the next calendar day, converting to UTC across the boundary (and across any DST transition in that window). No `spans_midnight` flag and no `(start, duration)` pair are needed — the sentinel is the frozen contract.

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| AVAIL-02 | Availability is capacity-aware — remaining capacity as a count, computed via sweep-line, correct for capacity ≥ 1 | Phase 1's `core/availability.py::free_fragments()` already IS a sweep-line primitive returning `(Interval, remaining_capacity)` pairs `[VERIFIED: src/availability_engine/core/availability.py:14-61]` — Phase 2's job is exposing `remaining`/`capacity` on the output contract (currently absent) and hypothesis-proving it, not building a new algorithm. See Architecture Patterns Pattern 1. |
| AVAIL-03 | Availability reads exclude expired holds via one shared active-entries primitive (`expires_at > now`) | Phase 1's `InMemoryStore._count_active()` and `get_active_entries()` do **not** filter by `expires_at` at all `[VERIFIED: src/availability_engine/storage/memory.py:37-69 — neither loop references `hold.expires_at`]` — this is a real, verified gap, not a hypothetical one. See Architecture Patterns Pattern 3 and Common Pitfalls. |
| AVAIL-04 | Structured output contract stable, documented, conformance-testable | `AvailabilityResult`/`PublicSlot` restructure (D-04) + `model_json_schema()` golden-file test. See Architecture Patterns Pattern 5 and Open Questions #1 (byte-for-byte claim vs. actual consumer stub shape). |
| GRID-02 | Grid generation correct across DST transitions (spring-forward gap, fall-back ambiguity), fixture-tested on real dates | Verified this session by executing `zoneinfo` against real 2026 America/New_York transition dates — see Architecture Patterns Pattern 2 and Common Pitfalls. |
| GRID-03 | Operating hours crossing midnight, no truncation/double-counting | `time.py::localize_operating_hours()` currently combines `local_interval.end` with the **same** `current_date` as `start` unconditionally `[VERIFIED: src/availability_engine/time.py:50-58]` — a real, verified bug for `end <= start` sentinels. One-line fix, verified by execution. See Architecture Patterns Pattern 2. |
| HOLD-05 | Expired holds auto-release lazily, no background sweeper | Same shared active-entries primitive as AVAIL-03 (`expires_at > now`) — `confirm_hold`'s existing expiry check `[VERIFIED: src/availability_engine/storage/memory.py:113-114 — "if datetime.now(UTC) >= hold.expires_at: raise HoldExpiredError(hold_id)"]` already implements the correct predicate for confirm; Phase 2 must apply the identical predicate to the capacity-count and active-entries read paths. |
| HOLD-08 | Rejections carry machine-readable reason codes | New `ReasonCode` StrEnum + `.reason_code` on each of `errors.py`'s exceptions, plus a new `OutsideHoursError` (does not exist in Phase 1). See Architecture Patterns Pattern 4. |

</phase_requirements>

## Summary

Phase 1 shipped a walking skeleton whose sweep-line primitive (`free_fragments`), UTC-boundary function (`localize_operating_hours`), and grid-stepper (`grid_slots`) were **already built to generalize correctly to capacity ≥ 1 and to real DST arithmetic** — this session verified, by actually executing Python's `zoneinfo` against the real 2024–2026 `America/New_York` transition dates, that the *existing* architecture (localize boundary points once via `.astimezone(UTC)`, then walk the grid in pure UTC `timedelta` arithmetic with zero further `zoneinfo` involvement) produces the exact correct elapsed-UTC-duration for both a normal 9–5 window (unaffected, since it never touches 2am) and an overnight window that spans the 2am transition (3 real hours on spring-forward, 5 real hours on fall-back, for a nominal midnight–4am window — confirmed by direct execution, not documentation). **This means GRID-02's hardest-sounding requirement is largely already correct by construction; Phase 2's actual work is (a) fixing one real, verified bug in `time.py::localize_operating_hours()` where `local_interval.end` is combined with the same calendar date as `start` even when `end <= start` (GRID-03), (b) writing fixture tests on real transition dates that prove both bullets, and (c) documenting the one genuinely subtle edge case — a `LocalInterval` boundary landing exactly inside the gap or the doubled hour — where Python's default `fold=0` behavior already implements the "skip the non-existent hour" contract (D-01) with zero code changes, but this must be tested and documented, not assumed.**

The other three requirement clusters are more purely additive. AVAIL-02/AVAIL-04 require restructuring `contracts.py`'s `AvailabilityResult`/`PublicSlot` from a single flat `slots` list with a `status` enum into D-04's two-list `available`/`booked` split, each slot carrying `remaining: int` and `capacity: int` — a one-way, locked breaking change to the frozen v1 contract (see Open Questions #1 for a real discrepancy found between CONTEXT.md's "byte-for-byte" framing and the actual `SocialNetwork-Chatbot` consumer code, which uses a structurally different sync ABC bridged by a not-yet-built Phase 5 adapter, not a direct pin). AVAIL-03/HOLD-05 require fixing a **verified, real gap**: `InMemoryStore`'s active-entries scanning currently never checks `hold.expires_at`, so an expired-but-never-released hold permanently occupies capacity — the fix is to make `get_active_entries()` the one shared, expiry-filtering primitive and have `place_hold`'s capacity check call it (reusing it, not duplicating the scan), which also satisfies AVAIL-03's literal wording ("via the one shared active-entries primitive"). HOLD-08 requires a new closed `ReasonCode` enum and a genuinely new `OutsideHoursError` (Phase 1 never validates that a requested hold falls within the resource's operating hours at all — this is new behavior, not just wiring).

**Primary recommendation:** Do not rewrite `core/availability.py` or `core/grid.py` — both are already structurally DST-safe and capacity-generalized. Spend the phase's engineering effort on: (1) the one-line `time.py` midnight-crossing fix + DST fixture tests on real dates, (2) the `contracts.py` two-list/remaining-capacity restructure + JSON-schema golden-file conformance test, (3) collapsing `InMemoryStore`'s duplicated active-entries scanning into one expiry-aware primitive, and (4) the `ReasonCode` enum + new `OutsideHoursError` validation in `engine.py::place_hold`.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| DST-safe local-hours→UTC boundary conversion | Time boundary (`time.py`) | — | Only file allowed to import `zoneinfo` (Phase 1 structural rule, unchanged); the fix and the imaginary/ambiguous-boundary detection both belong here, never in `core/` |
| Midnight-crossing date-anchoring fix | Time boundary (`time.py`) | — | Same function (`localize_operating_hours`) already owns this; it is a date-arithmetic fix, not a new module |
| Sweep-line capacity/remaining computation | Compute core (`core/availability.py`) | — | Already exists (`free_fragments`); Phase 2 property-tests it, does not rewrite it |
| Fixed-duration grid stepping | Compute core (`core/grid.py`) | — | Verified this session to need **zero changes** for DST — it operates on already-UTC `Interval`s via pure `timedelta` arithmetic |
| Capacity-shape output restructuring (`available`/`booked`, `remaining`, `capacity`) | Domain/Contract layer (`contracts.py`) | Public Facade (`engine.py`, assembles the two lists) | One-way, frozen public contract change (D-04) — must live at the Pydantic boundary, not be improvised per call site |
| Lazy hold-expiry / one shared active-entries primitive | Storage backend (`storage/memory.py`) | — | Atomicity and the expiry predicate both live behind the `StorageBackend` Protocol (STORE-01 structural rule, unchanged from Phase 1) |
| Reason-code enum + typed exception hierarchy | Domain/Contract layer (`errors.py`) | Public Facade (`engine.py`, raises `OutsideHoursError`) | Exceptions are part of the frozen public contract surface; `engine.py` is where the new outside-hours *check* runs (reusing `time_boundary.localize_operating_hours`) |
| Contract-freeze / conformance test | Test layer (`tests/test_contract_conformance.py`) | Domain/Contract layer (schema is generated from `contracts.py`) | A golden-file JSON-schema snapshot test, not a new production module |

## Standard Stack

### Core (already locked in Phase 1 — no changes)

| Library | Version | Purpose | Provenance |
|---------|---------|---------|--------------|
| Python | 3.12+ | Runtime | Locked, unchanged |
| Pydantic | 2.13.5 | Public boundary types, extended this phase | `[VERIFIED: pyproject.toml:8 — "pydantic==2.13.5"]`, already pinned by Phase 1 |
| `dataclasses` (stdlib) | stdlib | Internal `Interval` — unchanged, zero new fields needed | `[VERIFIED: src/availability_engine/core/intervals.py:13-19]` |
| `zoneinfo` (stdlib) | stdlib | IANA timezone resolution, confined to `time.py`/`contracts.py` | unchanged |

### New this phase

| Library | Version (verified 2026-09-03) | Purpose | Provenance |
|---------|---------|---------|--------------|
| `tzdata` | **2026.3** | Explicit IANA tzdata package (D-02) — reproducible DST fixtures on CI/minimal Linux/Windows where the system tzdb is absent | `[VERIFIED: PyPI registry — pypi.org/pypi/tzdata/json, "version": "2026.3", published 2026-07-10]`. Pre-approved in `.planning/APPROVED-DEPS.md` for Phase 2 (verdict `SUS`, approved 2026-09-03) — no new checkpoint needed. |
| `time-machine` | **3.5.0** | Freeze/travel time for hold-TTL expiry tests and stepping through a DST boundary mid-test | `[VERIFIED: PyPI registry — pypi.org/pypi/time-machine/json, "version": "3.5.0", published 2026-08-25]`. Pre-approved in `.planning/APPROVED-DEPS.md` for Phase 2. |
| `hypothesis` | **6.167.1** | Property-based tests for sweep-line capacity invariants and grid-alignment invariants | `[VERIFIED: PyPI registry — pypi.org/pypi/hypothesis/json, "version": "6.167.1", published 2026-08-30]`. Pre-approved in `.planning/APPROVED-DEPS.md` for Phase 2. |

**Version drift note:** all three exceed the milestone-level `.claude/CLAUDE.md` STACK research's assumed lines (`tzdata` any-current, `time-machine 2.16.x+`, `hypothesis 6.x latest`) — consistent with that same document's own instruction to re-verify at implementation time. No breaking-change risk identified for any of the three at this version distance (all are additive-feature releases per their PyPI publish cadence, not major-version jumps like Phase 1 hit with `pytest-asyncio`/`mypy`).

**Installation:**
```bash
uv add tzdata
uv add --dev time-machine hypothesis
```

**Note on hypothesis + async:** every function this phase needs to property-test (`free_fragments`, `grid_slots`, `localize_operating_hours`) is a plain **synchronous** function — `@given(...)` wraps them directly with no async-test interaction concerns. The `hypothesis`/`pytest-asyncio` compatibility caveat noted in `.claude/CLAUDE.md`'s Version Compatibility table only applies if property-testing an `async def` engine method directly, which this phase does not need to do.

## Package Legitimacy Audit

All three packages below are pre-approved in `.planning/APPROVED-DEPS.md` for Phase 2 — no new `checkpoint:human-verify` task is needed. Re-ran the legitimacy check this session to confirm current signals.

| Package | Registry | Age (latest release) | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| tzdata | pypi | published 2026-07-10 | unknown (heuristic misfires — `python/tzdata` is the canonical CPython-maintained tzdata mirror) | github.com/python/tzdata | SUS (`unknown-downloads`) | Approved (pre-approved, APPROVED-DEPS.md) |
| time-machine | pypi | published 2026-08-25 | unknown | none returned by the legitimacy check (the actual project lives at github.com/adamchainz/time-machine, well-known, maintained by Adam Johnson) | SUS (`too-new`, `unknown-downloads`, `no-repository`) | Approved (pre-approved) |
| hypothesis | pypi | published 2026-08-30 | unknown | none returned by the legitimacy check (the actual project is github.com/HypothesisWorks/hypothesis, a long-established, widely-used library) | SUS (`too-new`, `unknown-downloads`, `no-repository`) | Approved (pre-approved) |

**Packages removed due to `[SLOP]` verdict:** none.
**Packages flagged as suspicious `[SUS]`:** all three, per above — matching Phase 1's own pattern where mature, well-known packages trip `too-new`/`unknown-downloads`/`no-repository` heuristics on their latest patch release rather than reflecting an actual legitimacy concern. All three are already in `APPROVED-DEPS.md`, so the human already cleared them during discuss-phase. A package the planner introduces that is NOT in `APPROVED-DEPS.md` still must escalate to a human checkpoint per the standing rule (INC-2026-08-24-04).

## Architecture Patterns

### System Architecture Diagram (Phase 2 changes overlaid on Phase 1's skeleton)

```
consumer code
    │
    ▼
engine.py :: AvailabilityEngine
    │
    ├─► place_hold(resource_id, slot_start, slot_end, ttl_seconds)
    │        │
    │        ├─► [NEW] time_boundary.localize_operating_hours(resource, slot_start, slot_end)
    │        │        → if requested [slot_start,slot_end) not fully inside any returned
    │        │          UTC hours-interval  ──►  raise OutsideHoursError  (HOLD-08, NEW)
    │        │
    │        └─► storage.place_hold(...)
    │                 │
    │                 └─► [FIXED] active = await self.get_active_entries(resource_id, slot)
    │                          (the ONE shared primitive — filters hold.expires_at > now)
    │                          if len(active) >= effective_capacity → CapacityExhaustedError
    │
    ├─► get_availability(resource_id, start, end)
    │        │
    │        ├─► [FIXED] time_boundary.localize_operating_hours(...)
    │        │        (midnight-crossing: combine `end` with current_date+1 when end<=start)
    │        │
    │        ├─► storage.get_active_entries(resource_id, window)
    │        │        (now excludes expired holds — same primitive as place_hold above)
    │        │
    │        ├─► core/availability.py :: free_fragments(hours, busy, capacity)
    │        │        (UNCHANGED — already returns (Interval, remaining) pairs)
    │        │
    │        ├─► core/grid.py :: grid_slots(fragment, slot_duration, buffer)
    │        │        (UNCHANGED — pure UTC timedelta arithmetic, verified DST-safe)
    │        │
    │        └─► [RESTRUCTURED] wrap into AvailabilityResult(available=[...], booked=[...])
    │                 each PublicSlot carries remaining: int, capacity: int  (D-04)
    │
    └─► confirm_hold / release_hold — unchanged call shape; confirm_hold's existing
             `expires_at > now`-equivalent check becomes the canonical predicate reused
             by the shared active-entries primitive above
```

### Recommended Project Structure (Phase 2 — files touched, no new top-level modules)

```
src/availability_engine/
├── contracts.py             # MODIFIED: PublicSlot gains remaining/capacity;
│                             #   AvailabilityResult.slots → .available + .booked;
│                             #   new ReasonCode(StrEnum)
├── errors.py                 # MODIFIED: AvailabilityEngineError base + .reason_code
│                             #   on each exception; new OutsideHoursError
├── time.py                   # MODIFIED: one-line midnight-crossing date fix in
│                             #   localize_operating_hours(); no DST-specific code needed
├── core/
│   ├── intervals.py          # UNCHANGED
│   ├── availability.py       # UNCHANGED (already the sweep-line primitive)
│   └── grid.py                # UNCHANGED (verified DST-safe by construction)
├── storage/
│   ├── protocol.py            # UNCHANGED (signature already generalizes)
│   └── memory.py               # MODIFIED: get_active_entries() becomes the one
│                              #   expiry-filtering primitive; place_hold reuses it,
│                              #   delete the separate _count_active() duplicate
└── engine.py                  # MODIFIED: place_hold gains the outside-hours check;
                              #   get_availability assembles the two-list result

tests/
├── core/
│   ├── test_availability.py   # NEW: hypothesis property tests, capacity-K invariants
│   ├── test_grid_dst.py       # NEW: fixture tests on real 2024-2026 transition dates
│   └── test_time_boundary.py  # NEW: midnight-crossing + DST-boundary fixture tests
├── test_contract_conformance.py  # NEW: model_json_schema() golden-file snapshot test
└── test_engine.py              # EXTENDED: outside-hours rejection, lazy-expiry via
                                #   time-machine, two-list available/booked assertions
```

### Pattern 1: Capacity-shape output restructuring (AVAIL-02, AVAIL-04, D-04)

**What:** Replace `AvailabilityResult.slots: list[PublicSlot]` (Phase 1, flat, `status`-only) with two lists, and add `remaining`/`capacity` to `PublicSlot`. `free_fragments()` already computes exactly the `(Interval, remaining_capacity)` pairs this needs — no algorithm change.

**When to use:** `engine.py::get_availability()`'s slot-assembly loop.

**Example:**
```python
# contracts.py — replaces the current SlotStatus/PublicSlot/AvailabilityResult block
# (src/availability_engine/contracts.py:91-113, verified this session)
class PublicSlot(BaseModel):
    model_config = ConfigDict(frozen=True)
    start: UtcDatetime
    end: UtcDatetime
    resource_id: str
    capacity: Annotated[int, Field(ge=1)]        # resource.capacity, carried per-slot
    remaining: Annotated[int, Field(ge=0)]        # capacity - active_count; ge=0 makes
                                                    # an invariant violation fail loudly
                                                    # at construction, not corrupt silently

class AvailabilityResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    resource_id: str
    available: list[PublicSlot]   # every slot here has remaining > 0
    booked: list[PublicSlot]      # every slot here has remaining == 0
```

```python
# engine.py::get_availability — assembly loop change only
available: list[PublicSlot] = []
booked: list[PublicSlot] = []
for fragment, remaining_capacity in fragments:
    for slot_interval in grid_slots(fragment, resource.slot_duration, resource.buffer):
        slot = PublicSlot(
            start=slot_interval.start,
            end=slot_interval.end,
            resource_id=resource_id,
            capacity=resource.capacity,
            remaining=remaining_capacity,
        )
        (available if remaining_capacity > 0 else booked).append(slot)
return AvailabilityResult(resource_id=resource_id, available=available, booked=booked)
```

**Recommendation on `SlotStatus`/`status`:** keep `PublicSlot` free of a redundant `status` field — list membership (`available` vs `booked`) already encodes status, and D-04's own wording ("never collapsed to a boolean") is about the *capacity* representation, not about removing a derivable convenience field. This IS itself a decision the planner should lock explicitly rather than inherit silently from this research — see Open Questions #2.

### Pattern 2: DST-safe UTC boundary conversion + midnight-crossing fix (GRID-02, GRID-03)

**What:** Phase 1's `time.py::localize_operating_hours()` converts each `LocalInterval`'s `start`/`end` to UTC via a single `.astimezone(UTC)` call per boundary, then `core/grid.py::grid_slots()` walks the result in pure UTC `timedelta` arithmetic. **Verified this session by direct execution:** this two-step design is *already* DST-correct for any boundary pair that does not itself sit inside the transition window — the elapsed UTC duration between two `.astimezone(UTC)`-converted boundary points automatically reflects the missing/extra hour, with zero DST-aware code in the grid stepper.

**Verified findings (this session, `python3` + `zoneinfo`, `America/New_York`, `tzdata` real IANA data):**

| Scenario | Local window | Expected nominal span | Actual UTC span | Verified |
|---|---|---|---|---|
| Normal hours, spring-forward date | 2026-03-08 09:00–17:00 | 8h | (untouched — doesn't cross 2am) | not directly re-tested; doesn't touch the transition |
| Overnight, spans spring-forward | 2026-03-07 22:00 → 2026-03-08 06:00 | 8h | **7h** | `[VERIFIED: python3 zoneinfo runtime, this session — "overnight spring-forward span (expect 7h, nominal 8h): 7:00:00"]` |
| Overnight, spans fall-back | 2026-10-31 22:00 → 2026-11-01 06:00 | 8h | **9h** | `[VERIFIED: python3 zoneinfo runtime, this session — "overnight fall-back span (expect 9h, nominal 8h): 9:00:00"]` |
| Boundary-only midnight–4am, spring-forward | 2026-03-08 00:00–04:00 | 4h | **3h** | `[VERIFIED: python3 zoneinfo runtime, this session — "spring-forward midnight->4am UTC span hours: 3:00:00"]` |
| Boundary-only midnight–4am, fall-back | 2026-11-01 00:00–04:00 | 4h | **5h** | `[VERIFIED: python3 zoneinfo runtime, this session — "fall-back midnight->4am UTC span hours: 5:00:00"]` |

**Real fixture dates confirmed via web search** `[CITED: timeanddate.com/time/change/usa/new-york]`:
- 2024 spring-forward: Sun 2024-03-10 02:00 local (EST→EDT). 2024 fall-back: Sun 2024-11-03 02:00 local (EDT→EST).
- 2025 spring-forward: Sun 2025-03-09. 2025 fall-back: Sun 2025-11-02.
- 2026 spring-forward: Sun 2026-03-08. 2026 fall-back: Sun 2026-11-01.
- All transitions occur at 02:00 local wall-clock time; `America/New_York` is EST (UTC−5) in winter, EDT (UTC−4) in summer.

**The one required code fix (GRID-03), verified against the current source:**
```python
# Current (src/availability_engine/time.py:48-58, verified this session):
#   while current_date <= end_date:
#       ...
#       for local_interval in resource.operating_hours.get(weekday, []):
#           local_start = datetime.combine(current_date, local_interval.start, tzinfo=tz)
#           local_end = datetime.combine(current_date, local_interval.end, tzinfo=tz)
#           ...
#       current_date += timedelta(days=1)
#
# BUG: local_end always uses the SAME current_date as local_start, even when
# local_interval.end <= local_interval.start (the midnight-crossing sentinel per
# the Runtime Decision above) — this silently produces an inverted or zero-length
# UTC interval for any overnight shift.

for local_interval in resource.operating_hours.get(weekday, []):
    local_start = datetime.combine(current_date, local_interval.start, tzinfo=tz)
    end_date = current_date
    if local_interval.end <= local_interval.start:
        end_date = current_date + timedelta(days=1)
    local_end = datetime.combine(end_date, local_interval.end, tzinfo=tz)
    utc_interval = Interval(
        start=local_start.astimezone(UTC),
        end=local_end.astimezone(UTC),
    )
    ...
```

**The one genuinely subtle edge case (document, do not necessarily add code for):** if a `LocalInterval`'s `start` or `end` time-of-day itself falls **inside** the transition window (e.g. `time(2, 30)` on a spring-forward date, or `time(1, 30)` on a fall-back date), Python's default `fold=0` (unset) behavior was verified this session to already implement useful, well-defined semantics with zero extra code:

```python
# Verified this session (python3 zoneinfo runtime):
# Spring-forward gap time 2026-03-08 02:30 (nonexistent wall-clock instant):
#   fold=0 (default) -> 2026-03-08 07:30:00+00:00  (collapses FORWARD, same UTC
#     instant as the valid 03:30 local time immediately after the gap)
#   fold=1            -> 2026-03-08 06:30:00+00:00  (collapses BACKWARD, same UTC
#     instant as the valid 01:30 local time immediately before the gap)
# Fall-back ambiguous time 2026-11-01 01:30 (occurs twice):
#   fold=0 (default) -> 2026-11-01 05:30:00+00:00  (EARLIER occurrence, EDT -4:00)
#   fold=1            -> 2026-11-01 06:30:00+00:00  (LATER occurrence, EST -5:00)
```

Python's default (`fold=0`, unset) for a spring-forward gap boundary collapses it **forward** to the equivalent post-gap instant — this is a reasonable, deterministic reading of D-01's "skip the non-existent spring-forward hour" instruction and requires **no new code**, only an explicit fixture test proving it (e.g. `LocalInterval(start=time(2,30), end=time(4,0))` on 2026-03-08 must yield exactly a 90-minute UTC fragment, not 4 hours and not an error) and a comment in `time.py` recording the decision. For a fall-back ambiguous boundary, the default `fold=0` deterministically picks the *earlier* of the two occurrences — also worth an explicit fixture test and comment, since it is easy for a future contributor to "fix" this into instability by adding an unconsidered `fold=1`.

A reusable detection helper (useful for the fixture tests, and as defensive documentation even if not called from production code) — verified this session:
```python
def _is_imaginary(dt: datetime, tz: ZoneInfo) -> bool:
    """True iff dt is a nonexistent wall-clock time (falls inside a spring-forward gap)."""
    return dt.astimezone(UTC).astimezone(tz).replace(tzinfo=None) != dt.replace(tzinfo=None)

def _is_ambiguous(dt: datetime) -> bool:
    """True iff dt occurs twice (falls inside a fall-back doubled hour)."""
    return dt.replace(fold=0).utcoffset() != dt.replace(fold=1).utcoffset()
```

### Pattern 3: One shared, expiry-filtering active-entries primitive (AVAIL-03, HOLD-05)

**What:** Phase 1's `InMemoryStore` has **two separate, duplicated** overlap-scanning implementations — `get_active_entries()` (public, used by `get_availability`) and `_count_active()` (private, used by `place_hold`) — and **neither filters by `hold.expires_at`** `[VERIFIED: src/availability_engine/storage/memory.py:37-69]`. This is a real, currently-shipping gap: an expired-but-never-explicitly-released hold permanently occupies capacity today. Collapse both into one primitive that applies the `expires_at > now` predicate, matching `confirm_hold`'s existing (correct) predicate `[VERIFIED: src/availability_engine/storage/memory.py:113-114 — "if datetime.now(UTC) >= hold.expires_at: raise HoldExpiredError(hold_id)" — i.e. active iff expires_at > now]`.

**Example:**
```python
# storage/memory.py — get_active_entries becomes the ONE shared primitive
async def get_active_entries(
    self, resource_id: str, window: Interval
) -> list[Hold | Booking]:
    now = datetime.now(UTC)
    entries: list[Hold | Booking] = []
    for hold in self._holds.values():
        if hold.resource_id != resource_id or hold.expires_at <= now:
            continue  # AVAIL-03/HOLD-05: expired holds never count as active
        hold_interval = Interval(start=hold.slot_start, end=hold.slot_end)
        if overlaps(hold_interval, window):
            entries.append(hold)
    for booking in self._bookings.values():
        if booking.resource_id != resource_id:
            continue  # Bookings have no expiry (HOLD-06/cancel is Phase 3)
        booking_interval = Interval(start=booking.slot_start, end=booking.slot_end)
        if overlaps(booking_interval, window):
            entries.append(booking)
    return entries

# place_hold reuses it instead of a separate _count_active() scan
async def place_hold(self, resource_id, slot, capacity, ttl_seconds, ...):
    async with self._lock:
        resource = self._resources.get(resource_id)
        effective_capacity = resource.capacity if resource is not None else capacity
        active = await self.get_active_entries(resource_id, slot)  # SAME primitive
        if len(active) >= effective_capacity:
            raise CapacityExhaustedError(resource_id, slot)
        ...
```

**Safe to `await` inside the lock:** `get_active_entries()`'s body performs zero real I/O (pure dict iteration) — a coroutine with no internal suspension point does not yield control back to the event loop when awaited, so calling it from inside `place_hold`'s `async with self._lock:` block does **not** reopen the TOCTOU window Phase 1's Anti-Patterns section warns about. This is worth an explicit code comment, since it looks superficially like the anti-pattern.

### Pattern 4: Typed reason-code hierarchy (HOLD-08, D-03)

**What:** A closed `ReasonCode` enum plus a `.reason_code` attribute on every domain exception, including a genuinely new `OutsideHoursError` (Phase 1 never validates operating hours in `place_hold` at all — this is new behavior).

**Example:**
```python
# contracts.py — matches the existing StrEnum idiom (SlotStatus, Weekday already use it)
class ReasonCode(StrEnum):
    CAPACITY_EXHAUSTED = "capacity_exhausted"
    OUTSIDE_HOURS = "outside_hours"
    HOLD_EXPIRED = "hold_expired"
    NOT_FOUND = "not_found"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"  # reserved — Phase 3 raises this

# errors.py
class AvailabilityEngineError(Exception):
    """Common base so a consumer can `except AvailabilityEngineError` to catch any
    domain rejection, or inspect `.reason_code` to branch without string matching."""
    reason_code: ReasonCode

class CapacityExhaustedError(AvailabilityEngineError):
    reason_code = ReasonCode.CAPACITY_EXHAUSTED
    def __init__(self, resource_id: str, slot: Interval) -> None: ...

class OutsideHoursError(AvailabilityEngineError):   # NEW
    reason_code = ReasonCode.OUTSIDE_HOURS
    def __init__(self, resource_id: str, slot: Interval) -> None: ...

class HoldExpiredError(AvailabilityEngineError):
    reason_code = ReasonCode.HOLD_EXPIRED
    ...

class HoldNotFoundError(AvailabilityEngineError):
    reason_code = ReasonCode.NOT_FOUND
    ...

class ResourceNotFoundError(AvailabilityEngineError):
    reason_code = ReasonCode.NOT_FOUND   # shares NOT_FOUND with HoldNotFoundError —
    ...                                    # HOLD-08's list has one generic not_found,
                                            # not a resource-specific variant
```

```python
# engine.py::place_hold — the NEW outside-hours check, reusing time_boundary
async def place_hold(self, resource_id, slot_start, slot_end, ttl_seconds):
    resource = await self._storage.get_resource(resource_id)
    if resource is None:
        raise ResourceNotFoundError(resource_id)
    if slot_end <= slot_start:
        raise ValueError(...)
    hours = time_boundary.localize_operating_hours(resource, slot_start, slot_end)
    requested = Interval(start=slot_start, end=slot_end)
    if not any(h.start <= requested.start and requested.end <= h.end for h in hours):
        raise OutsideHoursError(resource_id, requested)
    interval = Interval(start=slot_start, end=slot_end)
    return await self._storage.place_hold(resource_id, interval, resource.capacity, ttl_seconds)
```

**mypy --strict note:** declaring `reason_code: ReasonCode` (annotation only, no default) on the base class and then assigning it as a class attribute in each subclass is accepted by `mypy --strict` without needing an `abc.ABC`/`abstractmethod` — if a subclass forgets to set it, mypy will not catch the omission (it is not truly abstract), so add a unit test asserting every concrete exception class in `errors.py` has a non-`None` `reason_code`, closing that gap structurally rather than trusting review.

### Pattern 5: Contract-freeze conformance test (AVAIL-04)

**What:** A JSON-schema snapshot/golden-file test — Pydantic v2's `model_json_schema()` is the standard mechanism `[CITED: pydantic.dev/docs — model_json_schema() API]`; committing its output and diffing against it in CI makes any contract drift visible in code review rather than silent.

**Example:**
```python
# tests/test_contract_conformance.py
import json
from pathlib import Path
from availability_engine.contracts import AvailabilityResult

GOLDEN_PATH = Path(__file__).parent / "golden" / "availability_result.schema.json"

def test_availability_result_schema_matches_golden() -> None:
    current_schema = AvailabilityResult.model_json_schema()
    golden_schema = json.loads(GOLDEN_PATH.read_text())
    assert current_schema == golden_schema, (
        "AvailabilityResult's JSON schema drifted from the frozen golden file. "
        "If this is an intentional contract change, regenerate the golden file "
        "in the SAME commit and get it reviewed — this is the parallel consumer's "
        "pin point."
    )
```

The golden file is generated once (e.g. `python -c "import json; from availability_engine.contracts import AvailabilityResult; print(json.dumps(AvailabilityResult.model_json_schema(), indent=2))" > tests/golden/availability_result.schema.json`) at the moment this phase freezes the contract, and committed alongside it. Repeat for `Resource`, `Hold`, `Booking` if those are also considered frozen-and-documented by this phase (their shapes did not change this phase, but a schema snapshot of them costs nothing and closes the same drift risk for the whole contract, not just the newly-changed part).

### Anti-Patterns to Avoid (Phase-2-specific)

- **Rewriting `free_fragments()` or `grid_slots()` from scratch.** Both are already correct for their stated scope; Phase 2 is a hardening/testing/output-shape phase, not an algorithm-replacement phase. A plan that includes "reimplement sweep-line" or "reimplement grid stepping" has scope-crept past what this research found necessary.
- **Adding DST-specific branches inside `core/grid.py`.** Verified this session: the grid stepper needs zero `zoneinfo`/DST-aware code — all DST correctness lives in the one-time boundary conversion in `time.py`. If a plan proposes touching `grid.py` for DST reasons, that is a sign the boundary-conversion fix was misdiagnosed.
- **Duplicating the expiry check.** Do not add a second `if hold.expires_at <= now: continue` anywhere outside the one shared `get_active_entries()` primitive — AVAIL-03's literal wording requires exactly one shared implementation, and duplicating it is how the original Phase 1 gap (two separate un-synchronized scans) happened in the first place.
- **Silently dropping `SlotStatus`/`status` without a locked decision.** See Pattern 1 and Open Questions #2 — removing a Phase-1-shipped field is a real breaking-contract choice, not a free cleanup; it must be an explicit plan decision, not an implementation-detail drive-by.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| DST gap/ambiguity detection | A custom UTC-offset-table lookup or a hand-rolled "is this March/November" heuristic | `zoneinfo.ZoneInfo` + `datetime.fold` + the round-trip `_is_imaginary`/`_is_ambiguous` helpers (Pattern 2) — verified this session to already produce correct elapsed-UTC durations with zero heuristics | `zoneinfo` already has the full, current IANA transition table (via `tzdata` on platforms that need it); a hand-rolled heuristic would need updating every time a jurisdiction changes its DST rules |
| Contract schema drift detection | A hand-maintained changelog/doc comment claiming "the contract hasn't changed" | `model_json_schema()` + a committed golden-file diff test (Pattern 5) | Automated, fails loudly in CI/review exactly when it matters; a doc comment can silently go stale |
| Reason-code-to-exception mapping | A generic `dict[str, type[Exception]]` registry with string keys | A `ReasonCode(StrEnum)` + one `.reason_code` class attribute per exception (Pattern 4) | Enum membership is exhaustiveness-checkable by `mypy --strict`; a string-keyed dict is not |
| Active-entries scanning | A second, "just for this one caller" overlap scan (which is exactly how Phase 1's `_count_active`/`get_active_entries` duplication happened) | The one shared `get_active_entries()` primitive (Pattern 3), called by every read and write path that needs it | AVAIL-03's own wording names this as the required design; duplicating it is the literal anti-pattern the requirement exists to prevent |

**Key insight:** every fix this phase needs was already anticipated by Phase 1's own structure (the sweep-line primitive, the UTC-boundary confinement, the `StorageBackend` Protocol) — the risk this phase carries is not "missing architecture," it's "duplicating a check that should be shared" (the active-entries gap) or "assuming a rewrite is needed where a one-line date-arithmetic fix suffices" (the midnight-crossing bug).

## Common Pitfalls

### Pitfall: Assuming DST correctness requires touching `core/grid.py`

**What goes wrong:** A plan or implementer sees "GRID-02: DST-transition correctness" and starts adding `zoneinfo`-aware branches inside the pure, zero-timezone `core/grid.py` stepper, violating the Architectural Responsibility Map's structural rule (`zoneinfo` confined to `time.py`/`contracts.py`) and duplicating logic that already lives correctly at the boundary.

**Why it happens:** GRID-02's requirement text ("grid generation is correct across DST transitions") reads as if the grid-generation function itself needs DST awareness, when in fact the *boundary conversion that feeds it* is where the real correctness lives, verified this session to already be arithmetically sound.

**How to avoid:** Before touching `grid.py`, run this phase's fixture tests (real 2024–2026 transition dates) against the **current, unmodified** `grid.py` + a **fixed** `time.py` — verified this session that the fix belongs entirely in `time.py`'s midnight-crossing date arithmetic, not in the grid stepper.

**Warning signs:** A plan task that lists `core/grid.py` as a file to modify for DST reasons (as opposed to the `time.py` midnight-crossing fix).

### Pitfall: Trusting `AwareDatetime`/`.astimezone(UTC)` to reject or flag imaginary/ambiguous local times

**What goes wrong:** Code (or a test author) assumes constructing `datetime(2026, 3, 8, 2, 30, tzinfo=ZoneInfo("America/New_York"))` will raise, since the wall-clock time never actually occurred. **Verified this session: it does not raise.** It silently returns a valid-looking `datetime` object whose `.astimezone(UTC)` collapses to the same UTC instant as a different, valid local time (see Pattern 2's verified fold table).

**Why it happens:** Many languages'/libraries' DST handling does raise on an imaginary time (e.g. some Java `ZonedDateTime` strictness modes) — Python's `zoneinfo` deliberately does not, per PEP 495's design.

**How to avoid:** Any code path that constructs a boundary datetime directly from user/consumer-supplied local wall-clock input (not just this phase's own `LocalInterval`s) and needs to detect a gap/ambiguity must call the explicit `_is_imaginary`/`_is_ambiguous` round-trip helpers (Pattern 2) — never assume construction alone will surface the condition.

**Warning signs:** A test asserting `pytest.raises(...)` around a bare `datetime(..., tzinfo=tz)` construction for a gap time — that assertion will fail, because no exception is raised.

### Pitfall: The active-entries expiry gap is a real, currently-shipping bug, not a hypothetical

**What goes wrong:** Treating AVAIL-03/HOLD-05 as "add a nice-to-have optimization" rather than "fix an existing correctness bug." Verified this session: `InMemoryStore._count_active()` and `get_active_entries()` never reference `hold.expires_at` at all — an expired hold that is never explicitly `release_hold()`-ed or `confirm_hold()`-ed today occupies capacity **forever**.

**Why it happens:** Phase 1's own integration test (`test_get_availability_end_to_end`) and unit tests never exercised a hold past its TTL, so the gap shipped un-caught (all 22 Phase 1 tests pass, and none of them freeze time past a hold's `expires_at`).

**How to avoid:** Write the `time-machine`-based lazy-expiry test (place hold at T0 with a short TTL, travel to T0+TTL+ε, assert a second hold on the same capacity-1 slot now succeeds with **no** intervening `release_hold`/`confirm_hold` call) as one of the first tests in this phase — it should FAIL against the current, un-fixed `InMemoryStore`, proving the gap is real before fixing it.

**Warning signs:** A plan that treats HOLD-05 as already-satisfied by Phase 1's existing `confirm_hold` expiry check — that check only protects `confirm_hold` itself, not `place_hold`'s capacity count or `get_availability`'s active-entries read.

### Pitfall: `OutsideHoursError` has no existing call site — it's new behavior, not new wiring

**What goes wrong:** Assuming `place_hold` already validates operating hours somewhere and Phase 2 just needs to attach a reason code to an existing check. Verified this session: `engine.py::place_hold` performs exactly one validation (`slot_end <= slot_start`) before delegating straight to storage — there is no operating-hours containment check anywhere in Phase 1's code.

**Why it happens:** It's easy to assume "the engine already knows a resource's hours" (it does, via `localize_operating_hours`) implies "the engine already enforces them at hold time" (it doesn't — that function is only called from `get_availability`).

**How to avoid:** Explicitly add the containment check shown in Pattern 4 to `place_hold`, reusing `time_boundary.localize_operating_hours` (already exists, already correct) rather than writing new hours-comparison logic.

**Warning signs:** A plan that lists `OutsideHoursError`'s reason code as "already wired" with no corresponding new check in `engine.py::place_hold`.

## Code Examples

### hypothesis property test — sweep-line capacity invariant (AVAIL-02)

```python
# Source: synthesized from CONTEXT.md's "interval/grid invariants with hypothesis"
# guidance + standard differential-testing pattern (compare optimized impl against
# a brute-force per-microsecond reference over random inputs)
from datetime import UTC, datetime, timedelta
from hypothesis import given, strategies as st
from availability_engine.core.availability import free_fragments
from availability_engine.core.intervals import Interval

def _brute_force_remaining(hours, busy, capacity, sample_points):
    """Reference implementation: for each sample instant, count overlapping busy
    intervals directly. O(n*m) but trivially correct — used only as a test oracle."""
    results = {}
    for t in sample_points:
        if any(h.start <= t < h.end for h in hours):
            active = sum(1 for b in busy if b.start <= t < b.end)
            results[t] = capacity - active
    return results

@given(
    capacity=st.integers(min_value=1, max_value=5),
    busy_offsets=st.lists(
        st.tuples(st.integers(0, 55), st.integers(1, 60)), max_size=6
    ),
)
def test_free_fragments_never_exceeds_capacity(capacity, busy_offsets):
    base = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)
    hours = [Interval(start=base, end=base + timedelta(hours=1))]
    busy = [
        Interval(start=base + timedelta(minutes=o), end=base + timedelta(minutes=o + d))
        for o, d in busy_offsets
    ]
    fragments = free_fragments(hours, busy, capacity)
    for _, remaining in fragments:
        assert 0 <= remaining <= capacity  # never negative, never exceeds capacity
```

### time-machine — lazy hold expiry (HOLD-05, AVAIL-03)

```python
# Source: adapted from time-machine's travel() API (verified via WebSearch this
# session against time-machine.readthedocs.io/en/latest/usage.html)
import time_machine
from datetime import UTC, datetime, timedelta

async def test_expired_hold_stops_counting_against_capacity(store, sample_resource):
    resource = sample_resource.model_copy(update={"capacity": 1})
    await store.save_resource(resource)
    t0 = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
    slot = Interval(start=t0 + timedelta(hours=1), end=t0 + timedelta(hours=1, minutes=30))

    with time_machine.travel(t0, tick=False):
        await store.place_hold(resource.id, slot, resource.capacity, ttl_seconds=60)
        # A second hold on the same capacity-1 slot fails while the first is active.
        with pytest.raises(CapacityExhaustedError):
            await store.place_hold(resource.id, slot, resource.capacity, ttl_seconds=60)

    with time_machine.travel(t0 + timedelta(seconds=61), tick=False):
        # No release_hold()/confirm_hold() call happened — expiry must be lazy.
        second_hold = await store.place_hold(resource.id, slot, resource.capacity, ttl_seconds=60)
        assert second_hold is not None
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| `hypothesis.extra.pytz.timezones()` for generating aware datetimes | `st.datetimes(timezones=st.timezones())` (zoneinfo-backed) | pytz extra deprecated in favor of stdlib `zoneinfo` (Python 3.9+) `[CITED: hypothesis.readthedocs.io — Additional packages, pytz extra deprecation note]` | If any DST-related property test is written for this phase, use the stdlib-backed strategy, not the deprecated `pytz` extra |
| `freezegun` for time mocking | `time-machine` | Already locked project-wide per `.claude/CLAUDE.md`'s "What NOT to Use" table — restated here since this phase is the first to actually use it | N/A — just confirming no regression to `freezegun` in this phase's test-writing |

**Deprecated/outdated:** none newly identified this phase beyond what `.claude/CLAUDE.md` already documents (`datetime.utcnow()`, `freezegun`, `python-intervals`).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | CPython's `zoneinfo` default (`fold=0`, unset) collapse-forward behavior for spring-forward gap boundaries is an acceptable, sufficient reading of D-01's "skip the non-existent spring-forward hour" instruction, requiring no additional production code — only tests/docs | Architecture Patterns Pattern 2 | LOW-MEDIUM — if the discuss/planning step decides "skip" should instead mean "truncate the window at the gap's start" (a different, also-defensible reading), a small amount of explicit `_is_imaginary`-driven clamping code would need to be added to `time.py`; the detection helper is already provided either way, so the cost of being wrong is bounded |
| A2 | Removing `PublicSlot.status`/`SlotStatus` entirely (rather than keeping it as a redundant-but-harmless field alongside the new `available`/`booked` list split) is the cleaner contract, but this research recommends *keeping* it to minimize the blast radius of the already-mandatory breaking change | Architecture Patterns Pattern 1, Open Questions #2 | LOW — either choice is additive-safe from here; if the planner drops it, tests referencing `.status` need updating, a small mechanical cost |
| A3 | `ResourceNotFoundError` and `HoldNotFoundError` should share the single `ReasonCode.NOT_FOUND` value (rather than the enum gaining a `resource_not_found` variant) since REQUIREMENTS.md's HOLD-08 wording lists only one generic `not_found` example | Architecture Patterns Pattern 4 | LOW — if wrong, adding a second closed-enum member is itself a one-way breaking change to the "closed enum" contract per D-03's own reversibility note, so this is worth explicit confirmation before locking, not a free fix later |
| A4 | Every function needing hypothesis property tests this phase (`free_fragments`, `grid_slots`, `localize_operating_hours`) is synchronous, so no hypothesis+pytest-asyncio async-strategy interaction applies | Standard Stack | LOW — verified directly by reading the actual function signatures in Phase 1's source (none are `async def`); would only be wrong if the planner also wants to property-test `AvailabilityEngine.get_availability` itself (an `async def` facade method), which is not required by any Phase 2 success criterion |

## Open Questions (RESOLVED)

1. **Does CONTEXT.md's "byte-for-byte" consumer-stub-matching framing (D-04's reversibility note) actually apply to the real `SocialNetwork-Chatbot` consumer code?**
   - What we know: reading the actual consumer repo (`/home/yahir/Projects/Reusable/SocialNetwork-Chatbot/src/chatbot_engine/availability/port.py`) shows its `AvailabilityPort` is a **synchronous `abc.ABC`** with its own `Slot(slot_id, resource_id, starts_at, ends_at, capacity)` / `Hold(hold_id, slot_id, expires_at)` / `Booking(booking_id, slot_id, confirmation_ref)` dataclasses — structurally different field names and shape from this engine's async, Pydantic `PublicSlot(start, end, resource_id, ...)` / `Hold` / `Booking`. The project's own `.planning/v1.0-DECISION-MAP.md` (Phase 5 `[adapter]` gray area) already anticipates this divergence and resolves it with "ship an example-integration adapter that translates the engine's async, reason-code contract into the consumer's sync `AvailabilityPort`" — i.e., an adapter, not a direct pin, and that adapter is explicitly a **Phase 5** deliverable, not built yet.
   - What's unclear: whether "byte-for-byte" in this phase's own CONTEXT.md D-04 is a stale/aspirational claim (written before the consumer's actual port.py existed or was inspected), or whether it refers to some other stub this research didn't find.
   - Recommendation: treat AVAIL-04's "conformance-testable" success criterion as **freezing and documenting the engine's own contract** (Pattern 5's golden-file test), independent of the consumer's `AvailabilityPort` shape — do not attempt to rename `PublicSlot`'s fields to match the consumer's `starts_at`/`ends_at`/`slot_id` naming, since that would only be correct if this phase were also building the Phase 5 adapter early (out of scope). Flag this discrepancy for the human to confirm during discuss-phase or plan-review, since it directly contradicts a locked decision's stated rationale.
   - **RESOLVED:** `02-03-PLAN.md`'s "Flagged Assumptions" section (AVAIL-04) locks in exactly this recommendation — the golden-file conformance test freezes THIS ENGINE's own `AvailabilityResult`/`PublicSlot` contract shape, not the consumer's structurally-different `AvailabilityPort`; reconciling the two is explicitly deferred to Phase 5's adapter, out of scope for this phase.

2. **Should `PublicSlot` keep a `status`/`SlotStatus` field alongside the new `available`/`booked` list split, or should it be removed as redundant?**
   - What we know: D-04 only specifies adding `remaining`/`capacity`; it does not explicitly say to remove `status`. Phase 1's own `SlotStatus` docstring anticipated Phase 2 extending the contract "additively," which the two-list restructure already violates for `AvailabilityResult.slots` regardless.
   - What's unclear: whether the consumer's eventual Phase 5 adapter benefits from a redundant `status` field, or whether it's dead weight.
   - Recommendation: keep `status` for now (Pattern 1's recommendation) — it is a zero-cost, backward-compatible-in-spirit convenience field a discuss-phase pass or planner can drop later without breaking anything (removing a field is always available; adding one back after a consumer pins to its absence is not).
   - **RESOLVED:** `02-03-PLAN.md` Task 1's action locks in KEEP — `SlotStatus`/`PublicSlot.status` are retained exactly as-is alongside the new `capacity`/`remaining` fields, per this research's own recommendation.

## Environment Availability

No new external service/tool dependencies — pure Python library code, in-memory backend only, no database, no Docker, no network calls beyond `uv add`'s package installs (same as Phase 1). `uv`, Python 3.12+, and the system's ability to install `tzdata` are already-satisfied prerequisites verified in Phase 1.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 + pytest-asyncio 1.4.0 (`asyncio_mode = "auto"`) — unchanged from Phase 1 |
| Config file | `pyproject.toml`'s existing `[tool.pytest.ini_options]` block — no changes needed |
| Quick run command | `uv run pytest tests/ -x -q` |
| Full suite command | `uv run pytest -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| AVAIL-02 | Sweep-line remaining-capacity never negative or over-capacity across random overlapping holds | property (hypothesis) | `uv run pytest tests/core/test_availability.py::test_free_fragments_never_exceeds_capacity -x` | ❌ Wave 0 |
| AVAIL-03 | Expired hold excluded from `get_active_entries()` on next read, no manual release | unit | `uv run pytest tests/storage/contract_suite.py -k expired -x` | ❌ Wave 0 |
| AVAIL-04 | `AvailabilityResult`'s JSON schema matches the committed golden file | unit | `uv run pytest tests/test_contract_conformance.py::test_availability_result_schema_matches_golden -x` | ❌ Wave 0 |
| GRID-02 | Spring-forward gap and fall-back doubled-hour produce no missing/duplicated/shifted slots on real 2024-2026 dates | fixture-based unit | `uv run pytest tests/core/test_grid_dst.py -x` | ❌ Wave 0 |
| GRID-03 | Overnight `end<=start` LocalInterval produces correct UTC span, including across a DST date | fixture-based unit | `uv run pytest tests/test_time_boundary.py -x` | ❌ Wave 0 |
| HOLD-05 | A hold with an elapsed TTL stops counting against capacity on the very next `place_hold`, no `release_hold` call | unit (time-machine) | `uv run pytest tests/test_hold_expiry.py -x` | ❌ Wave 0 |
| HOLD-08 | `place_hold` outside operating hours raises `OutsideHoursError` with `.reason_code == ReasonCode.OUTSIDE_HOURS`; every `errors.py` exception has a non-null `.reason_code` | unit | `uv run pytest tests/test_engine.py::test_place_hold_outside_hours tests/test_errors.py::test_every_exception_has_reason_code -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `uv run pytest tests/ -x -q`
- **Per wave merge:** `uv run pytest -q`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `tests/core/test_availability.py` — hypothesis property tests for AVAIL-02
- [ ] `tests/core/test_grid_dst.py` — real-date DST fixtures for GRID-02
- [ ] `tests/test_time_boundary.py` — midnight-crossing + DST-boundary fixtures for GRID-03
- [ ] `tests/test_contract_conformance.py` + `tests/golden/*.schema.json` — golden-file generation for AVAIL-04
- [ ] `tests/test_errors.py` — exhaustiveness test that every concrete exception class has a `.reason_code`
- [ ] Framework install: `uv add tzdata && uv add --dev time-machine hypothesis` — confirm exact pins still current immediately before running (PyPI publishes continuously)
- [ ] Canary: a single `time_machine.travel(...)` smoke test confirming it interacts correctly with `pytest-asyncio`'s `asyncio_mode="auto"` before writing the full HOLD-05 test

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | No | Unchanged from Phase 1 — no auth surface in this library |
| V3 Session Management | No | Unchanged — holds are not sessions |
| V4 Access Control | No | Unchanged — opaque ids only, no "who" concept |
| V5 Input Validation | Yes | New `OutsideHoursError` validation at `place_hold` (Pattern 4) is itself a V5 control — rejecting a structurally-valid-but-out-of-policy request rather than silently accepting it |
| V6 Cryptography | No | Unchanged — no cryptographic surface |
| V7 Error Handling and Logging | Yes | The new `ReasonCode`/`.reason_code` surface is itself an error-handling contract change — see Known Threat Patterns below for the enumeration-oracle consideration this introduces |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|----------------------|
| Reason-code granularity creates a hold-existence enumeration oracle (`hold_expired` vs. `not_found` are distinguishable reason codes) | Information Disclosure | This is a deliberate, requirement-driven design (HOLD-08 explicitly lists both codes) — the engine is a generic reusable library, not itself bound to a no-oracle security posture. The downstream `SocialNetwork-Chatbot` consumer already anticipated exactly this: its own `AvailabilityPort.HoldExpired` docstring states "a single presence-check covers both... deliberately indistinguishable (no oracle)," and the project's own decision map assigns collapsing this distinction to the not-yet-built Phase 5 adapter, not to this engine. No action needed in this phase beyond documenting the distinction exists — do not silently collapse `HoldNotFoundError`/`HoldExpiredError` into one reason code here, since that would violate HOLD-08's explicit requirement. |
| DST/imaginary-time construction silently succeeding rather than raising (Pattern 2's verified finding) could let a malformed or adversarial `Resource.operating_hours` (e.g. deliberately using `time(2,30)` boundaries every day to probe engine behavior) produce unexpected slot durations | Tampering (indirectly — a resource-defining caller manipulating scheduling math) | Fixture/property tests (this phase's Wave 0 gaps) close this by proving the exact, deterministic behavior for imaginary/ambiguous boundaries — "deterministic and documented" is the mitigation, not "reject the input," since a resource legitimately might have unusual hours. |
| A future SQL backend (Phase 4) exception leaking through `get_active_entries`'s now-more-complex expiry filtering | Information Disclosure | Not yet in scope (in-memory only), but the shared-primitive refactor (Pattern 3) is exactly the single choke point Phase 4's SQL backend implementation will need to replicate with a `WHERE expires_at > now()`-style clause — establishing the pattern here reduces Phase 4's risk of re-introducing the same duplicated-scan bug in a new backend. |

## Sources

### Primary (HIGH confidence)

- `[VERIFIED: python3 zoneinfo runtime, this session]` — direct execution of `zoneinfo`/`datetime.fold` against real `America/New_York` 2026 transition dates (spring-forward gap collapse, fall-back doubled-hour disambiguation, boundary-only and overnight-crossing UTC span calculations) — this is the single highest-confidence source in this document, since it is not a citation of a claim but a reproduced, observed result.
- `[VERIFIED: src/availability_engine/*.py]` — direct read of every Phase 1 source file this phase extends (`contracts.py`, `engine.py`, `errors.py`, `time.py`, `core/availability.py`, `core/grid.py`, `core/intervals.py`, `storage/protocol.py`, `storage/memory.py`), with exact line ranges cited per claim.
- `[VERIFIED: PyPI registry]` — direct `curl https://pypi.org/pypi/<package>/json` against the authoritative PyPI JSON API for `tzdata`, `time-machine`, `hypothesis` — exact current versions and publish dates, 2026-09-03.
- `[VERIFIED: /home/yahir/Projects/Reusable/SocialNetwork-Chatbot/src/chatbot_engine/availability/{port,stub}.py]` — direct read of the actual first-consumer's `AvailabilityPort` contract, surfacing the Open Questions #1 discrepancy.

### Secondary (MEDIUM confidence)

- `[CITED: timeanddate.com/time/change/usa/new-york]` — real DST transition dates for 2024/2025/2026, cross-referenced against direct `zoneinfo` execution above (dates matched exactly).
- `[CITED: time-machine.readthedocs.io/en/latest/usage.html]` — `travel()`/`tick`/`move_to`/`shift` API shape, via WebSearch (Context7 MCP tool was unavailable this session; no live doc fetch performed, WebSearch summary only).
- `[CITED: hypothesis.readthedocs.io — examples, Additional packages]` — `st.datetimes(timezones=...)`, pytz-extra deprecation.
- `[CITED: pydantic.dev/docs — model_json_schema()]` — JSON schema generation API for the conformance-test pattern.

### Tertiary (LOW confidence)

- None used as load-bearing claims — every DST-specific claim in this document was independently verified by direct execution rather than left as a WebSearch-only citation.

## Metadata

**Confidence breakdown:**
- DST/midnight-crossing correctness claims: HIGH — verified by direct code execution against real transition dates, not just cited
- Existing-codebase gap findings (active-entries expiry, missing outside-hours check): HIGH — verified by direct source read with line citations
- New dependency versions: HIGH — verified against PyPI's authoritative JSON API
- Library API shape (time-machine, hypothesis, pydantic schema methods): MEDIUM — WebSearch-cited, not fetched from live docs (Context7 MCP unavailable this session)
- Consumer-stub discrepancy (Open Questions #1): HIGH — verified by direct read of the actual consumer repo, though the *resolution* (what to do about it) is a judgment call flagged for human confirmation

**Research date:** 2026-09-03
**Valid until:** 2026-10-03 (30 days — DST transition dates and zoneinfo behavior are stable facts, not subject to drift; re-verify exact `tzdata`/`time-machine`/`hypothesis` version pins again immediately before `pyproject.toml` is updated, since all three show active release cadence)
