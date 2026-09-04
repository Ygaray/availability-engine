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
