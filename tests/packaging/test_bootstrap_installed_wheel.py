"""Build+venv+install+migrate round trip against the built wheel (D-05, PKG-01).

Proves a fresh git-tag-pinnable wheel install can bootstrap its own database
schema end to end: `import availability_engine` resolves from site-packages
(not this repo checkout), and `alembic.command.upgrade(cfg, "head")` against
`availability_engine.migrations.get_script_location()`'s resolved path
creates all four tables. Mirrors this repo's own
SocialNetwork-Chatbot/tests/packaging/test_bootstrap_installed_wheel.py
template (read in full during research).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    shutil.which("uv") is None, reason="uv is required to build/install the wheel under test"
)

_CHECK_SCRIPT = '''
import availability_engine

assert "site-packages" in availability_engine.__file__, (
    f"expected the installed wheel's site-packages copy, got "
    f"{availability_engine.__file__!r}"
)

from alembic import command
from alembic.config import Config
from availability_engine.migrations import get_script_location

cfg = Config()
cfg.set_main_option("script_location", str(get_script_location()))
cfg.set_main_option("sqlalchemy.url", "sqlite+aiosqlite:///./smoke_migrate.db")
command.upgrade(cfg, "head")

import sqlalchemy as sa

sync_engine = sa.create_engine("sqlite:///./smoke_migrate.db")
try:
    table_names = set(sa.inspect(sync_engine).get_table_names())
finally:
    sync_engine.dispose()

expected = {"resources", "holds", "bookings", "idempotency"}
assert expected <= table_names, (
    f"expected tables {expected} to be a subset of {table_names}"
)

print("MIGRATE_OK")
'''


def _run(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    assert result.returncode == 0, (
        f"command {cmd} failed (exit {result.returncode})\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return result


def test_migration_bootstraps_from_installed_wheel(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    _run(["uv", "build", "--wheel", "-o", str(dist_dir)], cwd=_REPO_ROOT)
    wheels = sorted(dist_dir.glob("*.whl"))
    assert len(wheels) == 1, f"expected exactly one built wheel, found {wheels}"

    venv_dir = tmp_path / "venv"
    _run(["uv", "venv", str(venv_dir), "--python", sys.executable])
    venv_python = venv_dir / "bin" / "python"

    _run(["uv", "pip", "install", "--python", str(venv_python), str(wheels[0])])

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    script_path = run_dir / "check_bootstrap.py"
    script_path.write_text(_CHECK_SCRIPT)

    result = _run([str(venv_python), str(script_path)], cwd=run_dir)
    assert "MIGRATE_OK" in result.stdout
