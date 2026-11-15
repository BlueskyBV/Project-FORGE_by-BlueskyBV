"""What the two-draft comparison reads of a tube: its entry in the ``compare`` registry (its branches moved from ``compare.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from collections.abc import Iterable

from forge_spec.draft import Item
from forge_spec.items.compare._common import (
    Feature,
    _Edge,
    _length,
    _mid,
    _r,
    _sub,
    _up,
    rims,
)
from forge_spec.items.compare.protocol import CompareKind
from forge_spec.placement import Instance


class Tube(CompareKind):
    key = "tube"

    def solid(self, n: int, item: Item, copy: Instance) -> list[Feature]:
        assert copy.lo is not None and copy.hi is not None
        lo, hi, kind = copy.lo, copy.hi, item.kind
        sizes, centre = _sub(hi, lo), _mid(lo, hi)
        up = _up(copy)
        across = (hi[(up + 1) % 3] - lo[(up + 1) % 3]) / 2
        axis = (copy.normal, False)
        inner = _length(item, "inner_diameter") or 0.0
        return [Feature(n, item.id, kind, "rod", sizes, centre, (_r(2 * across),), (axis,), field="outer_diameter"),
                # A tube is a rod with a bore right through: as built, one shape.
                Feature(n, item.id, kind, "round cut", (0.0, 0.0, 0.0), centre, (_r(inner), "through"),
                        (axis,), line=True, field="inner_diameter")]  # fmt: skip

    def edges(self, item: Item, copy: Instance, which: str) -> Iterable[_Edge]:
        def radii(end: str, outer: float) -> tuple[float, ...]:
            inner = (_length(item, "inner_diameter") or 0.0) / 2
            return {"outer": (outer,), "bore": (inner,)}.get(which, (outer, inner))

        return rims(copy, which, radii)


ENTRY = Tube()
