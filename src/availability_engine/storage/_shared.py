"""Small utilities shared across storage backend implementations
(`memory.py`, `sql/store.py`) — the cross-backend contract those modules
depend on, made explicit rather than incidental (WR-02).
"""

import hashlib
import json


def _fingerprint(*parts: object) -> str:
    """Deterministic fingerprint of the call arguments an idempotency key is
    scoped against. `json.dumps(..., sort_keys=True, default=str)` handles
    non-JSON-native parts (e.g. `datetime`) via `str()` deterministically.

    Every `StorageBackend` implementation's idempotency-conflict detection
    depends on this having identical semantics across backends — treat any
    change to this function's hashing scheme as a cross-backend breaking
    change, not an internal `memory.py` (or `sql/store.py`) detail.
    """
    return hashlib.sha256(
        json.dumps(parts, sort_keys=True, default=str).encode()
    ).hexdigest()


__all__ = ["_fingerprint"]
