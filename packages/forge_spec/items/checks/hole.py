"""What the spec checks read of a hole: its entry in the ``checks`` registry (its branches moved from ``checks.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.draft import Counterbore, Countersink, Item, PartSpec
from forge_spec.items.checks._common import Collect, cut_rounding_limit
from forge_spec.items.checks.protocol import SpecCheckKind
from forge_spec.placement import Layout, mm
from forge_spec.problems import pointer


class Hole(SpecCheckKind):
    key = "hole"

    def physical(
        self, spec: PartSpec, item: Item, at: str, layout: Layout, c: Collect
    ) -> None:
        d = layout.diameters.get(item.id)
        for extra in ("counterbore", "countersink"):
            recess = item.get(extra)
            if (
                isinstance(recess, (Counterbore, Countersink))
                and d is not None
                and mm(recess.diameter) <= d
            ):
                c.problem("question", at + pointer(extra),
                          f"a {extra} {mm(recess.diameter):g} mm across is no wider than its {d:g} mm hole",
                          recess.diameter, item.get("diameter"))  # fmt: skip

    def rounding_limit(self, target: Item, which: str, layout: Layout) -> float | None:
        return cut_rounding_limit(target, layout)


ENTRY = Hole()
