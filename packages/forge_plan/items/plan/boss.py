"""What the planner writes for a boss: its entry in the ``plan`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
boss's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item
from forge_spec.geometry import FlatFace, disc

from forge_plan.items.plan._edges import _rims
from forge_plan.items.plan._families import StandingPlan
from forge_plan.items.plan._tools import _bounds_of_cylinder, _id, _mm, _rod
from forge_plan.write import Ref, add

if TYPE_CHECKING:
    from forge_spec.geometry import Part
    from forge_spec.placement import Instance

    from forge_plan.items.plan._edges import Queries
    from forge_plan.write import Chain

Vec = tuple[float, float, float]


class Boss(StandingPlan):
    key = "boss"

    threadable = True
    rod_length = "height"

    def standing_tool(
        self, chain: Chain, item: Item, copy: Instance, behind: float
    ) -> str:
        k, w, u = copy.index, copy.origin, copy.normal
        d, h = _mm(item, "diameter"), _mm(item, "height")
        # Its box is the boss's own: the sunk part is within the part already.
        return _rod(
            chain,
            item,
            k,
            add(w, u, -behind),
            u,
            d,
            h + behind,
            own=_bounds_of_cylinder(w, u, d / 2, h),
        )

    def sink_footprint(
        self, item: Item, face: FlatFace, copy: Instance
    ) -> tuple[tuple[Part, ...], dict[str, float]]:
        r = _mm(item, "diameter") / 2
        return (disc(r),), dict.fromkeys(face.axes, r)

    def round_side_prism(
        self, chain: Chain, item: Item, copy: Instance, reach: float
    ) -> tuple[str, Vec, Vec]:
        k, w, u = copy.index, copy.origin, copy.normal
        d, h = _mm(item, "diameter"), _mm(item, "height")
        prism = chain.cylinder(
            _id(item.id, k, "rod"), add(w, u, -reach), u, d, reach + h, item=item.id
        )
        chain.name(item.id, k, "+end", Ref(prism, "top"))
        chain.name(item.id, k, "side", Ref(prism, "lateral"))
        lo, hi = _bounds_of_cylinder(add(w, u, -reach), u, d / 2, reach + h)
        return prism, lo, hi

    def own_edges(self, chain: Chain, queries: Queries, target: Item, copy: Instance, which: str,
                  open_faces: set[str], part: str | None) -> frozenset[frozenset[str]]:  # fmt: skip
        return _rims(chain, queries, target, copy, which, open_faces, part)


ENTRY = Boss()
