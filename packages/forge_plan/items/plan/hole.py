"""What the planner writes for a hole: its entry in the ``plan`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
hole's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from forge_numeric import scalar as fs
from forge_spec.draft import Counterbore, Countersink, Item
from forge_spec.geometry import BallFace, Face, FlatFace, SideFace, disc
from forge_spec.placement import Instance

from forge_plan.errors import PlanError
from forge_plan.items.plan._edges import _mm
from forge_plan.items.plan._families import CutPlan
from forge_plan.items.plan._tools import (
    _bounds_of_cylinder,
    _cut_depth,
    _id,
    _start,
    _through,
)
from forge_plan.write import Box, Chain, Ref, add, box_round, neg

if TYPE_CHECKING:
    from forge_spec.geometry import Part
    from forge_spec.placement import Instance

    from forge_plan.tools import Context
    from forge_plan.write import Chain

Vec = tuple[float, float, float]


def _widest(ctx: Context, item: Item) -> tuple[float, float]:
    """A hole's radius, and its widest radius (its counterbore's or countersink's, if wider)."""
    diameter = ctx.layout.diameters.get(item.id)
    if diameter is None:
        raise PlanError("its diameter wasn't resolved", item=item.id)
    radius = widest = diameter / 2
    counterbore, countersink = item.get("counterbore"), item.get("countersink")
    if isinstance(counterbore, Counterbore):
        widest = max(widest, counterbore.diameter.made_in("mm") / 2)
    if isinstance(countersink, Countersink):
        widest = max(widest, countersink.diameter.made_in("mm") / 2)
    return radius, widest


def _hole(chain: Chain, ctx: Context, item: Item, copy: Instance, face: Face,
          mouth: float, far: float) -> list[str]:  # fmt: skip
    k, w = copy.index, copy.origin
    d = neg(copy.normal)
    diameter = ctx.layout.diameters.get(item.id)
    if diameter is None:
        raise PlanError("its diameter wasn't resolved", item=item.id)
    radius = diameter / 2
    start = _start(face)
    if isinstance(face, (SideFace, BallFace)):
        depth = (
            face.most_material_under((disc(radius),)) if _through(item) else _mm(item, "depth")
        )
    else:
        depth = _cut_depth(item, face, (disc(radius),), w)
    pieces: list[str] = []
    begin = start - mouth
    bore = chain.cylinder(_id(item.id, k, "bore"), add(w, d, begin), d, diameter, depth + far - begin,
                          item=item.id)  # fmt: skip
    pieces.append(bore)
    chain.name(item.id, k, "wall", Ref(bore, "lateral"))
    chain.name(item.id, k, "floor", Ref(bore, "top"))
    lo, hi = _bounds_of_cylinder(add(w, d, start), d, radius, depth - start)
    counterbore, countersink = item.get("counterbore"), item.get("countersink")
    if isinstance(counterbore, Counterbore):
        wide = counterbore.diameter.made_in("mm")
        deep = counterbore.depth.made_in("mm")
        step = chain.cylinder(_id(item.id, k, "counterbore"), add(w, d, begin), d, wide, deep - begin,
                              item=item.id)  # fmt: skip
        pieces.append(step)
        chain.name(item.id, k, "counterbore_wall", Ref(step, "lateral"))
        chain.name(item.id, k, "counterbore_floor", Ref(step, "top"))
        lo, hi = box_round(
            [lo, hi, *_bounds_of_cylinder(add(w, d, start), d, wide / 2, deep - start)]
        )
    if isinstance(countersink, Countersink):
        wide = countersink.diameter.made_in("mm")
        angle = countersink.angle.made_in("deg")
        deep = (wide - diameter) / 2 / fs.tan(math.radians(angle) / 2)
        cone = chain.cone(
            _id(item.id, k, "countersink"), w, d, wide, diameter, deep, item=item.id
        )
        pieces.append(cone)
        chain.name(item.id, k, "countersink", Ref(cone, "lateral"))
        lo, hi = box_round([lo, hi, *_bounds_of_cylinder(w, d, wide / 2, deep)])
        if (
            start < 0.0
        ):  # inside a bore: no lip of the wall left in front of it (hole.md)
            front = chain.cylinder(_id(item.id, k, "countersink_front"), add(w, d, start), d, wide,
                                   -start, item=item.id)  # fmt: skip
            pieces.append(front)
        elif mouth:  # carried: the countersink's mouth runs on into the air as wide
            air = chain.cylinder(_id(item.id, k, "countersink_air"), add(w, d, -mouth), d, wide, mouth,
                                 item=item.id)  # fmt: skip
            pieces.append(air)
    chain.cut_box(Box(lo, hi, item.id, k))
    return pieces


class Hole(CutPlan):
    key = "hole"

    goes_round_side = True

    def cut_tool(self, chain: Chain, ctx: Context, item: Item, copy: Instance, face: Face,
                 mouth: float, far: float) -> list[str]:  # fmt: skip
        return _hole(chain, ctx, item, copy, face, mouth, far)

    def into_round_side(self, ctx: Context, item: Item) -> bool:
        for copy in ctx.layout.instances.get(item.id, []):
            face = ctx.face(copy)
            if isinstance(face, SideFace) and face.outward:
                return True
        return False

    def widest(self, ctx: Context, item: Item) -> tuple[float, float]:
        return _widest(ctx, item)

    def air_outline(
        self, ctx: Context, item: Item, face: FlatFace
    ) -> tuple[tuple[float, float], tuple[float, float], tuple[Part, ...]]:
        radius, widest = _widest(ctx, item)
        return (widest, widest), (radius, radius), (disc(radius),)

    def pieces(self, cut: Item) -> int:
        return 1


ENTRY = Hole()
