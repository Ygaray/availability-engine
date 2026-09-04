"""Package anchor for the force-included Alembic assets.

This package is intentionally near-empty. Its sole purpose is to give
``importlib.resources.files("availability_engine._migrations")`` a real,
importable anchor to resolve against. The actual ``alembic.ini``/``alembic/``
content is NOT written here in the source tree -- it is copied into this
package's directory *inside the built wheel only*, via
``[tool.hatch.build.targets.wheel.force-include]``, from the canonical
repo-root locations (kept there for `alembic` CLI ergonomics).
"""
