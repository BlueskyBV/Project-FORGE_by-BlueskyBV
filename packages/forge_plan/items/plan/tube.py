"""What the planner writes for a tube: its entry in the ``plan`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
tube's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item

from forge_plan.items.plan._edges import _rims
from forge_plan.items.plan._families import BodyPlan
from forge_plan.items.plan._tools import _BORE_PAST, _bounds_of_cylinder, _id, _mm
from forge_plan.write import Box, Ref, add

if TYPE_CHECKING:
    from forge_spec.placement import Instance

    from forge_plan.items.plan._edges import Queries
    from forge_plan.tools import Context
    from forge_plan.write import Chain

Vec = tuple[float, float, float]


class Tube(BodyPlan):
    key = "tube"

    bored = True

    def body_tool(
        self, chain: Chain, ctx: Context, item: Item, copy: Instance, dome_cut: bool
    ) -> str:
        k, o, u = copy.index, copy.origin, copy.normal
        outer, inner, long = (
            _mm(item, "outer_diameter"),
            _mm(item, "inner_diameter"),
            _mm(item, "length"),
        )
        rod = chain.cylinder(_id(item.id, k, "outer"), o, u, outer, long, item=item.id)
        bore = chain.cylinder(_id(item.id, k, "bore"), add(o, u, -_BORE_PAST), u, inner,
                              long + 2 * _BORE_PAST, item=item.id)  # fmt: skip
        tool = chain.boolean(
            _id(item.id, k, "tube"), "subtract", [rod, bore], item=item.id
        )
        chain.name(item.id, k, "+end", Ref(rod, "top"))
        chain.name(item.id, k, "-end", Ref(rod, "base"))
        chain.name(item.id, k, "side", Ref(rod, "lateral"))
        chain.name(item.id, k, "bore", Ref(bore, "lateral"))
        chain.add_box(Box(*_bounds_of_cylinder(o, u, outer / 2, long), item.id, k))
        return tool

    def own_edges(self, chain: Chain, queries: Queries, target: Item, copy: Instance, which: str,
                  open_faces: set[str], part: str | None) -> frozenset[frozenset[str]]:  # fmt: skip
        return _rims(chain, queries, target, copy, which, open_faces, part)

    def outer_rim(self, target: Item, end: str) -> float:
        return _mm(target, "outer_diameter") / 2


ENTRY = Tube()
