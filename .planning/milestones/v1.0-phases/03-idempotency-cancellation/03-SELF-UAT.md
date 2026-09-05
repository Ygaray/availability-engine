---
status: complete
result: all_pass
gate: 1
phase: 03-idempotency-cancellation
source: [03-ROADMAP success criteria]
device: headless (library — no UI/device; driven via the real AvailabilityEngine facade + InMemoryStore in a fresh Python process)
apk: n/a — Python library; wheel md5 293ff7091682f4bd85255449c922ab64 @ 16cf513 (availability_engine-0.1.0-py3-none-any.whl)
run: 2026-09-04T18:15:00Z
---

# Self-UAT Log — Phase 03 (idempotency-cancellation)

**Target:** headless CLI/library — Python 3.12.3, `uv` venv. There is no UI/device for this project;
"driving the real app" means importing and calling the public `AvailabilityEngine` facade against
`InMemoryStore`, exactly as an external consumer would (no test-harness shortcuts, no monkeypatching,
no internal-state peeking except to read back through `get_availability`).
**Build:** git sha `16cf513`, wheel `availability_engine-0.1.0-py3-none-any.whl` md5
`293ff7091682f4bd85255449c922ab64` (`uv build --wheel`).
**Driver playbook:** none declared/present for this project (`uat_driver_playbook: null`, no
`AGENT-*-TESTING.md` at project root). Per the process's task context, this is a Python
library/CLI-API surface — driving = a fresh interpreter script importing the installed package and
calling the public facade. No bootstrap interview was run (headless, and the task context already
specified the exact drive method); noting this so a future run can formalize an
`AGENT-CLI-TESTING.md` if this project accrues more phases needing Gate-1.
**Unit suite:** `uv run pytest tests/ -q` → **69 passed, 0 failed** (baseline, pre-existing at HEAD).
**Lint/type:** `uv run mypy --strict src/` → clean (12 files). `uv run ruff check .` → 6 pre-existing
E501 (line-too-long) findings, all on long test-function names in `tests/storage/contract_suite.py`
and one in `storage/memory.py:138`; cosmetic only, no behavioral bearing on any of the 3 criteria
below — noted, not blocking.
**Seed/fixture integrity:** No persistent fixture — `InMemoryStore()` is instantiated fresh per
script run, and one `Resource` (`room-1`, IANA `UTC`, 1h slots, all-week open hours) is seeded
programmatically via `engine.define_resource()` at the top of each script. Capacity varies per
criterion (1 where "exhausted/freed" must be unambiguous, 2–3 where two independent holds are
needed side-by-side). Verified state via the real `get_availability` read path (not by inspecting
`InMemoryStore._holds`/`_bookings` directly).

## Criteria

### 1. Calling `place_hold` or `confirm` twice with the same idempotency key returns the original result instead of acting twice
result: passed
- **Rung:** 3 (headless data-level check via the real facade + `get_availability` read-back — no UI exists to climb higher)
- **Target:** headless (fresh Python process, real package import)
- **Expected:** two `place_hold` calls with identical `idempotency_key` + identical args return the same `Hold.id`; capacity is consumed exactly once. Same for `confirm_hold`/`Booking.id`, including the harder case where the first call's success already deleted the underlying `Hold` (replay must not raise `HoldNotFoundError`).
- **Arranged (seeded):** one `Resource("room-1", capacity=1)` programmatically via `engine.define_resource()`.
- **Did (drove):** `engine.place_hold(..., idempotency_key="req-abc")` called twice sequentially; separately, `engine.place_hold()` (no key) → `engine.confirm_hold(hold.id, payload, idempotency_key="confirm-xyz")` called twice. Also drove a same-key `confirm_hold` conflict variant (different `hold_id`/payload under the identical key) as an SC2-adjacent falsification.
- **Observed:** `h1.id == h2.id` (`714135ea-...` both calls); a third call with a *different* key on the same capacity-1 slot correctly raised `CapacityExhaustedError` — proving only ONE hold was ever actually created, not that the return value merely looked identical. `b1.id == b2.id` (`d99e4a77-...`) for `confirm_hold`, with the replay succeeding even though the first call's underlying `Hold` had already been consumed into the `Booking`. Adversarial CR-01 regression probe (release-then-replay): after `release_hold(h1.id)`, replaying the *same* key produced a live, capacity-consuming NEW hold (`0d52afad...` → `5e73df09...`, `remaining=0` post-replay) — i.e. the record does not return a phantom/stale reference after the underlying state changed.
- **Evidence:** `/tmp/claude-1000/-home-yahir-Projects-Reusable-availability-engine/5ef72cb8-2eca-4c72-83b4-9d210c2dce2e/scratchpad/uat_sc1_sc2.py` (stdout captured below); `uat_adversarial_stale_replay.py` (stdout captured below).
  ```
  === SC1: place_hold same idempotency_key twice -> same Hold, no double action ===
  PASS: h1.id=714135ea-237b-4df9-9362-c5f45efbc8ef h2.id=714135ea-237b-4df9-9362-c5f45efbc8ef (identical); capacity-1 resource still rejects a 3rd distinct hold -> only ONE hold was actually created
  === SC1: confirm_hold same idempotency_key twice -> same Booking ===
  PASS: b1.id=d99e4a77-ce9a-4375-8b9d-2d8cd351a0e9 b2.id=d99e4a77-ce9a-4375-8b9d-2d8cd351a0e9 (identical) — replay after underlying hold consumed did not raise HoldNotFoundError
  ...
  h1.id=0d52afad-7c26-42fd-bb51-44dd7b799419 (released) h2.id=5e73df09-e4bf-4e6f-be53-38883907e18e (replay-after-release)
  post-replay availability: status=booked, remaining=0
  PASS: replay after release produced a live, capacity-consuming hold (no stale/phantom result)
  ```

### 2. A retried call that races the original never double-spends capacity; a genuinely conflicting key surfaces an `idempotency_conflict` reason code
result: passed
- **Rung:** 3 (headless data-level check + real concurrent `asyncio.gather` race — no UI exists to climb higher)
- **Target:** headless (fresh Python process, real package import)
- **Expected:** two concurrent same-key `place_hold` calls (a real race, not a sequential simulation) resolve to one `Hold.id` and capacity is consumed exactly once; a same-key call with materially different args (different slot for `place_hold`, different `hold_id`/payload for `confirm_hold`) raises `IdempotencyConflictError` whose `.reason_code == ReasonCode.IDEMPOTENCY_CONFLICT`.
- **Arranged (seeded):** `Resource("room-1", capacity=1)` for the race case (capacity=1 makes double-spend unambiguous); `Resource("room-1", capacity=2)`/`capacity=3` for the conflict cases (need two independent slots/holds to construct a genuine conflict).
- **Did (drove):** `asyncio.gather(engine.place_hold(...key="race-key"), engine.place_hold(...key="race-key"))` — two truly concurrent calls into the same running engine/lock, not two sequential awaits. Separately: `place_hold(slot_A, key="dup-key")` then `place_hold(slot_B, key="dup-key")` (same key, different slot). Separately: `confirm_hold(hold1.id, ..., key="confirm-conflict-key")` then `confirm_hold(hold2.id, ..., key="confirm-conflict-key")` (same key, different hold/payload).
- **Observed:** race resolved to a single `Hold.id` (`7ae253fe-...`); the subsequent real `get_availability` read showed exactly one matching slot record with `remaining=0` on a capacity-1 resource — proving the race truly serialized rather than two holds silently existing under one returned id. The conflicting `place_hold` call raised `IdempotencyConflictError` with `reason_code=idempotency_conflict`. The conflicting `confirm_hold` call likewise raised `IdempotencyConflictError` with `reason_code=idempotency_conflict`, and a follow-up `get_availability` read confirmed `hold2` was never silently confirmed under the wrong record (`remaining=2` on a capacity-3 resource: 1 consumed by the legitimately confirmed `hold1`, 1 still held by `hold2`, matching expectation exactly).
- **Evidence:** `.../scratchpad/uat_sc1_sc2.py`, `.../scratchpad/uat_sc2_confirm_conflict.py` (stdout below).
  ```
  === SC2: same key, materially different args -> IdempotencyConflictError w/ idempotency_conflict reason code ===
  PASS: IdempotencyConflictError raised, reason_code=idempotency_conflict
  === SC2: concurrent same-key race on capacity-1 resource never double-spends ===
  PASS: race resolved to single Hold.id=7ae253fe-92fe-4fcf-ad02-704e4426eda4, get_availability shows remaining=0 (capacity=1, exactly one hold counted)
  ---
  PASS: confirm_hold conflict raised IdempotencyConflictError, reason_code=idempotency_conflict
  hold2's slot remaining=2 (capacity=3, only hold1 confirmed + hold2 still held)
  ```

### 3. A caller can cancel a confirmed booking, and its capacity is freed immediately — the freed slot reappears on the next availability read
result: passed
- **Rung:** 3 (headless data-level check via the real facade + `get_availability` read-back — no UI exists to climb higher)
- **Target:** headless (fresh Python process, real package import)
- **Expected:** `cancel_booking(booking.id)` on a `CONFIRMED` booking flips it to `CANCELLED`; the VERY NEXT `get_availability` call (no delay, no sweeper, no polling) shows the slot `AVAILABLE`/`remaining` restored, and a fresh `place_hold` on the exact same slot succeeds. Cancelling an already-cancelled or unknown booking must raise, never silently no-op.
- **Arranged (seeded):** `Resource("room-1", capacity=1)` (capacity-1 makes "freed" unambiguous: booked → available is a hard state flip, not a partial-capacity nuance).
- **Did (drove):** `engine.place_hold(...)` → `engine.confirm_hold(hold.id, payload)` → real `get_availability` read (sanity: confirmed BOOKED/remaining=0 before touching cancel) → `engine.cancel_booking(booking.id)` (the SUT) → immediate real `get_availability` read again → `engine.place_hold()` again on the identical slot → `engine.cancel_booking(booking.id)` a second time (already-cancelled).
- **Observed:** pre-cancel: `status=booked, remaining=0`. Post-cancel (the very next read, same slot): `status=available, remaining=1` — capacity freed with no delay. A fresh `place_hold` on that exact slot then succeeded (`Hold.id=f4edb6be-...`), proving "freed" in the real, consumable sense, not just a flipped display flag. Re-cancelling the same (now-cancelled) `booking.id` raised `BookingNotFoundError` — no silent no-op.
- **Evidence:** `.../scratchpad/uat_sc3_cancel.py` (stdout below).
  ```
  === SC3: cancel_booking on a CONFIRMED booking frees capacity immediately ===
  Pre-cancel: status=booked, remaining=0 (as expected: capacity exhausted)
  Post-cancel (immediate next read): status=available, remaining=1
  PASS: fresh place_hold on the freed slot succeeded -> new Hold.id=f4edb6be-a431-416f-9849-e99fbbc93b1a
  PASS: re-cancelling an already-cancelled booking raised BookingNotFoundError (no silent no-op)
  ```

## Summary

total: 3
passed: 3
partial: 0
failed: 0
infra: 0

## Notes / anomalies (for the Gate-2 reviewer)

- No prior `*-SELF-UAT.md` existed for this phase — nothing to audit/correct; all three verdicts above are fresh, adversarial, first-hand observations against the real facade+in-memory backend.
- This project has no declared UAT driver playbook and no UI/device target (it is a headless
  library). Per the task's explicit driving instruction, verification was performed by importing the
  installed package in a fresh interpreter and calling `AvailabilityEngine` methods directly against
  `InMemoryStore` — the closest equivalent to "driving the real app" this surface offers. All rungs
  above 3 (UI structure tree / visual capture) are inapplicable to this project; rung 3 (headless
  data/log checks via the real read-path `get_availability`) is the ceiling and was used throughout.
- `uv run ruff check .` reports 6 pre-existing `E501` (line-too-long) findings on long, descriptive
  test-function names (`tests/storage/contract_suite.py`) and one in `storage/memory.py:138`. Purely
  cosmetic, no bearing on any of the 3 ROADMAP success criteria — flagged for the team's lint hygiene,
  not a UAT gap.
- Went beyond the literal roadmap wording to adversarially probe the CR-01 class of bug the phase's
  own code review flagged as critical (stale/phantom idempotency replay after the underlying
  Hold/Booking state changed via `release_hold`) — independently re-confirmed fixed via a live
  release-then-replay probe (see Criterion 1 evidence), not merely by trusting `03-REVIEW-FIX.md`'s
  claim.

## Findings routed to gap-closure (if any)

None. All 3 criteria PASS on first-hand adversarial verification against the real running facade.

## Verdict

All criteria PASS → Gate-1 complete; human Gate-2 deferred to milestone completion (registered in HUMAN-UAT-PENDING.md).
