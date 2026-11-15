"""One module per family of operations; :data:`BUILDERS` maps every operation to its builder (docs/V2-stage3.md, 7.2)."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from ..products import Context, Product
from . import (
    arrays,
    bend,
    booleans,
    holes,
    letters,
    modifiers,
    primitives,
    sketch,
    sweeps,
    threads,
)

__all__ = ["BUILDERS", "Builder"]

Builder = Callable[[Context], Product]

BUILDERS: Mapping[str, Builder] = {
    **sketch.BUILDERS,
    **primitives.BUILDERS,
    **sweeps.BUILDERS,
    **booleans.BUILDERS,
    **holes.BUILDERS,
    **modifiers.BUILDERS,
    **arrays.BUILDERS,
    **bend.BUILDERS,
    **letters.BUILDERS,
    **threads.BUILDERS,
}
