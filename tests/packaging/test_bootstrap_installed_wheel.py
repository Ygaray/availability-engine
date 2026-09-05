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
from testcontainers.postgres import PostgresContainer

_REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    shutil.which("uv") is None,
    reason="uv is required to build/install the wheel under test",
)

_SQLITE_CHECK_SCRIPT = '''
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

# PKG-01 Nyquist gap: the SQLite check above proves the force-included
# alembic tree resolves and runs from an installed wheel's site-packages
# copy (via `get_script_location()`), but this project's storage layer and
# dialect-aware locking strategy explicitly target BOTH SQLite and
# Postgres (see pyproject.toml's asyncpg dependency and
# tests/test_migrations.py's own sqlite+postgres pairing at the source-tree
# level). Without this script, "installed wheel bootstraps its own schema"
# was only ever proven for one of the two backends the packaging claim
# covers -- a Postgres-only regression (e.g. a dialect-specific path in a
# future migration) could ship silently.
_POSTGRES_CHECK_SCRIPT_TEMPLATE = '''
import availability_engine

assert "site-packages" in availability_engine.__file__, (
    f"expected the installed wheel's site-packages copy, got "
    f"{{availability_engine.__file__!r}}"
)

from alembic import command
from alembic.config import Config
from availability_engine.migrations import get_script_location

cfg = Config()
cfg.set_main_option("script_location", str(get_script_location()))
cfg.set_main_option("sqlalchemy.url", "{sqlalchemy_url}")
command.upgrade(cfg, "head")

import asyncio

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine


async def _table_names() -> set[str]:
    engine = create_async_engine("{sqlalchemy_url}")
    try:
        async with engine.connect() as conn:
            return await conn.run_sync(
                lambda sync_conn: set(sa.inspect(sync_conn).get_table_names())
            )
    finally:
        await engine.dispose()


table_names = asyncio.run(_table_names())

expected = {{"resources", "holds", "bookings", "idempotency"}}
assert expected <= table_names, (
    f"expected tables {{expected}} to be a subset of {{table_names}}"
)

print("MIGRATE_OK")
'''


def _run(
    cmd: list[str], *, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    assert result.returncode == 0, (
        f"command {cmd} failed (exit {result.returncode})\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return result


def _build_wheel_into_fresh_venv(tmp_path: Path) -> Path:
    """Build the wheel and install it into a fresh venv, returning the
    venv's python executable. Shared by both the SQLite and Postgres
    bootstrap checks below -- neither depends on the other's storage
    backend, only on the same installed-wheel artifact."""
    dist_dir = tmp_path / "dist"
    _run(["uv", "build", "--wheel", "-o", str(dist_dir)], cwd=_REPO_ROOT)
    wheels = sorted(dist_dir.glob("*.whl"))
    assert len(wheels) == 1, f"expected exactly one built wheel, found {wheels}"

    venv_dir = tmp_path / "venv"
    _run(["uv", "venv", str(venv_dir), "--python", sys.executable])
    venv_python = venv_dir / "bin" / "python"

    _run(["uv", "pip", "install", "--python", str(venv_python), str(wheels[0])])
    return venv_python


def test_migration_bootstraps_from_installed_wheel(tmp_path: Path) -> None:
    venv_python = _build_wheel_into_fresh_venv(tmp_path)

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    script_path = run_dir / "check_bootstrap.py"
    script_path.write_text(_SQLITE_CHECK_SCRIPT)

    result = _run([str(venv_python), str(script_path)], cwd=run_dir)
    assert "MIGRATE_OK" in result.stdout


def test_migration_bootstraps_from_installed_wheel_against_postgres(
    tmp_path: Path,
) -> None:
    """PKG-01 (both-backends gap): the same installed-wheel bootstrap proof
    as `test_migration_bootstraps_from_installed_wheel` above, but against
    a real Postgres instance instead of SQLite -- the force-included
    `alembic`/`alembic.ini` tree and `get_script_location()` resolution
    must work identically for both backends this library packages for
    (asyncpg is already a direct wheel dependency, so no extra install
    step is needed beyond the wheel itself)."""
    venv_python = _build_wheel_into_fresh_venv(tmp_path)

    with PostgresContainer("postgres:17", driver="asyncpg") as pg:
        sqlalchemy_url = pg.get_connection_url()

        run_dir = tmp_path / "run_pg"
        run_dir.mkdir()
        script_path = run_dir / "check_bootstrap_pg.py"
        script_path.write_text(
            _POSTGRES_CHECK_SCRIPT_TEMPLATE.format(sqlalchemy_url=sqlalchemy_url)
        )

        result = _run([str(venv_python), str(script_path)], cwd=run_dir)

    assert "MIGRATE_OK" in result.stdout
