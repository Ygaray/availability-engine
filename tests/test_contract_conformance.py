"""Contract-freeze golden-file conformance test (AVAIL-04).

Proves `AvailabilityResult`'s JSON schema matches the committed golden-file
snapshot — a consumer pins to this shape, so any drift must fail loudly here
rather than silently reaching a downstream consumer. No production code is
modified by this file.
"""

import json
from pathlib import Path

from availability_engine.contracts import AvailabilityResult

GOLDEN_PATH = Path(__file__).parent / "golden" / "availability_result.schema.json"


def test_availability_result_schema_matches_golden() -> None:
    current_schema = AvailabilityResult.model_json_schema()
    golden_schema = json.loads(GOLDEN_PATH.read_text())
    assert current_schema == golden_schema, (
        "AvailabilityResult's JSON schema drifted from the frozen golden file "
        f"at {GOLDEN_PATH}. If this is an intentional contract change, "
        "regenerate the golden file in the SAME commit and get it reviewed — "
        "this is the parallel consumer's pin point."
    )
