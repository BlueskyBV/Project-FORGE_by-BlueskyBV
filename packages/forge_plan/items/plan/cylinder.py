"""What the planner writes for a cylinder: its entry in the ``plan`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
cylinder's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item
from forge_spec.geometry import FlatFace
from forge_spec.placement import Instance

from forge_plan.items.plan._edges import Queries, _mm, _rims, circle_where
from forge_plan.items.plan._families import BodyPlan
from forge_plan.items.plan._shells import _check_walls, _inner, _round, _span, _walls
from forge_plan.items.plan._tools import _rod, leaning_standing
from forge_plan.write import Box, Chain, Hollow, Ref, add, axis_of, ordered

if TYPE_CHECKING:
    from forge_spec.placement import Instance

    from forge_plan.items.plan._edges import Queries
    from forge_plan.tools import Context
    from forge_plan.write import Chain

Vec = tuple[float, float, float]


def _cylinder(chain: Chain, shell: Item, body: Item, copy: Instance) -> str:
    key = (body.id, copy.index)
    t = _mm(shell, "thickness")
    o, u = copy.origin, copy.normal
    walls = _walls(shell, {"+end": "-end", "-end": "+end"})
    walls["side"] = t
    radius = _mm(body, "diameter") / 2 - t
    start = add(o, u, walls["-end"])
    height = _mm(body, "length") - walls["-end"] - walls["+end"]
    step = f"{shell.id}.{copy.index}.hollow"
    tool = chain.cylinder(step, start, u, 2 * radius, height, item=shell.id)
    ends = {"+end": (Ref(step, "top"),), "-end": (Ref(step, "base"),)}
    for n, earlier in enumerate(chain.rounded.get(key, [])):
        size = _inner(earlier, t)
        queries = Queries()
        for pair in map(frozenset, ordered(earlier.pairs)):
            if "side" not in pair or not _check_walls(shell, pair, walls):
                continue
            end = next(f for f in pair if f != "side")
            at = add(start, u, height) if end == "+end" else start
            where = circle_where(at, u, radius)
            queries.add(ends[end], (Ref(step, "lateral"),), where=where, count=(1, 1))
        if size > 1e-9 and queries.found:
            tool = _round(chain, shell, copy, tool, earlier, size, queries, n)
    chain.name(body.id, copy.index, "inner side", Ref(step, "lateral"))
    for end, refs in ends.items():
        if walls[end] > 0.0:
            chain.name(body.id, copy.index, f"inner {end}", *refs)
    across = {a: radius for a in "xyz" if a != axis_of(u)}
    lo, hi = _span(start, u, 0.0, height, across)
    chain.hollows[key] = Hollow(lo, hi, radius)
    chain.cut_box(Box(lo, hi, shell.id, copy.index))
    return tool


class Cylinder(BodyPlan):
    key = "cylinder"

    threadable = True

    def body_tool(
        self, chain: Chain, ctx: Context, item: Item, copy: Instance, dome_cut: bool
    ) -> str:
        k, o, u = copy.index, copy.origin, copy.normal
        if copy.direction is not None and copy.host is not None:  # leaning on its face (step 3): as a boss leans
            face = ctx.face(copy)
            assert isinstance(face, FlatFace)
            return leaning_standing(chain, item, copy, face, None, _mm(item, "diameter") / 2, _mm(item, "length"))
        return _rod(chain, item, k, o, u, _mm(item, "diameter"), _mm(item, "length"))

    def hollow_tool(
        self,
        chain: Chain,
        shell: Item,
        body: Item,
        copy: Instance,
        cavity: tuple[Vec, Vec] | None,
    ) -> str:
        return _cylinder(chain, shell, body, copy)

    def own_edges(self, chain: Chain, queries: Queries, target: Item, copy: Instance, which: str,
                  open_faces: set[str], part: str | None) -> frozenset[frozenset[str]]:  # fmt: skip
        return _rims(chain, queries, target, copy, which, open_faces, part)


ENTRY = Cylinder()
