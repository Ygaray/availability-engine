# Deferred Items — Phase 4

Items discovered during execution that are out of scope for the current task per the
SCOPE BOUNDARY rule (pre-existing, not caused by this task's changes).

## 04-01 (Task 2)

- **Pre-existing `ruff check` E501 violations, unrelated to this plan's changes.**
  Task 2's `<verify>` block runs `uv run ruff check` (whole repo), which surfaces 6
  pre-existing line-length violations that predate Phase 4 entirely (confirmed via
  `git diff <phase-4-base-commit> -- <file>` — zero diff on the offending lines):
  - `src/availability_engine/storage/memory.py:138` (89 chars) — a `TypeError` message
    string, landed in Phase 3.
  - `tests/storage/contract_suite.py:205,241,275,308,419` (94-105 chars) — long
    `test_*` method-name definition lines, landed in Phase 3. Renaming these methods to
    fit 88 chars is out of scope for Task 2 (only the parametrize decorator and one
    disclosed test-body fix were authorized) and would reduce their self-documenting
    value.
  - All files/lines this plan actually created or modified
    (`src/availability_engine/storage/sql/*.py`, `tests/storage/conftest.py`,
    `tests/storage/test_sql_store.py`, and the specific lines changed in
    `tests/storage/contract_suite.py`/`tests/storage/test_protocol_conformance.py`)
    are individually `ruff check`-clean — verified via a scoped
    `uv run ruff check <touched files>` run.
  - Recommendation: a future cleanup task should either wrap these lines or add a
    per-line `# noqa: E501` where the identifier itself (a test method name) cannot be
    shortened without losing self-documentation value.

## 04-02 (Task 2)

- **Same 6 pre-existing `ruff check` E501 violations, re-confirmed.** Task 2's
  `<verify>` block (`uv run pytest tests/storage/ -x && uv run mypy --strict src && uv
  run ruff check`) re-surfaces the identical 6 violations logged under 04-01 above (line
  numbers in `tests/storage/contract_suite.py` shifted by +14 due to this plan's new
  `pytestmark` block, but the flagged lines themselves are byte-for-byte unchanged —
  confirmed via `git diff <phase-4-base-commit> -- tests/storage/contract_suite.py`,
  which shows zero diff on any offending line). Every file this plan actually touched
  (`tests/storage/conftest.py`, `src/availability_engine/storage/sql/*.py`, and the
  specific lines changed in `tests/storage/contract_suite.py`) is individually
  `ruff check`-clean — verified via `uv run ruff check src/availability_engine/storage/sql/ tests/storage/conftest.py`.
  No new dialect-parity fixes were needed in `store.py`: the full three-way
  `contract_suite.py` regression (51 cases) already passed cleanly after Task 1's
  fixture wiring — the JSON/JSONB empty-payload round-trip, `DateTime(timezone=True)`
  round-trip, and the dialect-agnostic `IntegrityError` catch in
  `_write_idempotency_record` were all already correct from Plan 04-01 (Postgres's
  `JSON().with_variant(postgresql.JSONB, "postgresql")` deserializes to a native
  Python `dict` and `Booking`'s `payload: dict[str, Any]` Pydantic field would have
  raised a validation error on any test if it hadn't; `_ensure_utc` already normalizes
  both dialects' datetime round-trips).
