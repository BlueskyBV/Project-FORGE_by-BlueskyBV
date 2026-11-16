"""The schema's migrations, one module per major step (ADR-0026; V2-stage4b-0c.md, 3.2).

Each step is a pure function from a draft's JSON at one major version to
the next, kept here forever and listed in :data:`STEPS` in order, so a
draft of any earlier version is brought to the current one step by step
(:func:`forge_spec.versions.migrate`). A minor version only adds optional
fields and needs none. A step is proven by ``tests/v2_migrations.py``: every
draft Forge holds, migrated, read by the new code against the draft read by
the old.

None yet: version 1.1 named its version ``schema_version`` (1.0 said
``"spec_format": 1``), a minor step.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

__all__ = ["STEPS", "Migration"]

Migration = Callable[[dict[str, Any]], dict[str, Any]]

#: (from this major version, to the next, the migration), in order.
STEPS: tuple[tuple[int, int, Migration], ...] = ()
