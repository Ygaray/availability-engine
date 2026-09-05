# Phase 2: Capacity & Time Correctness - Context

**Gathered:** 2026-09-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Make availability correct under capacity > 1 and under timezone/DST transitions: freeze the DST representation in the output contract, partition available/booked with explicit remaining capacity, and model midnight-crossing operating hours.

</domain>

<decisions>
## Implementation Decisions

### DST & Time Contract
- **D-01 [dst-contract]:** UTC-only slot identity (ISO-8601 with explicit offset); loop grid arithmetic in UTC so fall-back naturally yields two distinct ordered slots; skip the non-existent spring-forward hour and document that default. Localizing for display stays the consumer's job. _(source: human — skip-vs-shift is behavioral and locked before freeze; matches ARCHITECTURE.md.)_ — **Reversibility:** one-way — this is the frozen output-contract representation the consumer stub pins to.
- **D-02 [tzdata]:** Pin the `tzdata` PyPI package as an explicit dependency so spring-forward/fall-back fixtures (e.g. `America/New_York`) and consumer installs are reproducible across CI and minimal Linux/Windows environments where the system tzdb may be absent. _(source: ai-auto)_

### Reason Codes
- **D-03 [reason-codes]:** Typed exception hierarchy (`CapacityExhaustedError`, `OutsideHoursError`, `HoldExpiredError`, `HoldNotFoundError`), each exposing `.reason_code` from a **closed** enum that pre-includes `idempotency_conflict` (raised only from Phase 3) — so Phase 3 doesn't widen a "closed" set the consumer already pinned to. _(source: ai-auto)_ — **Reversibility:** one-way — a closed enum in the frozen contract; widening it later breaks the consumer's exhaustiveness assumptions.

### Capacity Shaping
- **D-04 [capacity-shape]:** Two lists — `available` (each slot `remaining > 0`) and `booked` (`remaining == 0`) — each slot carrying an explicit remaining-capacity integer (plus resource capacity), computed via sweep-line; never collapsed to a boolean. _(source: ai-auto)_ — **Reversibility:** one-way — exact split point and field names must match the consumer stub byte-for-byte.

### Midnight-Crossing Hours
- **D-05 [midnight-hours]:** Tolerate `end < start` in the frozen Resource schema (via `(start_local, duration)` or an explicit `spans_midnight` flag) with grid generation anchored from the start day and extending past midnight in UTC. _(source: ai-auto)_ _(provisional — refresh at execution; depends on Phase 1)_ — **Reversibility:** one-way — must reconcile with the actual Phase 1 `Resource` shape once it lands.

### Claude's Discretion
Sweep-line implementation details and internal grid-generation helpers are open provided the frozen contract fields above are honored.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Milestone decisions
- `.planning/v1.0-DECISION-MAP.md` §Phase 2 — the resolved gray areas above (dst-contract, reason-codes, capacity-shape, midnight-hours, tzdata)
- `.planning/APPROVED-DEPS.md` — pre-approved packages for this phase (tzdata, time-machine, hypothesis)

### Upstream contract (must reconcile)
- `.planning/phases/01-end-to-end-walking-skeleton-in-memory/01-CONTEXT.md` — the frozen `Resource` shape (`hours-shape`) and contract types this phase extends; `midnight-hours` must reconcile with the actual Phase 1 `Resource` once it lands.

### Project scope
- `.planning/ROADMAP.md` — Phase 2 scope and success criteria
- `.planning/REQUIREMENTS.md` — correctness requirements (TZ-aware, UTC-internal, DST)
- `.claude/CLAUDE.md` — UTC-internal / TZ-aware constraint; `zoneinfo` boundary rule; naive-datetime prohibition

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- The Phase 1 hand-rolled half-open `Interval` type and in-memory store are the base this phase extends. Surfaced at plan time.

### Established Patterns
- Do interval math in aware stdlib `datetime` (always UTC); resolve per-resource IANA zones via `zoneinfo.ZoneInfo` only at the operating-hours→UTC-slot-grid boundary (CLAUDE.md).

### Integration Points
- The output contract extended here (DST representation, capacity split) is what the consumer stub pins to.

</code_context>

<specifics>
## Specific Ideas

DST edge cases (spring-forward gap, fall-back doubled hour) and multi-timezone resources will be tested heavily with `time-machine`; interval/grid invariants with `hypothesis`.

</specifics>

<deferred>
## Deferred Ideas

- Continuous/arbitrary-duration bookings (interval-set algebra via `portion`) — deferred beyond v1.
- SQL persistence of the capacity/status model → Phase 4 (`schema`).

</deferred>

---

*Phase: 2-Capacity & Time Correctness*
*Context gathered: 2026-09-03*

## Runtime Decisions

_Refreshed at milestone-execute time from Phase 1's real output (provisional decision resolved)._

**[midnight-hours]** (source: ai-auto, depends-on: Phase 1 — now complete)
Phase 1 landed `operating_hours` as `dict[Weekday, list[LocalInterval]]` where
`LocalInterval = {start: time, end: time}` with **no** same-day (`end > start`) validator —
`end < start` is the tolerated sentinel for overnight/midnight-crossing shifts. Phase 2 grid
generation must interpret a `LocalInterval` with `end <= start` as spanning midnight: anchor the
slot grid from the start weekday's local date and extend past 24:00 into the next calendar day,
converting to UTC across the boundary (and across any DST transition in that window). No
`spans_midnight` flag and no `(start, duration)` pair are needed — the sentinel is the frozen contract.
