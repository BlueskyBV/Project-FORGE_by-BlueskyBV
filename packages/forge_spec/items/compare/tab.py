"""What the two-draft comparison reads of a tab: its entry in the ``compare`` registry (its branches moved from ``compare.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.draft import Item
from forge_spec.items.compare._common import Feature, _choice, _length, _mid, _r, _sub
from forge_spec.items.compare.protocol import CompareKind
from forge_spec.placement import Instance
from forge_spec.problems import pointer


class Tab(CompareKind):
    key = "tab"

    def solid(self, n: int, item: Item, copy: Instance) -> list[Feature]:
        assert copy.lo is not None and copy.hi is not None
        lo, hi, kind = copy.lo, copy.hi, item.kind
        sizes, centre = _sub(hi, lo), _mid(lo, hi)
        if _choice(item, "end") != "round":
            return [Feature(n, item.id, kind, "box", sizes, centre)]
        width = _length(item, "width") or 0.0
        return [
            Feature(
                n,
                item.id,
                kind,
                "round-ended tab",
                sizes,
                centre,
                (_r(width),),
                ((copy.normal, True),),
            )
        ]

    def shape_differs(
        self, mine: Feature, other: Feature, here: str
    ) -> tuple[str, str] | None:
        name, shape = mine.item, mine.shape
        ends = {"box": "square", "round-ended tab": "round"}
        return here + pointer("end"), (f"{name}'s end is {ends.get(shape, shape)} here, "
                                       f"{ends.get(other.shape, other.shape)} in the second draft")  # fmt: skip


ENTRY = Tab()
