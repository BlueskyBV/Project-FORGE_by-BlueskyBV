"""What the planner writes for a cone: its entry in the ``plan`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
cone's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item

from forge_plan.items.plan._edges import _rims
from forge_plan.items.plan._families import BodyPlan
from forge_plan.items.plan._tools import _bounds_of_cylinder, _id, _mm
from forge_plan.write import Box, Ref

if TYPE_CHECKING:
    from forge_spec.placement import Instance

    from forge_plan.items.plan._edges import Queries
    from forge_plan.tools import Context
    from forge_plan.write import Chain

Vec = tuple[float, float, float]


class Cone(BodyPlan):
    key = "cone"

    def body_tool(
        self, chain: Chain, ctx: Context, item: Item, copy: Instance, dome_cut: bool
    ) -> str:
        k, o, u = copy.index, copy.origin, copy.normal
        base, top, long = (
            _mm(item, "base_diameter"),
            _mm(item, "top_diameter"),
            _mm(item, "length"),
        )
        from forge_plan.seams import cone_motion

        turn = cone_motion(ctx, item.id, k, o, u, min(base, top) / 2)
        if turn is not None:
            chain.seams[(item.id, k)] = turn
        made = chain.cone(_id(item.id, k, "cone"), o, u, base, top, long, item=item.id)
        tool = chain.seamed(made, (item.id, k), item=item.id)
        if top > 0.0:
            chain.name(item.id, k, "+end", Ref(made, "top"))
        chain.name(item.id, k, "-end", Ref(made, "base"))
        chain.name(item.id, k, "side", Ref(made, "lateral"))
        chain.add_box(
            Box(*_bounds_of_cylinder(o, u, max(base, top) / 2, long), item.id, k)
        )
        return tool

    def own_edges(self, chain: Chain, queries: Queries, target: Item, copy: Instance, which: str,
                  open_faces: set[str], part: str | None) -> frozenset[frozenset[str]]:  # fmt: skip
        return _rims(chain, queries, target, copy, which, open_faces, part)

    def outer_rim(self, target: Item, end: str) -> float:
        return _mm(target, "top_diameter" if end == "+end" else "base_diameter") / 2


ENTRY = Cone()
