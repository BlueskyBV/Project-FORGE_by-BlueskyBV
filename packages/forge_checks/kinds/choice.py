"""The ``choice`` kind: the shape a choice makes, told from the shapes of the other choices.

Round or square ends, a rectangle or a circle, cut in or standing out, the
whole ball or the dome, the axis a slot runs along: **measures** points
where the spec's choice and each other choice make shapes that differ by
more than the part may, and holds the spec's to its side of each
(:mod:`forge_checks.kinds.told`).

**Tolerance policy:** none: the shape is the spec's choice or another's.

**Mutants and near-misses:** the item made with each other choice (it must
fail), and with the spec's (it must pass).
"""

from __future__ import annotations

from .told import Told, measure

__all__ = ["Told", "measure"]
