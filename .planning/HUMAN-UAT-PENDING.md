# Human UAT Pending

## Entries

### Phase 3 — idempotency-cancellation (v1.0)

- **Status:** `pending`
- **Milestone:** v1.0
- **Gate 1 self-UAT log:** [`.planning/phases/03-idempotency-cancellation/03-SELF-UAT.md`](phases/03-idempotency-cancellation/03-SELF-UAT.md) — Verdict: **ALL 3 criteria PASS** (headless — Python library, no UI/device; driven via the real `AvailabilityEngine` facade + `InMemoryStore`, wheel md5 `293ff7091682f4bd85255449c922ab64` @ `16cf513`, 2026-09-04). Proved retry-safe `place_hold`/`confirm_hold` via idempotency keys (replay, conflict, and a genuine `asyncio.gather` concurrent race) and immediate capacity-freeing `cancel_booking`.
- **Items covered (3 ROADMAP success criteria):**
  - **SC1 — Idempotent replay returns the original result.** Same `idempotency_key`+args on `place_hold`/`confirm_hold` returns the identical `Hold`/`Booking` id; capacity consumed exactly once (proven via a follow-up `CapacityExhaustedError` on a genuinely new key). Also adversarially re-confirmed the CR-01 fix: replay after the underlying hold was released produces a fresh, live hold, not a stale/phantom reference.
  - **SC2 — Race safety + conflict reason code.** A real concurrent (`asyncio.gather`) same-key race on a capacity-1 resource resolves to one `Hold.id`, never double-spending capacity. A same-key call with materially different args (either operation) raises `IdempotencyConflictError` with `reason_code == idempotency_conflict`.
  - **SC3 — Cancellation frees capacity immediately.** `cancel_booking` on a `CONFIRMED` booking flips it `CANCELLED`; the very next `get_availability` read shows the slot freed, and a fresh `place_hold` on the identical slot succeeds. Re-cancelling raises `BookingNotFoundError` (no silent no-op).
- **Owner how-to-verify (run at milestone completion):**
  1. Read the Gate-1 log above for per-criterion evidence and exact driver scripts' stdout.
  2. Optionally re-run: `uv run python -c "..."` against `AvailabilityEngine`/`InMemoryStore` reproducing a `place_hold` call twice with the same `idempotency_key` and confirm the returned `Hold.id` is identical; then `cancel_booking` a confirmed booking and confirm `get_availability` shows it freed on the very next call.
- **Note:** No SQL/persistent backend yet (Phase 4) — all verification is against `InMemoryStore`, the only backend that exists at this phase. No UI/device exists for this project (pure Python library); Gate-1 ceiling is rung 3 (headless data-level checks via the real read path), which is the highest rung meaningful for this surface. 6 pre-existing cosmetic `ruff` E501 findings noted in the SELF-UAT log — no bearing on these criteria.
