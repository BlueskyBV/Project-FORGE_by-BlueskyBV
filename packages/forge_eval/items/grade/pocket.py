"""What spec grading reads for a pocket: its entry in the ``grade`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
pocket's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from forge_numeric import scalar as fs
from forge_spec.draft import Item
from forge_spec.placement import Layout, mm
from forge_spec.values import Value

from forge_eval.items.grade.protocol import GradeKind
from forge_eval.spec_grade import _choice


class Pocket(GradeKind):
    key = "pocket"
    cut_out = True

    def reach(self, item: Item, layout: Layout) -> float | None:
        size = {
            n: mm(v)
            for n in ("length", "width", "diameter")
            if isinstance(v := item.get(n), Value)
        }
        if _choice(item, "shape") == "circle":
            return size["diameter"] / 2 if "diameter" in size else None
        if "length" in size and "width" in size:
            return fs.hypot(size["length"], size["width"]) / 2
        return None

    def through_diameter(self, item: Item, layout: Layout) -> float | None:
        if _choice(item, "shape") != "circle":
            return None
        size = item.get("diameter")
        return mm(size) if isinstance(size, Value) else None


ENTRY = Pocket()
