"""What the planner writes for an extrusion: its entry in the ``plan`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
extrusion's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from forge_spec.draft import Item
from forge_spec.placement import Instance

from forge_plan.errors import PlanError
from forge_plan.items.plan._edges import (
    Queries,
    _arc_box,
    _box_of,
    _count,
    _mm,
    _profile,
    _sides,
    _tangent,
    _vec,
    _within,
    circle_where,
)
from forge_plan.items.plan._families import BodyPlan
from forge_plan.items.plan._tools import _id, outline_points
from forge_plan.write import (
    DATUMS,
    PLANE_AXES,
    Box,
    Chain,
    Ref,
    Vec,
    add,
    along,
    axis_of,
    unit,
)

if TYPE_CHECKING:
    from forge_spec.placement import Instance

    from forge_plan.items.plan._edges import Queries
    from forge_plan.tools import Context
    from forge_plan.write import Chain


def _extrusion(chain: Chain, item: Item, copy: Instance) -> str:
    """An extrusion (4.3): its outline drawn on the plane of its -end, from its point along the face's axes, pushed ``length`` along its axis."""
    k, o, u = copy.index, copy.origin, copy.normal
    axis = axis_of(u)
    base, sign = DATUMS[axis]
    a1, a2 = PLANE_AXES[base]
    if copy.face_axes is not None and copy.face_axes != (a1, a2):
        raise PlanError(
            f"its outline lies along {copy.face_axes}, not the plane's {(a1, a2)}",
            item=item.id,
        )
    plane = chain.datum(_id(item.id, k, "plane"), axis, along(o, axis), item=item.id)
    points = outline_points(_profile(item), (along(o, a1), along(o, a2)))
    outline = chain.profile(_id(item.id, k, "outline"), "profile_outline", plane,
                            {"points": {"points": points, "unit": "mm"}}, item=item.id)  # fmt: skip
    mode = "normal" if u["xyz".index(axis)] == sign else "reverse"
    tool = chain.extrude(
        _id(item.id, k, "body"), outline, _mm(item, "length"), mode, item=item.id
    )
    # The extrusion's start is its low end along the datum's normal: the plane, or the far end reversed.
    near, far = (
        ("start_face", "end_face") if mode == "normal" else ("end_face", "start_face")
    )
    chain.name(item.id, k, "+end", Ref(tool, far))
    chain.name(item.id, k, "-end", Ref(tool, near))
    chain.name(item.id, k, "side", Ref(tool, "side"))
    assert copy.lo is not None and copy.hi is not None
    chain.add_box(Box(copy.lo, copy.hi, item.id, k))
    return tool


def _extrusion_edges(chain: Chain, queries: Queries, target: Item, copy: Instance,
                     which: str) -> frozenset[frozenset[str]]:  # fmt: skip
    """An extrusion's edges (extrusion.md): round each end, a line or an arc's circle for each side of its outline; along its axis, a line at each corner where two sides meet at an angle."""
    if which not in ("top", "bottom", "vertical", "all"):
        raise PlanError(f"an extrusion has no {which!r} edges", item=target.id)
    key = (target.id, copy.index)
    names = chain.names_of(target.id, copy.index)
    o, u = copy.origin, copy.normal
    # Its outline's axes: the face's it stands on, or (the first body) its -end plane's.
    a1, a2 = (
        unit("+" + a) for a in (copy.face_axes or PLANE_AXES[DATUMS[axis_of(u)][0]])
    )
    length = _mm(target, "length")
    sides = _sides(_profile(target))

    def world(p: tuple[float, float], height: float) -> Vec:
        return add(add(add(o, a1, p[0]), a2, p[1]), u, height)

    pairs: list[tuple[str, str]] = []
    for end, height in (("+end", length), ("-end", 0.0)):
        if which not in ({"+end": "top", "-end": "bottom"}[end], "all"):
            continue
        pairs.append((end, "side"))
        for a, b, centre, clockwise in sides:
            if centre is None:
                start, stop = world(a, height), world(b, height)
                run = math.dist(a, b)
                where = {"kind": "line", "axis": _vec([(stop[i] - start[i]) / run for i in range(3)]),
                         "through": _vec(start), "within": _within(*_box_of(start, stop))}  # fmt: skip
            else:
                (l1, l2), (h1, h2) = _arc_box(a, b, centre, clockwise)
                where = {**circle_where(world(centre, height), u, math.dist(a, centre)),
                         "within": _within(*_box_of(world((l1, l2), height), world((h1, h2), height)))}  # fmt: skip
            queries.add(
                names[end], names["side"], where=where, count=_count(chain, where, key)
            )
    if which in ("vertical", "all"):
        pairs.append(("side", "side"))
        for k, side in enumerate(sides):
            after = sides[(k + 1) % len(sides)]
            t_in, t_out = _tangent(side, True), _tangent(after, False)
            if t_in[0] * t_out[0] + t_in[1] * t_out[1] > 1.0 - 1e-9:
                continue  # they run on smoothly: no edge
            foot, top = world(side[1], 0.0), world(side[1], length)
            where = {
                "kind": "line",
                "axis": _vec(u),
                "through": _vec(foot),
                "within": _within(*_box_of(foot, top)),
            }
            queries.add(
                names["side"],
                names["side"],
                where=where,
                count=_count(chain, where, key),
            )
    return frozenset(frozenset(p) for p in pairs)


class Extrusion(BodyPlan):
    key = "extrusion"

    def body_tool(
        self, chain: Chain, ctx: Context, item: Item, copy: Instance, dome_cut: bool
    ) -> str:
        return _extrusion(chain, item, copy)

    def own_edges(self, chain: Chain, queries: Queries, target: Item, copy: Instance, which: str,
                  open_faces: set[str], part: str | None) -> frozenset[frozenset[str]]:  # fmt: skip
        return _extrusion_edges(chain, queries, target, copy, which)


ENTRY = Extrusion()
