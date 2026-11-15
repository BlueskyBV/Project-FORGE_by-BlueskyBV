"""What the planner writes for a revolution: its entry in the ``plan`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
revolution's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item
from forge_spec.outline import Shape, turned_extremes, turned_rims
from forge_spec.placement import Instance

from forge_plan.errors import PlanError
from forge_plan.items.plan._edges import Queries, _count, _profile, circle_where
from forge_plan.items.plan._families import BodyPlan
from forge_plan.items.plan._tools import _id, outline_points
from forge_plan.write import Box, Chain, Ref, add

if TYPE_CHECKING:
    from forge_spec.placement import Instance

    from forge_plan.items.plan._edges import Queries
    from forge_plan.tools import Context
    from forge_plan.write import Chain

Vec = tuple[float, float, float]


def _revolution(chain: Chain, item: Item, copy: Instance) -> str:
    """A revolution (4.3): its half outline turned a full turn about the line along its axis through its point.

    The revolve reads the outline's first coordinate as the distance from
    the axis and its second as the height along it from the axis's point,
    whichever plane it is drawn on (stage 3, 7.2). Its flat ends are the
    revolve's ``top`` and ``base``, where the placement has them.
    """
    k, o, u = copy.index, copy.origin, copy.normal
    plane = chain.datum(_id(item.id, k, "plane"), "z", 0.0, item=item.id)
    outline = chain.profile(_id(item.id, k, "outline"), "profile_outline", plane,
                            {"points": {"points": outline_points(_profile(item)), "unit": "mm"}}, item=item.id)  # fmt: skip
    axis = chain.axis(_id(item.id, k, "axis"), o, u, item=item.id)
    tool = chain.revolve(_id(item.id, k, "body"), outline, axis, item=item.id)
    shape = Shape.of_profile(_profile(item))
    for name, role, top in (("+end", "top", True), ("-end", "base", False)):
        if (
            turned_extremes(shape, top) is not None
        ):  # revolution.md: a flat end across the axis there
            chain.name(item.id, k, name, Ref(tool, role))
    chain.name(item.id, k, "side", Ref(tool, "side"))
    assert copy.lo is not None and copy.hi is not None
    chain.add_box(Box(copy.lo, copy.hi, item.id, k))
    return tool


def _turned_rims(chain: Chain, queries: Queries, target: Item, copy: Instance,
                 which: str) -> frozenset[frozenset[str]]:  # fmt: skip
    """A revolution's rims (revolution.md): round each flat end, a circle where it meets the side next to it at an angle, off the axis."""
    ends = {"top": ["+end"], "bottom": ["-end"]}.get(which)
    if ends is None:
        raise PlanError(f"a revolution has no {which!r} edges", item=target.id)
    key = (target.id, copy.index)
    names = chain.names_of(target.id, copy.index)
    o, u = copy.origin, copy.normal
    shape = Shape.of_profile(_profile(target))
    for end in ends:
        found, rims = (
            turned_extremes(shape, end == "+end"),
            turned_rims(shape, end == "+end"),
        )
        if found is None or rims is None or end not in names:
            raise PlanError(f"it has no flat {end}: no edges there", item=target.id)
        if not rims:
            raise PlanError(
                f"its side runs on smoothly into its {end}: no edges there",
                item=target.id,
            )
        for radius in rims:  # a rim the side runs on smoothly into is no edge
            where = circle_where(add(o, u, found[0]), u, radius)
            queries.add(
                names[end], names["side"], where=where, count=_count(chain, where, key)
            )
    return frozenset(frozenset((end, "side")) for end in ends)


class Revolution(BodyPlan):
    key = "revolution"

    def body_tool(
        self, chain: Chain, ctx: Context, item: Item, copy: Instance, dome_cut: bool
    ) -> str:
        return _revolution(chain, item, copy)

    def own_edges(self, chain: Chain, queries: Queries, target: Item, copy: Instance, which: str,
                  open_faces: set[str], part: str | None) -> frozenset[frozenset[str]]:  # fmt: skip
        return _turned_rims(chain, queries, target, copy, which)


ENTRY = Revolution()
