"""What the planner writes for a rib: its entry in the ``plan`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
rib's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item

from forge_plan.items.plan._families import StandingPlan
from forge_plan.items.plan._tools import _choice, _mm

if TYPE_CHECKING:
    pass

Vec = tuple[float, float, float]


class Rib(StandingPlan):
    key = "rib"

    def box_like(self, item: Item) -> bool:
        return True

    def section(
        self, item: Item, axes: tuple[str, str]
    ) -> tuple[dict[str, float], float]:
        a1, a2 = axes
        run = _choice(item, "along") or a1
        other = a2 if run == a1 else a1
        return {run: _mm(item, "length") / 2, other: _mm(item, "thickness") / 2}, _mm(
            item, "height"
        )


ENTRY = Rib()
