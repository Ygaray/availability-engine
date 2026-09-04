"""Wheel namelist regression guard (D-05, PKG-01, T-05-01).

Locks in Task 1's force-include fix as a permanent, fast, CI-friendly
regression guard: asserts the built wheel ships `py.typed` and the packaged
Alembic migration tree, and -- the shipped-consumer-dependency prohibition --
asserts it never ships `examples/` or anything naming `chatbot_adapter`, the
`AvailabilityPort`-importing reference adapter this phase adds later. That
adapter lives outside `src/` specifically so it can never be force-included;
this assertion is the regression guard against a future careless config
change reintroducing it.
"""
from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    shutil.which("uv") is None, reason="uv is required to build the wheel under test"
)


def test_built_wheel_contains_migrations(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    result = subprocess.run(
        ["uv", "build", "--wheel", "-o", str(dist_dir)],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr

    wheels = sorted(dist_dir.glob("*.whl"))
    assert len(wheels) == 1

    with zipfile.ZipFile(wheels[0]) as zf:
        names = zf.namelist()

    assert (
        "availability_engine/py.typed" in names
    ), f"py.typed missing; namelist={names}"
    assert any(
        n.startswith("availability_engine/_migrations/alembic/") for n in names
    ), f"migrations not force-included; namelist={names}"
    assert "availability_engine/_migrations/alembic/env.py" in names
    assert any(
        n.startswith("availability_engine/_migrations/alembic/versions/") for n in names
    ), f"migration versions missing; namelist={names}"

    # Negative case: the wheel must never carry the AvailabilityPort-importing
    # reference adapter, nor anything under an `examples/` directory.
    assert not any(
        n.startswith("availability_engine/examples/") for n in names
    ), f"wheel must never ship examples/; namelist={names}"
    assert not any(
        "chatbot_adapter" in n for n in names
    ), f"wheel must never ship the chatbot_adapter reference adapter; namelist={names}"
