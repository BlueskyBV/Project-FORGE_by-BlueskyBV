"""What the spec checks read of a region: its entry in the ``checks`` registry (its branches moved from ``checks.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.draft import Item, PartSpec
from forge_spec.items.checks._common import Collect
from forge_spec.items.checks.protocol import SpecCheckKind
from forge_spec.placement import Layout, mm
from forge_spec.problems import pointer
from forge_spec.values import Value


class Region(SpecCheckKind):
    key = "region"

    def physical(
        self, spec: PartSpec, item: Item, at: str, layout: Layout, c: Collect
    ) -> None:
        wall = item.get("min_wall")
        sizes = [
            v
            for v in (item.get(n) for n in ("length", "width", "height"))
            if isinstance(v, Value)
        ]
        if (
            isinstance(wall, Value)
            and sizes
            and mm(wall) > min(mm(v) for v in sizes) + 1e-9
        ):
            smallest = min(sizes, key=mm)
            c.problem("cant", at + pointer("min_wall"),
                      f"a {mm(wall):g} mm wall can't fit in a region {mm(smallest):g} mm across", wall, smallest)  # fmt: skip


ENTRY = Region()
