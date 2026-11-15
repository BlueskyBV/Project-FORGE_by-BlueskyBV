"""What the two-draft comparison reads of a cone: its entry in the ``compare`` registry (its branches moved from ``compare.py`` at stage 4b.0b's step 3)."""

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
    rims,
)
from forge_spec.items.compare.protocol import CompareKind
from forge_spec.placement import Instance


class Cone(CompareKind):
    key = "cone"

    def solid(self, n: int, item: Item, copy: Instance) -> list[Feature]:
        assert copy.lo is not None and copy.hi is not None
        lo, hi, kind = copy.lo, copy.hi, item.kind
        sizes, centre = _sub(hi, lo), _mid(lo, hi)
        base, top = (
            _length(item, "base_diameter") or 0.0,
            _length(item, "top_diameter") or 0.0,
        )
        return [
            Feature(
                n,
                item.id,
                kind,
                "cone",
                sizes,
                centre,
                (_r(base), _r(top)),
                ((copy.normal, True),),
            )
        ]

    def edges(self, item: Item, copy: Instance, which: str) -> Iterable[_Edge]:
        def radii(end: str, outer: float) -> tuple[float, ...]:
            return (
                (
                    _length(item, "top_diameter" if end == "+" else "base_diameter")
                    or 0.0
                )
                / 2,
            )

        return rims(copy, which, radii)


ENTRY = Cone()
