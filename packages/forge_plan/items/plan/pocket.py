"""What the planner writes for a pocket: its entry in the ``plan`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
pocket's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item
from forge_spec.geometry import FlatFace, Part, SideFace, disc, rounded_rect
from forge_spec.placement import Instance
from forge_spec.schema import DIRECTIONS

from forge_plan.errors import PlanError
from forge_plan.items.plan._edges import _choice, _mm
from forge_plan.items.plan._families import CutPlan
from forge_plan.items.plan._tools import (
    _cut_depth,
    _extrude_into,
    _footprint_box,
    _id,
    _mm_or,
    _span_box,
)
from forge_plan.write import Box, Chain, Ref, length, neg, role_of, unit

if TYPE_CHECKING:
    from forge_spec.geometry import Part
    from forge_spec.placement import Instance

    from forge_plan.tools import Context
    from forge_plan.write import Chain

Vec = tuple[float, float, float]


def _pocket(
    chain: Chain, item: Item, copy: Instance, face: FlatFace, mouth: float, far: float
) -> str:
    k, w = copy.index, copy.origin
    if _choice(item, "shape") == "circle":
        d = _mm(item, "diameter")
        parts: tuple[Part, ...] = (disc(d / 2),)
        depth = _cut_depth(item, face, parts, w)
        tool, _, floor = _extrude_into(chain, item, k, face, w, depth, "profile_circle",
                                       {"diameter": length(d)}, mouth, far)  # fmt: skip
        chain.name(item.id, k, "wall", Ref(tool, "side"))
        chain.name(item.id, k, "bottom", Ref(tool, floor))
        chain.cut_box(Box(*_footprint_box(face, w, (d / 2, d / 2), depth), item.id, k))
        return tool
    long, wide = _mm(item, "length"), _mm(item, "width")
    r = _mm_or(item, "corner_radius", 0.0)
    parts = rounded_rect(long / 2, wide / 2, r)
    depth = _cut_depth(item, face, parts, w)
    a1, a2 = face.axes
    box = Box(*_footprint_box(face, w, (long / 2, wide / 2), depth), item.id, k)
    chain.cut_box(box)
    if r <= 0.0:
        carried = _span_box(
            w, neg(unit(face.normal)), -mouth, depth + far, {a1: long / 2, a2: wide / 2}
        )
        tool = chain.box(_id(item.id, k, "cut"), *carried, item=item.id)
        inward = neg(unit(face.normal))
        floor = next(n for n in DIRECTIONS if unit(n) == inward)
        walls = [n for n in DIRECTIONS if n[1] in (a1, a2)]
        chain.name(item.id, k, "wall", *(Ref(tool, role_of(n)) for n in walls))
        chain.name(item.id, k, "bottom", Ref(tool, role_of(floor)))
        return tool
    short = min(long, wide) / 2
    if (
        r >= long / 2 - 1e-9 and r >= wide / 2 - 1e-9
    ):  # rounded all across both ways: a circle
        op, params = "profile_circle", {"diameter": length(long)}
    elif r >= short - 1e-9:  # rounded all across its width: a stadium along its length
        op, params = "profile_slot", {
            "length": length(max(long, wide)), "width": length(min(long, wide)),
            "rotation": {"magnitude": 0.0 if long >= wide else 90.0, "unit": "deg"}}  # fmt: skip
    else:
        op, params = "profile_rectangle", {"width": length(long), "height": length(wide),
                                           "corner_radius": length(r)}  # fmt: skip
    tool, _, floor = _extrude_into(
        chain, item, k, face, w, depth, op, params, mouth, far
    )
    chain.name(item.id, k, "wall", Ref(tool, "side"))
    chain.name(item.id, k, "bottom", Ref(tool, floor))
    return tool


class Pocket(CutPlan):
    key = "pocket"

    floored = True

    def cut_tool(self, chain: Chain, ctx: Context, item: Item, copy: Instance, face: FlatFace | SideFace,
                 mouth: float, far: float) -> list[str]:  # fmt: skip
        if not isinstance(face, FlatFace):
            raise PlanError(f"a {item.kind} goes into flat faces only", item=item.id)
        return [_pocket(chain, item, copy, face, mouth, far)]

    def outline_of(
        self, item: Item, face: FlatFace
    ) -> tuple[tuple[float, float], tuple[Part, ...]]:
        if _choice(item, "shape") == "circle":
            r = _mm(item, "diameter") / 2
            return (r, r), (disc(r),)
        long, wide = _mm(item, "length"), _mm(item, "width")
        return (long / 2, wide / 2), rounded_rect(
            long / 2, wide / 2, _mm_or(item, "corner_radius", 0.0)
        )

    def pieces(self, cut: Item) -> int:
        if _choice(cut, "shape") == "circle":
            return 1
        return super().pieces(cut)


ENTRY = Pocket()
