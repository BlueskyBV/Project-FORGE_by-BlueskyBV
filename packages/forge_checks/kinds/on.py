"""The ``on`` kind: the face an item stands on or cuts into, told from the other faces it could be on.

**Measures** points where the item on the spec's face and the item on each
other face of its host (as the definitions would place it there) differ by
more than the part may: the spec's face must have each on its own side
(:mod:`forge_checks.kinds.told`). A cut right through, the same from either
face, is told only where its counterbore or countersink is.

**Tolerance policy:** none: the face is the spec's or another.

**Mutants and near-misses:** the item made on each other face (it must
fail), and on its own (it must pass).
"""

from __future__ import annotations

from .told import Told, measure

__all__ = ["Told", "measure"]
