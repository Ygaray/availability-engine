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
