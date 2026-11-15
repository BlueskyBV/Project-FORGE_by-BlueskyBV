"""What the planner writes for a tab: its entry in the ``plan`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
tab's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from forge_spec.draft import Choice, Item
from forge_spec.placement import Instance
from forge_spec.schema import DIRECTIONS

from forge_plan.errors import GapError, PlanError
from forge_plan.items.plan._edges import Queries, _choice, _count, _mm, circle_where
from forge_plan.items.plan._families import StandingPlan
from forge_plan.items.plan._tools import _SIDE_PAST, _axes, _id, _span_box
from forge_plan.write import (
    DATUMS,
    PLANE_AXES,
    Box,
    Chain,
    Ref,
    add,
    along,
    axis_of,
    dot,
    length,
    role_of,
    unit,
)

if TYPE_CHECKING:
    from forge_spec.placement import Instance

    from forge_plan.items.plan._edges import Queries
    from forge_plan.write import Chain

Vec = tuple[float, float, float]


def _round_tab(chain: Chain, item: Item, copy: Instance, halves: Mapping[str, float], height: float,
               below: float, *, record: bool = True) -> str:  # fmt: skip
    """A round-ended tab: a stadium pushed across its thickness, kept beyond the plane its foot is in (4.5).

    Seen along its thickness, a round-ended tab is a rectangle whose far end
    is a half-circle of its width (tab.md). The stadium runs from well behind
    the foot to the tab's far end, its far end that half-circle; the box it
    is kept within reaches past the stadium everywhere but at the plane
    ``below`` behind the foot (0 on a flat face; round a side, the side's
    axis), so no face of the box lies on or touches one of the stadium's.
    """
    k, w, u = copy.index, copy.origin, copy.normal
    thin = _choice(item, "thickness_along")
    if thin is None:
        raise PlanError("a tab says which way its thickness runs", item=item.id)
    wide = next(a for a in halves if a != thin)
    r, t = halves[wide], halves[thin]
    behind = (
        below + r + _SIDE_PAST
    )  # the stadium's near end, behind where the tab is kept from
    run = height + behind
    middle = add(w, u, (height - behind) / 2)
    plane = chain.datum(_id(item.id, k, "plane"), thin, along(w, thin), item=item.id)
    base, datum_sign = DATUMS[thin]
    first, second = PLANE_AXES[base]
    up = axis_of(u)
    outline = chain.profile(_id(item.id, k, "outline"), "profile_slot", plane, {
        "length": length(run), "width": length(2 * r),
        "rotation": {"magnitude": 0.0 if up == first else 90.0, "unit": "deg"},
        "center_u": length(along(middle, first)), "center_v": length(along(middle, second))},
        item=item.id)  # fmt: skip
    stadium = chain.extrude(
        _id(item.id, k, "stadium"), outline, 2 * t, "symmetric", item=item.id
    )
    roomy = {wide: r + _SIDE_PAST, thin: t + _SIDE_PAST}
    lo_k, hi_k = _span_box(w, u, -below, height + _SIDE_PAST, roomy)
    keep = chain.box(_id(item.id, k, "keep"), lo_k, hi_k, item=item.id)
    tool = chain.boolean(
        _id(item.id, k, "tab"), "intersect", [stadium, keep], item=item.id
    )
    # The stadium's start face is its low end along the datum's normal, which faces against it.
    low = ("-" if datum_sign > 0 else "+") + thin
    for d in DIRECTIONS:
        if d[1] == thin:
            chain.name(
                item.id, k, d, Ref(stadium, "start_face" if d == low else "end_face")
            )
        elif d[1] == wide:
            chain.name(item.id, k, d, Ref(stadium, "side"))
        else:  # along its length: its foot is the box's face behind it; its far end the round side
            foot = d != ("+" if dot(u, unit("+" + up)) > 0 else "-") + up
            chain.name(
                item.id, k, d, Ref(keep, role_of(d)) if foot else Ref(stadium, "side")
            )
    chain.name(item.id, k, "end", Ref(stadium, "side"))
    if record:  # round a side, the feature's box is its caller's
        lo, hi = _span_box(w, u, -below, height, halves)
        chain.add_box(Box(lo, hi, item.id, k))
    return tool


def _round_tab_edges(chain: Chain, queries: Queries, target: Item, copy: Instance,
               which: str) -> frozenset[frozenset[str]]:  # fmt: skip
    """A round-ended tab's ``top``: the two half-circles where its rounding meets its broad faces.

    Its ``vertical`` edges run on smoothly into those half-circles (tab.md):
    a rounding can't stop there, so they are not compiled (a gap).
    """
    if which != "top":
        raise GapError("a round-ended tab's vertical edges run on smoothly into its rounding: "
                        "no construction rounds them and stops there", item=target.id)  # fmt: skip
    key = (target.id, copy.index)
    names = chain.names_of(target.id, copy.index)
    thin = _choice(target, "thickness_along")
    assert thin is not None
    width, thickness, long = (
        _mm(target, "width"),
        _mm(target, "thickness"),
        _mm(target, "length"),
    )
    r = width / 2
    centre = add(copy.origin, copy.normal, long - r)
    for sign in ("+", "-"):
        face = sign + thin
        at = add(centre, unit(face), thickness / 2)
        where = circle_where(at, unit("+" + thin), r)
        queries.add(
            names[face], names["end"], where=where, count=_count(chain, where, key)
        )
    return frozenset({frozenset({"+" + thin, "end"}), frozenset({"-" + thin, "end"})})


class Tab(StandingPlan):
    key = "tab"

    def box_like(self, item: Item) -> bool:
        end = item.get("end")
        return not (isinstance(end, Choice) and end.value == "round")

    def section(
        self, item: Item, axes: tuple[str, str]
    ) -> tuple[dict[str, float], float]:
        a1, a2 = axes
        thin = _choice(item, "thickness_along") or a2
        wide = a1 if thin == a2 else a2
        return {thin: _mm(item, "thickness") / 2, wide: _mm(item, "width") / 2}, _mm(
            item, "length"
        )

    def standing_tool(
        self, chain: Chain, item: Item, copy: Instance, behind: float
    ) -> str:
        if _choice(item, "end") == "round":
            halves, height = self.section(item, _axes(copy))
            return _round_tab(chain, item, copy, halves, height, 0.0)
        return super().standing_tool(chain, item, copy, behind)

    def sinkable(self, item: Item) -> bool:
        return _choice(item, "end") != "round"

    def round_side_prism(
        self, chain: Chain, item: Item, copy: Instance, reach: float
    ) -> tuple[str, Vec, Vec]:
        if _choice(item, "end") != "round":
            return super().round_side_prism(chain, item, copy, reach)
        w, u = copy.origin, copy.normal
        halves, h = self.section(item, _axes(copy))
        prism = _round_tab(chain, item, copy, halves, h, reach, record=False)
        lo, hi = _span_box(w, u, -reach, h, halves)
        return prism, lo, hi

    def own_edges(self, chain: Chain, queries: Queries, target: Item, copy: Instance, which: str,
                  open_faces: set[str], part: str | None) -> frozenset[frozenset[str]]:  # fmt: skip
        return _round_tab_edges(chain, queries, target, copy, which)


ENTRY = Tab()
