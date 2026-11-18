"""What the planner writes for a slot: its entry in the ``plan`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
slot's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item
from forge_spec.geometry import Face, FlatFace, rect, slot_outline
from forge_spec.placement import Instance

from forge_plan.errors import PlanError
from forge_plan.items.plan._edges import _choice, _mm
from forge_plan.items.plan._families import CutPlan
from forge_plan.items.plan._tools import _cut_depth, _extrude_into, _footprint_box
from forge_plan.write import Box, Chain, Ref, length

if TYPE_CHECKING:
    from forge_spec.geometry import Part
    from forge_spec.placement import Instance

    from forge_plan.tools import Context
    from forge_plan.write import Chain

Vec = tuple[float, float, float]


def _slot(
    chain: Chain, item: Item, copy: Instance, face: FlatFace, mouth: float, far: float
) -> str:
    k, w = copy.index, copy.origin
    long, wide = _mm(item, "length"), _mm(item, "width")
    first = _choice(item, "along") == face.axes[0]
    round_ends = _choice(item, "ends") == "round"
    _, parts = ENTRY.outline_of(item, face)
    depth = _cut_depth(item, face, parts, copy)
    if round_ends:
        op, params = "profile_slot", {"length": length(long), "width": length(wide),
                                      "rotation": {"magnitude": 0.0 if first else 90.0, "unit": "deg"}}  # fmt: skip
    else:
        size = (long, wide) if first else (wide, long)
        op, params = (
            "profile_rectangle",
            {"width": length(size[0]), "height": length(size[1])},
        )
    tool, _, floor = _extrude_into(
        chain, item, k, face, w, depth, op, params, mouth, far
    )
    chain.name(item.id, k, "wall", Ref(tool, "side"))
    chain.name(item.id, k, "floor", Ref(tool, floor))
    halves = (long / 2, wide / 2) if first else (wide / 2, long / 2)
    chain.cut_box(Box(*_footprint_box(face, w, halves, depth), item.id, k))
    return tool


class Slot(CutPlan):
    key = "slot"

    def cut_tool(self, chain: Chain, ctx: Context, item: Item, copy: Instance, face: Face,
                 mouth: float, far: float) -> list[str]:  # fmt: skip
        if not isinstance(face, FlatFace):
            raise PlanError(f"a {item.kind} goes into flat faces only", item=item.id)
        return [_slot(chain, item, copy, face, mouth, far)]

    def outline_of(
        self, item: Item, face: FlatFace
    ) -> tuple[tuple[float, float], tuple[Part, ...]]:
        long, wide = _mm(item, "length"), _mm(item, "width")
        first = _choice(item, "along") == face.axes[0]
        if _choice(item, "ends") == "round":
            parts = slot_outline(long, wide, along_first=first)
        else:
            parts = (
                (rect(long / 2, wide / 2),) if first else (rect(wide / 2, long / 2),)
            )
        return ((long / 2, wide / 2) if first else (wide / 2, long / 2)), parts

    def pieces(self, cut: Item) -> int:
        return 4


ENTRY = Slot()
