"""Each kind's tool, from the definitions (docs/V2-stage4.md, sections 4.3 to 4.5).

A tool is one copy of one item as a solid of its own: built from primitives
at the copy's place in the frame, exactly the item's points as its
definition gives them. Bodies and standing features are then joined to the
part; cuts are taken from it (:mod:`forge_plan.planner`). Every number is
the layout's (:class:`forge_spec.placement.Layout`, the solver's) or the
spec's: where a copy is, which way it faces, the material under its face.

Each function writes one copy's steps into the chain, names its faces
there (by the schema's names, worked out from each face's plane: 4.6), puts
its box in the chain's added or cut boxes, and returns the step that is
its tool.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from forge_spec.draft import (
    Counterbore,
    Item,
    PartSpec,
)
from forge_spec.geometry import (
    EPS,
    FlatFace,
    Footprint,
    SideFace,
    least_material_under,
    side_most_material,
)
from forge_spec.outline import Shape
from forge_spec.placement import Instance, Layout

from .errors import PlanError
from .items.plan import PLAN
from .items.plan._tools import (
    _SIDE_PAST,
    CARRY,
    _bounds_of_cylinder,
    _cut_depth,
    _id,
    _mm,
    _on_face,
    _span_box,
    _through,
    _up,
    _vertical,
    leaning_cut,
    leaning_standing,
    turn_of,
    turned_cut,
    turned_halves,
    turned_on,
)
from .write import (
    Box,
    Chain,
    Vec,
    add,
    neg,
    unit,
)

__all__ = [
    "CARRY",
    "Context",
    "air_boxes",
    "body_tool",
    "carried_ways",
    "clear_of",
    "cut_tool",
    "early_applies",
    "sink_box",
    "standing_tool",
]

#: How far an edge's own box is shrunk at its ends, and grown across, to find what covers it (5.5).
_TOUCH = 1e-9


@dataclass(frozen=True)
class Context:
    """What every tool reads: the spec's items and the solver's layout."""

    spec: PartSpec
    layout: Layout

    @property
    def items(self) -> Mapping[str, Item]:
        return {item.id: item for item in self.spec.items}

    def face(self, copy: Instance) -> FlatFace | SideFace:
        """The face a copy stands on or is cut into."""
        if copy.host is None:
            raise PlanError("the first body is on no face", item=copy.item)
        host, index, name = copy.host
        found = self.layout.faces.get((host, index), {}).get(name)
        if found is None:
            raise PlanError(
                f"its face {host}#{index} {name} isn't in the layout", item=copy.item
            )
        return found

    # What the families of kinds make their tools with (items/plan/_families.py).
    def carried(self, chain: Chain, item: Item, copy: Instance) -> tuple[bool, bool]:
        return carried_ways(chain, self, item, copy)

    def sink(self, chain: Chain, item: Item, copy: Instance) -> tuple[Vec, Vec] | None:
        return sink_box(chain, self, item, copy)

    def cut_tool(
        self, chain: Chain, item: Item, copy: Instance, carry: tuple[bool, bool]
    ) -> list[str]:
        return cut_tool(chain, self, item, copy, carry=carry)

    def standing_tool(
        self, chain: Chain, item: Item, copy: Instance, sink: bool
    ) -> str:
        return standing_tool(chain, self, item, copy, sink=sink)


def early_applies(
    chain: Chain, item: Item, copies: list[Instance], size: float, rounding: str
) -> bool:
    """Whether rounding a box-like item's vertical edges early, on its own tool, makes what the definition makes (5.5).

    Made late the rounding takes ``K``, the corner region between its round
    and each edge; early, it takes ``K`` from the tool alone. The two are
    the same when no other tool added so far meets ``K``'s box (a body
    stacked flush on the item meets it only on a plane: the rounding stops
    there either way) and none covers the edge itself (a post standing flush
    over it: there is no edge to round there, and early would round it).
    Its own earlier roundings must leave its vertical edges as they were.
    """
    for copy in copies:
        key = (item.id, copy.index)
        own = next((b for b in chain.added if (b.item, b.copy) == key), None)
        if own is None:
            return False
        earlier = [
            done for done in chain.rounded.get(key, []) if done.rounding != rounding
        ]
        vertical = [frozenset(p) for p in _vertical(item.kind, _up(copy.normal))]
        if any(p in done.pairs for done in earlier for p in vertical):
            return False
        others = [b for b in chain.added if (b.item, b.copy) != key]
        for f1, f2 in _vertical(item.kind, _up(copy.normal)):
            region, edge = _corner_region(own, f1, f2, size)
            if any(region.meets(b) or edge.meets(b, by=_TOUCH) for b in others):
                return False
    return True


def _corner_region(own: Box, f1: str, f2: str, size: float) -> tuple[Box, Box]:
    """The box of the region a rounding of the edge between faces ``f1`` and ``f2`` of a box takes, and the edge's own box shrunk at its ends."""
    lo, hi = list(own.lo), list(own.hi)
    elo, ehi = list(own.lo), list(own.hi)
    for f in (f1, f2):
        i = "xyz".index(f[1])
        if f[0] == "+":
            lo[i] = own.hi[i] - size
            elo[i] = ehi[i] = own.hi[i]
        else:
            hi[i] = own.lo[i] + size
            elo[i] = ehi[i] = own.lo[i]
    k = 3 - "xyz".index(f1[1]) - "xyz".index(f2[1])
    elo[k] += 2 * _TOUCH
    ehi[k] -= 2 * _TOUCH
    return (Box((lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2]), own.item, own.copy),
            Box((elo[0], elo[1], elo[2]), (ehi[0], ehi[1], ehi[2]), own.item, own.copy))  # fmt: skip


def clear_of(
    chain: Chain, box: tuple[Vec, Vec], *, but: tuple[str, int] | None = None
) -> bool:
    """Whether a box meets no tool added so far (its interior meets none of theirs): all of the part made so far is within those.

    ``but``: an item copy whose own boxes are left out, an exact test standing for them (5.2, a round side's host).
    """
    probe = Box(box[0], box[1], "", -1)
    return not any(probe.meets(b) for b in chain.added if (b.item, b.copy) != but)


# ----------------------------------------------------------------------
# Bodies (4.3)
# ----------------------------------------------------------------------
def body_tool(
    chain: Chain, ctx: Context, item: Item, copy: Instance, *, dome_cut: bool = False
) -> str:
    """One copy of a body: block, cylinder, tube, cone or sphere. ``dome_cut``: a dome as the ball less the box behind its flat face (5.4)."""
    return PLAN[item.kind].body_tool(chain, ctx, item, copy, dome_cut)


def cut_tool(chain: Chain, ctx: Context, item: Item, copy: Instance, *,
             carry: tuple[bool, bool] = (False, False)) -> list[str]:  # fmt: skip
    """One copy of a cut: a hole (with its counterbore or countersink), a slot or a pocket. Its tool's pieces.

    ``carry`` (5.2): the tool carried :data:`CARRY` into the air past its
    mouth, and past its far side (a cut through), where :func:`air_boxes`
    and :func:`clear_of` prove that air. The cut's box is its own either way.
    """
    face = ctx.face(copy)
    mouth, far = (CARRY if c else 0.0 for c in carry)
    if mouth and isinstance(face, SideFace) and not face.outward:
        raise PlanError(
            "a hole into a bore or a hollow starts at its axis: its mouth isn't carried",
            item=item.id,
        )
    if copy.direction is not None:  # leaning on its face (1b's second move)
        assert isinstance(face, FlatFace)
        bore = item.get("counterbore")
        recess = (bore.diameter.made_in("mm") / 2, bore.depth.made_in("mm")) if isinstance(bore, Counterbore) else None
        return [leaning_cut(chain, item, copy, face, ctx.layout.diameters[item.id] / 2, recess)]
    turned = turned_on(ctx.layout, item, face)
    if turned is not None:
        assert isinstance(face, FlatFace)
        return [turned_cut(chain, item, copy, face, turned, mouth, far, PLAN[item.kind].floor_name)]
    return PLAN[item.kind].cut_tool(chain, ctx, item, copy, face, mouth, far)


def air_boxes(
    ctx: Context, item: Item, copy: Instance
) -> tuple[tuple[Vec, Vec] | None, tuple[Vec, Vec] | None]:
    """The regions a cut's tool is carried through past its mouth and past its far side (5.2): None where it isn't offered.

    ``E`` is the cut's widest outline, :data:`CARRY` beyond its face (and,
    for a cut through, beyond its far end). ``P - (T + E) = P - T`` when
    ``E`` meets none of ``P``, which :func:`clear_of` shows from the boxes of the tools
    added so far. On a flat face only: a round side's are :func:`side_air_boxes`.
    """
    face = ctx.face(copy)
    if not isinstance(face, FlatFace) or copy.direction is not None:  # a leaning tool is kept by its face's plane
        return None, None
    w, d = copy.origin, neg(copy.normal)
    a1, a2 = face.axes
    turned = turned_on(ctx.layout, item, face)
    if turned is not None:  # the box round its turned outline, past its mouth and its far side alike
        at_mouth = at_far = turned_halves(turned)
        depth_of: Footprint = turned
    else:
        at_mouth, at_far, depth_of = PLAN[item.kind].air_outline(ctx, item, face)
    mouth = _span_box(w, d, -CARRY, 0.0, {a1: at_mouth[0], a2: at_mouth[1]})
    if not _through(item):
        return mouth, None
    depth = _cut_depth(item, face, depth_of, w)
    return mouth, _span_box(w, d, depth, depth + CARRY, {a1: at_far[0], a2: at_far[1]})


def side_air_boxes(
    ctx: Context, item: Item, copy: Instance
) -> tuple[tuple[Vec, Vec] | None, tuple[Vec, Vec] | None]:
    """The boxes of ``E`` past a hole's mouth and past its far side on a round side (5.2): None where it isn't offered.

    Returned only where the side's own radius proves ``E`` clear of its host
    (meeting it only where the tool already does): past a mouth from
    outside, and past a far side that is the plane touching a rod's, a
    boss's or a wall's outside, every point of ``E`` is beyond a plane
    touching the side; past the far side of a tube's or a hollowed
    cylinder's wall from outside, within the bore's radius when the far
    end's centre is more than :data:`CARRY` from the axis, and, in a
    hollow, within its span along the axis. The other added tools' boxes are
    tested against these by :func:`clear_of`, the host's left out.
    """
    face = ctx.face(copy)
    if not isinstance(face, SideFace) or not PLAN[item.kind].goes_round_side:
        return None, None
    radius, widest = PLAN[item.kind].widest(ctx, item)
    w, d = copy.origin, neg(copy.normal)
    mouth = None
    if face.outward:  # into a bore or a hollow a hole starts at the axis, in air
        mouth = _bounds_of_cylinder(add(w, d, -CARRY), d, widest, CARRY)
    if not _through(item):
        return mouth, None
    depth = side_most_material(face, radius)
    into = face.outward and face.wall < 2 * face.radius - EPS  # a bore or a hollow
    if into:
        inner = face.radius - face.wall
        if inner * inner - radius * radius <= CARRY * CARRY:  # h <= c: past the axis
            return mouth, None
        if not _inside_holds(ctx, copy, face, radius):
            return mouth, None
    return mouth, _bounds_of_cylinder(add(w, d, depth), d, radius, CARRY)


def _inside_holds(ctx: Context, copy: Instance, face: SideFace, radius: float) -> bool:
    """Whether the air inside a round side runs along its axis over all of a hole's span, ``radius`` each way of its point (5.2).

    A tube's bore runs its whole length, and past its ends there is no tube;
    a hollowed cylinder's hollow is its cavity, which must hold the span
    strictly inside. Any other inside isn't told.
    """
    assert copy.host is not None
    key = (copy.host[0], copy.host[1])
    cavity = ctx.layout.cavities.get(key)
    if cavity is None:
        host = ctx.items.get(copy.host[0])
        return host is not None and PLAN[host.kind].bored
    k = "xyz".index(face.axis)
    at = copy.origin[k]
    return cavity[0][k] + EPS < at - radius and at + radius < cavity[1][k] - EPS


def carried_ways(
    chain: Chain, ctx: Context, item: Item, copy: Instance
) -> tuple[bool, bool]:
    """Whether a cut's tool may be carried into the air past its mouth, and past its far side (5.2), on the part made so far."""
    face = ctx.face(copy)
    if isinstance(face, FlatFace):
        mouth, far = air_boxes(ctx, item, copy)
        host = None
    else:
        mouth, far = side_air_boxes(ctx, item, copy)
        assert copy.host is not None
        host = (copy.host[0], copy.host[1])
    return (
        mouth is not None and clear_of(chain, mouth, but=host),
        far is not None and clear_of(chain, far, but=host),
    )


# ----------------------------------------------------------------------
# Standing features (4.5), and bodies standing on faces
# ----------------------------------------------------------------------
def _section(item: Item, axes: tuple[str, str]) -> tuple[dict[str, float], float]:
    """A box-like standing item's half sizes across its direction, by frame axis, and its height."""
    return PLAN[item.kind].section(item, axes)


def standing_tool(
    chain: Chain, ctx: Context, item: Item, copy: Instance, *, sink: bool = False
) -> str:
    """One copy of a standing feature (boss, post, rib, tab), on a flat face or round a side.

    ``sink`` (5.3): carried :data:`CARRY` into what it stands on behind its
    foot, where :func:`sink_box` proves that region is all material.
    """
    face = ctx.face(copy)
    if isinstance(face, SideFace):
        return _round_side(chain, item, copy, face)
    if copy.direction is not None:  # leaning on its face (1b's second move)
        sizes = PLAN[item.kind].section(item, face.axes) if PLAN[item.kind].box_like(item) else None
        if sizes is None:
            return leaning_standing(chain, item, copy, face, None, _mm(item, "diameter") / 2, _mm(item, "height"))
        halves, height = sizes
        by = turn_of(item) or (1.0, 0.0)
        cross = Shape.rect((0.0, 0.0), (halves[face.axes[0]], halves[face.axes[1]])).turned(*by)
        return leaning_standing(chain, item, copy, face, cross, 0.0, height)
    behind = CARRY if sink and sink_box(chain, ctx, item, copy) is not None else 0.0
    turned = turned_on(ctx.layout, item, face)
    if turned is not None:  # turned in its face's plane (1b's first move)
        _, height = PLAN[item.kind].section(item, face.axes)
        return PLAN[item.kind].turned_tool(chain, item, copy, face.axes, turned, height, behind)
    return PLAN[item.kind].standing_tool(chain, item, copy, behind)


def sink_box(
    chain: Chain, ctx: Context, item: Item, copy: Instance
) -> tuple[Vec, Vec] | None:
    """The region a standing feature's tool is sunk into behind its foot (5.3), where it is all material; else None.

    ``E`` is the feature's footprint, :data:`CARRY` deep behind its face.
    ``P + (T + E) = P + T`` when ``E`` is all within ``P``: here when ``E`` lies within its
    host's own box, and clear of its sides by the carry (a foot flush with
    the face's edge, or a boss's tangent to it, would sink a face of the
    tool onto or tangent to the host's side, which no boolean joins
    soundly), the least material under the footprint is more than the carry
    (the face's own depth model, its hollow's wall included), and no cut
    made so far has a box meeting ``E``. A foot round a side, or a
    round-ended tab, is not offered.
    """
    face = ctx.face(copy)
    if not isinstance(face, FlatFace) or copy.host is None or copy.direction is not None:
        return None
    if not PLAN[item.kind].sinkable(item):
        return None
    w, u = copy.origin, copy.normal
    p1, p2 = _on_face(face, w)
    turned = turned_on(ctx.layout, item, face)
    parts: Footprint
    if turned is not None:  # its turned foot, and the box round it
        h1, h2 = turned_halves(turned)
        parts, halves = turned, {face.axes[0]: h1, face.axes[1]: h2}
    else:
        parts, halves = PLAN[item.kind].sink_footprint(item, face, copy)
    if least_material_under(face, parts, p1, p2) <= CARRY:
        return None
    region = _span_box(w, u, -CARRY, 0.0, halves)
    host = next(
        (b for b in chain.added if (b.item, b.copy) == (copy.host[0], copy.host[1])),
        None,
    )
    up = max(range(3), key=lambda i: abs(u[i]))
    if host is None or not all(
        host.lo[i] + margin <= region[0][i] and region[1][i] <= host.hi[i] - margin
        for i, margin in ((i, 0.0 if i == up else CARRY) for i in range(3))
    ):
        return None
    probe = Box(region[0], region[1], "", -1)
    if any(probe.meets(b) for b in chain.cut):
        return None
    return region


def _round_side(chain: Chain, item: Item, copy: Instance, face: SideFace) -> str:
    """A standing feature round a side: its section out to its height, on the open side of the side's surface (4.5)."""
    k = copy.index
    radius, side_axis = face.radius, face.axis
    run = unit("+" + side_axis)
    # Outside: from the plane through the side's axis. Inside: from behind the plane that touches
    # the side at its point (every point of the bore is in front of it, so where behind it the
    # prism starts changes nothing, and its face never touches the bore's surface).
    reach = radius if face.outward else _SIDE_PAST
    prism, lo, hi = PLAN[item.kind].round_side_prism(chain, item, copy, reach)
    side = chain.cylinder(_id(item.id, k, "side"), add(face.start, run, -_SIDE_PAST), run, 2 * radius,
                          face.length + 2 * _SIDE_PAST, item=item.id)  # fmt: skip
    op = "subtract" if face.outward else "intersect"
    tool = chain.boolean(_id(item.id, k, "on_side"), op, [prism, side], item=item.id)
    chain.add_box(Box(lo, hi, item.id, k))
    return tool
