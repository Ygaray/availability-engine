"""Reason-code exhaustiveness test (HOLD-08).

`AvailabilityEngineError.reason_code` is an annotation-only class attribute —
`mypy --strict` accepts a subclass that forgets to set it (it is not truly
abstract), so this test closes that gap structurally: every concrete
exception in `errors.py` must carry a non-None `ReasonCode` instance. No
production code is modified by this file.
"""

from availability_engine import errors
from availability_engine.contracts import ReasonCode
from availability_engine.errors import AvailabilityEngineError

_CONCRETE_EXCEPTION_CLASSES = [
    errors.CapacityExhaustedError,
    errors.OutsideHoursError,
    errors.HoldExpiredError,
    errors.HoldNotFoundError,
    errors.ResourceNotFoundError,
    errors.BookingNotFoundError,
    errors.IdempotencyConflictError,
]


def test_every_exception_has_reason_code() -> None:
    for exc_class in _CONCRETE_EXCEPTION_CLASSES:
        assert issubclass(exc_class, AvailabilityEngineError)
        reason_code = getattr(exc_class, "reason_code", None)
        assert reason_code is not None, (
            f"{exc_class.__name__} has no reason_code set"
        )
        assert isinstance(reason_code, ReasonCode), (
            f"{exc_class.__name__}.reason_code is not a ReasonCode instance"
        )


def test_new_error_names_importable_from_top_level_package() -> None:
    # RESEARCH.md Pitfall 6: guards against the export-barrel omission —
    # BookingStatus/BookingNotFoundError must be importable from the
    # top-level availability_engine package, not just their submodules.
    from availability_engine import BookingNotFoundError, BookingStatus

    assert BookingNotFoundError is not None
    assert BookingStatus is not None


def test_reason_code_importable_from_top_level_package() -> None:
    # WR-03: ReasonCode.IDEMPOTENCY_CONFLICT is a value consumers need to
    # match against per this module's docstring ("inspect .reason_code to
    # branch without string-matching the exception type"), but ReasonCode
    # itself was never re-exported from __init__.py — the same export-barrel
    # omission class the test above guards for BookingStatus.
    from availability_engine import ReasonCode

    assert ReasonCode is not None
    assert ReasonCode.IDEMPOTENCY_CONFLICT is not None
