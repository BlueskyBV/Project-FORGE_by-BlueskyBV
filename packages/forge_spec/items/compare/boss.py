"""What the two-draft comparison reads of a boss: its entry in the ``compare`` registry (its branches moved from ``compare.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from collections.abc import Iterable

from forge_spec.draft import Item
from forge_spec.items.compare._common import Feature, _Edge, _mid, _r, _sub, _up, rims
from forge_spec.items.compare.protocol import CompareKind
from forge_spec.placement import Instance


class Boss(CompareKind):
    key = "boss"

    def solid(self, n: int, item: Item, copy: Instance) -> list[Feature]:
        assert copy.lo is not None and copy.hi is not None
        lo, hi, kind = copy.lo, copy.hi, item.kind
        sizes, centre = _sub(hi, lo), _mid(lo, hi)
        up = _up(copy)
        across = (hi[(up + 1) % 3] - lo[(up + 1) % 3]) / 2
        axis = (copy.normal, False)
        return [
            Feature(
                n,
                item.id,
                kind,
                "rod",
                sizes,
                centre,
                (_r(2 * across),),
                (axis,),
                field="diameter",
            )
        ]

    def edges(self, item: Item, copy: Instance, which: str) -> Iterable[_Edge]:
        return rims(copy, which, lambda end, outer: (outer,))


ENTRY = Boss()
