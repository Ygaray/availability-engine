"""Programmatic Alembic script_location resolver (D-05).

Consumer usage:
    from alembic.config import Config
    from alembic import command
    from availability_engine.migrations import get_script_location

    cfg = Config()
    cfg.set_main_option("script_location", str(get_script_location()))
    cfg.set_main_option("sqlalchemy.url", "<consumer's real DB URL>")
    command.upgrade(cfg, "head")
"""
from __future__ import annotations

from importlib.resources import files
from pathlib import Path

# Mirrors chatbot_engine/persistence/reconcile.py::_resolve_alembic_ini --
# same dual-layout resolution: installed wheel first, repo checkout fallback.
_REPO_ROOT = Path(__file__).resolve().parents[2]


def get_script_location() -> Path:
    """Resolve the Alembic ``script_location`` directory wherever it landed.

    1. Installed package: force-included under
       ``availability_engine._migrations/alembic`` -- resolved via
       ``importlib.resources`` so it works regardless of install location.
    2. Repo checkout (running tests from source): falls back to the
       repo-root ``alembic/`` directory.
    """
    packaged = files("availability_engine._migrations").joinpath("alembic")
    if packaged.is_dir():
        return Path(str(packaged))
    return _REPO_ROOT / "alembic"
