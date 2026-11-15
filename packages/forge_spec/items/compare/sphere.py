"""What the two-draft comparison reads of a sphere: its entry in the ``compare`` registry (its branches moved from ``compare.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from collections.abc import Iterable

from forge_spec.draft import Item
from forge_spec.items.compare._common import (
    Feature,
    _choice,
    _Edge,
    _length,
    _mid,
    _r,
    _sub,
    rims,
)
from forge_spec.items.compare.protocol import CompareKind
from forge_spec.placement import Instance


class Sphere(CompareKind):
    key = "sphere"

    def solid(self, n: int, item: Item, copy: Instance) -> list[Feature]:
        assert copy.lo is not None and copy.hi is not None
        lo, hi, kind = copy.lo, copy.hi, item.kind
        sizes, centre = _sub(hi, lo), _mid(lo, hi)
        diameter = _r(_length(item, "diameter") or 0.0)
        if _choice(item, "portion") == "upper_half":
            return [
                Feature(
                    n,
                    item.id,
                    kind,
                    "dome",
                    sizes,
                    copy.origin,
                    (diameter,),
                    ((copy.normal, True),),
                )
            ]
        return [Feature(n, item.id, kind, "ball", sizes, centre, (diameter,))]

    def edges(self, item: Item, copy: Instance, which: str) -> Iterable[_Edge]:
        return rims(copy, which, lambda end, outer: (outer,))


ENTRY = Sphere()
