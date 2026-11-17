"""What the planner writes for a block: its entry in the ``plan`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
block's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item
from forge_spec.geometry import FlatFace
from forge_spec.outline import Shape
from forge_spec.placement import Instance
from forge_spec.schema import DIRECTIONS

from forge_plan.errors import PlanError
from forge_plan.items.plan._edges import Queries, _mm, box_queries, opposite
from forge_plan.items.plan._families import BodyPlan
from forge_plan.items.plan._shells import _check_walls, _inner, _round, _walls
from forge_plan.items.plan._tools import (
    _box_tool,
    _up,
    leaning_standing,
    turn_of,
    turned_on,
    turned_prism,
)
from forge_plan.write import Box, Chain, Done, Hollow, Ref, Vec, ordered, role_of

if TYPE_CHECKING:
    from forge_spec.placement import Instance

    from forge_plan.items.plan._edges import Queries
    from forge_plan.tools import Context
    from forge_plan.write import Chain


def _block(
    chain: Chain,
    shell: Item,
    body: Item,
    copy: Instance,
    cavity: tuple[Vec, Vec] | None,
) -> str:
    if cavity is None:
        raise PlanError("the layout has no hollow for it", item=shell.id)
    key = (body.id, copy.index)
    t = _mm(shell, "thickness")
    walls = _walls(shell, {d: opposite(d) for d in DIRECTIONS})
    lo, hi = cavity
    box = f"{shell.id}.{copy.index}.hollow"
    tool = chain.box(box, lo, hi, item=shell.id)
    names: dict[str, tuple[Ref, ...]] = {d: (Ref(box, role_of(d)),) for d in DIRECTIONS}
    made: list[Done] = []
    for n, earlier in enumerate(chain.rounded.get(key, [])):
        size = _inner(earlier, t)
        pairs = [
            pair
            for pair in ordered(earlier.pairs)
            if _check_walls(shell, frozenset(pair), walls)
        ]
        if size <= 1e-9 or not pairs:
            continue
        queries = Queries()
        box_queries(
            queries, lo, hi, [(a, b) for a, b in pairs], names, made, lambda _w: (1, 1)
        )
        tool = _round(chain, shell, copy, tool, earlier, size, queries, n)
        made.append(
            Done(tool, earlier.bevel, size, frozenset(frozenset(p) for p in pairs))
        )
    for d in DIRECTIONS:
        if walls[d] > 0.0:
            chain.name(body.id, copy.index, f"inner {d}", *names[d])
    chain.hollows[key] = Hollow(lo, hi, rounded=tuple(made))
    chain.cut_box(Box(lo, hi, shell.id, copy.index))
    return tool


class Block(BodyPlan):
    key = "block"

    bottom_edges = True

    def body_tool(
        self, chain: Chain, ctx: Context, item: Item, copy: Instance, dome_cut: bool
    ) -> str:
        k = copy.index
        face = ctx.face(copy) if copy.host is not None else None
        if copy.direction is not None and isinstance(face, FlatFace):  # leaning on its face (step 3): as a post leans
            halves, height = self.section(item, face.axes)
            cross = Shape.rect((0.0, 0.0), (halves[face.axes[0]], halves[face.axes[1]])).turned(*(turn_of(item) or (1.0, 0.0)))
            return leaning_standing(chain, item, copy, face, cross, 0.0, height)
        turned = turned_on(ctx.layout, item, face) if face is not None else None
        if turned is not None:  # standing turned in its face's plane (1b's first move): its turned outline, pushed up
            assert isinstance(face, FlatFace)
            return turned_prism(chain, item, copy, face.axes, turned, _mm(item, "height"), 0.0)
        assert copy.lo is not None and copy.hi is not None
        tool = _box_tool(chain, item, k, copy.lo, copy.hi, _up(copy.normal))
        chain.add_box(Box(copy.lo, copy.hi, item.id, k))
        return tool

    def box_like(self, item: Item) -> bool:
        return True

    def section(
        self, item: Item, axes: tuple[str, str]
    ) -> tuple[dict[str, float], float]:
        a1, a2 = axes
        return {a1: _mm(item, "length") / 2, a2: _mm(item, "width") / 2}, _mm(
            item, "height"
        )

    def hollow_tool(
        self,
        chain: Chain,
        shell: Item,
        body: Item,
        copy: Instance,
        cavity: tuple[Vec, Vec] | None,
    ) -> str:
        return _block(chain, shell, body, copy, cavity)


ENTRY = Block()
