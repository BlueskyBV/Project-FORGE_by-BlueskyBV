"""What spec grading reads for a hole: its entry in the ``grade`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
hole's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from forge_spec.draft import Counterbore, Countersink, Item
from forge_spec.placement import Layout, mm

from forge_eval.items.grade.protocol import GradeKind


class Hole(GradeKind):
    key = "hole"
    cut_out = True

    def reach(self, item: Item, layout: Layout) -> float | None:
        hole = layout.diameters.get(item.id)
        if hole is None:
            return None
        rims = [mm(x.diameter) for x in (item.get("counterbore"), item.get("countersink"))
                if isinstance(x, (Counterbore, Countersink))]  # fmt: skip
        return max([hole, *rims]) / 2

    def through_diameter(self, item: Item, layout: Layout) -> float | None:
        return layout.diameters.get(item.id)


ENTRY = Hole()
