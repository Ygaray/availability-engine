# Deferred Items — Phase 4

Items discovered during execution that were out of scope for the current task per the
SCOPE BOUNDARY rule (pre-existing, not caused by this task's changes).

**All items below were resolved at v1.0 milestone close (commit `155e06b`, 2026-09-05):**
the 6 pre-existing `ruff check` E501 violations were fixed by wrapping the `place_hold`
idempotency `TypeError` message (implicit string concatenation) and adding `# noqa: E501`
to the five long, self-documenting `test_*` method-name definition lines. Verified: `uv run
ruff check .` → all checks passed; `uv run mypy --strict src/` → clean; `uv run pytest` →
139 passed. No behavioral change.

## Deferred Items

- **Pre-existing `ruff check` E501 violations, unrelated to Phase 4's changes.**
  status: resolved
  Six pre-existing line-length violations that predated Phase 4 entirely (confirmed via
  `git diff <phase-4-base-commit> -- <file>` — zero diff on the offending lines):
  `src/availability_engine/storage/memory.py:138` (a `TypeError` message string, landed in
  Phase 3) and five long `test_*` method-name definition lines in
  `tests/storage/contract_suite.py` (94–105 chars, landed in Phase 3). Renaming the methods
  to fit 88 chars would have reduced their self-documenting value, so they were deferred at
  the time. **Resolved in `155e06b`** per the recommendation below — the message string was
  wrapped and the five method-name lines carry a per-line `# noqa: E501`.

- **Full project-wide green run (status note — no action required).**
  status: resolved
  `uv run pytest` — 110 passed at the Phase 4 gate (139 passed at milestone close). `uv run
  mypy --strict src` — clean. `git diff d8f246e HEAD -- src/availability_engine/engine.py
  src/availability_engine/contracts.py` — empty diff, confirming no task across the entire
  phase touched either file (Success Criterion #2). This was a green-run confirmation, not a
  deferred action.
