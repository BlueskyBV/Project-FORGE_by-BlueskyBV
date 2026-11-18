"""What the planner writes for a sphere: its entry in the ``plan`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
sphere's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from forge_spec.draft import Choice, Item
from forge_spec.placement import Instance
from forge_spec.values import Value

from forge_plan.errors import PlanError
from forge_plan.items.plan._edges import Queries, _choice, _count, _mm, circle_where
from forge_plan.items.plan._families import BodyPlan
from forge_plan.items.plan._shells import _check_walls, _inner, _open, _round, _span
from forge_plan.items.plan._tools import _id, _span_box
from forge_plan.write import (
    Box,
    Chain,
    Hollow,
    Ref,
    Vec,
    add,
    axis_of,
    dot,
    role_of,
    scale,
    unit,
)

if TYPE_CHECKING:
    from forge_spec.placement import Instance

    from forge_plan.items.plan._edges import Queries
    from forge_plan.tools import Context
    from forge_plan.write import Chain


def _dome(
    chain: Chain, item: Item, k: int, o: Vec, u: Vec, r: float, *, cut: bool = False
) -> str:
    """A dome: the ball about its flat face's centre, within the box beyond that face (4.3).

    ``cut`` (5.4): the ball less the box on the other side of the flat face,
    which holds all of the ball outside the first box; the two boxes meet
    only on the flat face's plane, so the ball within the one is the ball
    less the other.
    """
    up = axis_of(u)
    across = {a: r for a in "xyz" if a != up}
    lo, hi = _span_box(o, u, 0.0, r, across)
    # The boxes that take its half are twice the ball across and deep: one only as big as the ball touches it
    # at its rim's four points and its pole, and OpenCascade may leave a sliver there (generated part 492: an
    # edge 1.9e-6 mm long at the rim, its two vertices one within the other's tolerance).
    wide = dict.fromkeys(across, 2 * r)
    made = chain.sphere(_id(item.id, k, "ball"), o, 2 * r, item=item.id)
    ball = chain.seamed(made, (item.id, k), item=item.id)
    if cut:
        behind = _span_box(o, u, -2 * r, 0.0, wide)
        half = chain.box(_id(item.id, k, "behind"), *behind, item=item.id)
        tool = chain.boolean(
            _id(item.id, k, "dome"), "subtract", [ball, half], item=item.id
        )
        facing = (
            "+" if dot(u, unit("+" + up)) > 0 else "-"
        ) + up  # the behind box's face on the flat plane
        chain.name(item.id, k, "-end", Ref(half, role_of(facing)))
    else:
        half = chain.box(
            _id(item.id, k, "half"), *_span_box(o, u, 0.0, 2 * r, wide), item=item.id
        )
        tool = chain.boolean(
            _id(item.id, k, "dome"), "intersect", [ball, half], item=item.id
        )
        flat = ("-" if dot(u, unit("+" + up)) > 0 else "+") + up
        chain.name(item.id, k, "-end", Ref(half, role_of(flat)))
    chain.name(item.id, k, "surface", Ref(made, "surface"))
    chain.add_box(Box(lo, hi, item.id, k))
    return tool


def _dome_edges(chain: Chain, queries: Queries, target: Item, copy: Instance, which: str,
          open_faces: set[str], part: str | None) -> frozenset[frozenset[str]]:  # fmt: skip
    if which != "bottom" or _choice(target, "portion") != "upper_half":
        raise PlanError(
            "only a dome's rim (bottom) can be rounded on a ball", item=target.id
        )
    key = (target.id, copy.index)
    names = chain.names_of(target.id, copy.index)
    if part == "after" or (part is None and "-end" in open_faces):
        hollow = chain.hollows.get(key)
        inner = names.get("inner surface")
        if hollow is None or inner is None:
            raise PlanError(
                "its flat face is open, and the hollow has no name", item=target.id
            )
        where = circle_where(copy.origin, copy.normal, hollow.radius)
        queries.add(names["-end"], inner, where=where, count=_count(chain, where, key))
    if part != "after":
        where = circle_where(copy.origin, copy.normal, _mm(target, "diameter") / 2)
        queries.add(
            names["-end"],
            names["surface"],
            where=where,
            count=_count(chain, where, key),
        )
    return frozenset({frozenset({"-end", "surface"})})


def _sphere(chain: Chain, shell: Item, body: Item, copy: Instance) -> str:
    key = (body.id, copy.index)
    t = _mm(shell, "thickness")
    r = _mm(body, "diameter") / 2
    inner = r - t
    o, u = copy.origin, copy.normal
    ball = f"{shell.id}.{copy.index}.ball"
    portion = body.get("portion")
    if not (isinstance(portion, Choice) and portion.value == "upper_half"):
        centre = add(o, u, r) if copy.host is None else o
        tool = chain.seamed(chain.sphere(ball, centre, 2 * inner, item=shell.id), key, item=shell.id)
        chain.name(body.id, copy.index, "inner surface", Ref(ball, "surface"))
        lo = (centre[0] - inner, centre[1] - inner, centre[2] - inner)
        hi = (centre[0] + inner, centre[1] + inner, centre[2] + inner)
        chain.hollows[key] = Hollow(lo, hi, inner)
        chain.cut_box(Box(lo, hi, shell.id, copy.index))
        return tool
    # A dome's floor is its flat face's own wall (shell.md): ``floor`` thick, or ``thickness`` when none is given;
    # none where the flat face is left open. (No face across from it is ever open.)
    given = shell.get("floor")
    floor = (
        0.0
        if "-end" in _open(shell)
        else given.made_in("mm")
        if isinstance(given, Value)
        else t
    )
    walls = {"-end": floor, "surface": t}
    up = axis_of(u)
    flat = ("-" if u["xyz".index(up)] > 0 else "+") + up
    turned = chain.seamed(chain.sphere(ball, o, 2 * inner, item=shell.id), key, item=shell.id)
    lo, hi = _span(o, u, floor, r, {a: r for a in "xyz" if a != up})
    above = f"{shell.id}.{copy.index}.above"
    chain.box(above, lo, hi, item=shell.id)
    tool = chain.boolean(
        f"{shell.id}.{copy.index}.hollow", "intersect", [turned, above], item=shell.id
    )
    chain.name(body.id, copy.index, "inner surface", Ref(ball, "surface"))
    if floor > 0.0:
        chain.name(body.id, copy.index, "inner -end", Ref(above, role_of(flat)))
    for n, earlier in enumerate(chain.rounded.get(key, [])):
        pair = frozenset({"-end", "surface"})
        if pair not in earlier.pairs or not _check_walls(shell, pair, walls):
            continue
        size = _inner(earlier, t)
        if size <= 1e-9:
            continue
        queries = Queries()
        rim = math.sqrt(max(inner * inner - floor * floor, 0.0))
        queries.add((Ref(above, role_of(flat)),), (Ref(ball, "surface"),),
                    where=circle_where(add(o, u, floor), u, rim), count=(1, 1))  # fmt: skip
        tool = _round(chain, shell, copy, tool, earlier, size, queries, n)
    hlo, hhi = _span(o, u, floor, inner, {a: inner for a in "xyz" if a != up})
    chain.hollows[key] = Hollow(hlo, hhi, inner)
    chain.cut_box(Box(hlo, hhi, shell.id, copy.index))
    return tool


class Sphere(BodyPlan):
    key = "sphere"

    def body_tool(
        self, chain: Chain, ctx: Context, item: Item, copy: Instance, dome_cut: bool
    ) -> str:
        from forge_plan.seams import ball_motion

        k, o, u = copy.index, copy.origin, copy.normal
        d = _mm(item, "diameter")
        r = d / 2
        if _choice(item, "portion") == "upper_half":
            turn = ball_motion(ctx, item.id, k, o, r, u)
            if turn is not None:
                chain.seams[(item.id, k)] = turn
            return _dome(chain, item, k, o, u, r, cut=dome_cut)
        assert copy.lo is not None and copy.hi is not None
        centre = scale(add(copy.lo, copy.hi), 0.5)
        turn = ball_motion(ctx, item.id, k, centre, r, u if copy.host is not None else None)
        if turn is not None:
            chain.seams[(item.id, k)] = turn
        made = chain.sphere(_id(item.id, k, "ball"), centre, d, item=item.id)
        tool = chain.seamed(made, (item.id, k), item=item.id)
        chain.name(item.id, k, "surface", Ref(made, "surface"))
        chain.add_box(Box(copy.lo, copy.hi, item.id, k))
        return tool

    def other_construction(
        self, ctx: Context, item: Item
    ) -> tuple[str, str, Any] | None:
        """A dome made as the ball less the box behind its flat face (5.4)."""
        if _choice(item, "portion") == "upper_half":
            return ("dome_cut", "5.4", None)
        return None

    def hollow_tool(
        self,
        chain: Chain,
        shell: Item,
        body: Item,
        copy: Instance,
        cavity: tuple[Vec, Vec] | None,
    ) -> str:
        return _sphere(chain, shell, body, copy)

    def own_edges(self, chain: Chain, queries: Queries, target: Item, copy: Instance, which: str,
                  open_faces: set[str], part: str | None) -> frozenset[frozenset[str]]:  # fmt: skip
        return _dome_edges(chain, queries, target, copy, which, open_faces, part)


ENTRY = Sphere()
