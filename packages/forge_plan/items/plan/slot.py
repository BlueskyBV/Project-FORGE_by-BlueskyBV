"""What the planner writes for a slot: its entry in the ``plan`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
slot's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_numeric import scalar as fs
from forge_spec.draft import Item
from forge_spec.ends import ThroughAll, end_of
from forge_spec.frames import Rigid
from forge_spec.geometry import Face, FlatFace, SideFace, disc, rect, slot_outline
from forge_spec.placement import Instance

from forge_plan.errors import PlanError
from forge_plan.items.plan._edges import _choice, _mm
from forge_plan.items.plan._families import CutPlan
from forge_plan.items.plan._tools import (
    _cut_depth,
    _extrude_along,
    _extrude_into,
    _footprint_box,
)
from forge_plan.write import (
    DATUMS,
    PLANE_AXES,
    Box,
    Chain,
    Ref,
    add,
    axis_of,
    box_round,
    length,
    neg,
)

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


def _dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def keyway_frame(face: SideFace, copy: Instance) -> tuple[Vec, Vec, Rigid]:
    """A keyway made upright (slot.md, "Round a side"): the way out at the quarter turn round the side at or below its
    own (a frame axis's), its point turned back there, and the turn about the side's axis that takes it to its own."""
    frame = face.frame
    u, v, a = frame.u, frame.v, frame.n
    r = copy.normal
    c, s = _dot(r, u), _dot(r, v)
    k = 0 if c > 0 and s >= 0 else 1 if c <= 0 and s > 0 else 2 if c < 0 and s <= 0 else 3
    quarter = (u, v, neg(u), neg(v))[k]
    dc, ds = _dot(r, quarter), _dot(r, _cross(a, quarter))
    size = fs.hypot(dc, ds)
    dc, ds = dc / size, ds / size
    back = Rigid.turn_about(frame.origin, a, dc, -ds)
    return quarter, back.point(copy.origin), Rigid.turn_about(frame.origin, a, dc, ds)


def _keyway(chain: Chain, item: Item, copy: Instance, face: SideFace, mouth: float, far: float) -> str:
    """A slot round a side (slot.md, "Round a side"): its outline on the plane touching the side along the line through
    its point, its length along the side's axis, in square to that plane to its depth, or right through as far as a
    hole as wide would go. Made upright, as at the quarter turn round the side at or below it (its way out a frame
    axis's), then turned with the side about its axis by the rest."""
    k = copy.index
    long, wide = _mm(item, "length"), _mm(item, "width")
    out, w, turn = keyway_frame(face, copy)
    axes = PLANE_AXES[DATUMS[axis_of(out)][0]]
    first = _choice(item, "along") == axes[0]
    depth = face.most_material_under((disc(wide / 2),)) if isinstance(end_of(item), ThroughAll) else _mm(item, "depth")
    if _choice(item, "ends") == "round":
        op, params = "profile_slot", {"length": length(long), "width": length(wide),
                                      "rotation": {"magnitude": 0.0 if first else 90.0, "unit": "deg"}}  # fmt: skip
    else:
        size = (long, wide) if first else (wide, long)
        op, params = "profile_rectangle", {"width": length(size[0]), "height": length(size[1])}
    i = next(j for j in range(3) if abs(out[j]) > 0.5)
    made, _, floor = _extrude_along(chain, item, k, ("+" if out[i] > 0 else "-") + "xyz"[i], axes, w, depth, op,
                                    params, mouth, far)  # fmt: skip
    chain.name(item.id, k, "wall", Ref(made, "side"))
    chain.name(item.id, k, "floor", Ref(made, floor))
    along_axis = face.frame.n
    across = _cross(along_axis, out)
    corners = [turn.point(add(add(add(w, along_axis, sa * long / 2), across, sc * wide / 2), out, -t))
               for sa in (-1.0, 1.0) for sc in (-1.0, 1.0) for t in (0.0, depth)]  # fmt: skip
    chain.cut_box(Box(*box_round(corners), item.id, k))
    if turn.is_identity:
        return made
    from forge_plan.moved import transform_params

    return chain.step(f"{made}.about", "transform", transform_params(turn), item=item.id, inputs=(made,))


class Slot(CutPlan):
    key = "slot"
    keyway = True

    def cut_tool(self, chain: Chain, ctx: Context, item: Item, copy: Instance, face: Face,
                 mouth: float, far: float) -> list[str]:  # fmt: skip
        if isinstance(face, SideFace):
            return [_keyway(chain, item, copy, face, mouth, far)]
        if not isinstance(face, FlatFace):
            raise PlanError(f"a {item.kind} goes into flat faces and round sides only", item=item.id)
        return [_slot(chain, item, copy, face, mouth, far)]

    def into_round_side(self, ctx: Context, item: Item) -> bool:
        """A keyway's definition's tool touches the side along the line through its point: carried first (5.2)."""
        return any(isinstance(face := ctx.face(copy), SideFace) and face.outward
                   for copy in ctx.layout.instances.get(item.id, []))  # fmt: skip

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
