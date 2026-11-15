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

import math
from collections.abc import Mapping
from dataclasses import dataclass

from forge_spec.draft import (
    Choice,
    Counterbore,
    Countersink,
    Item,
    PartSpec,
    Profile,
    Through,
)
from forge_spec.geometry import (
    EPS,
    FlatFace,
    Part,
    SideFace,
    disc,
    least_material_under,
    most_material_under,
    rect,
    rounded_rect,
    side_most_material,
    slot_outline,
)
from forge_spec.outline import Shape, turned_extremes
from forge_spec.placement import Instance, Layout
from forge_spec.schema import DIRECTIONS
from forge_spec.values import Value

from .errors import PlanError
from .write import (
    DATUMS,
    PLANE_AXES,
    Box,
    Chain,
    Done,
    Ref,
    Vec,
    add,
    along,
    axis_of,
    box_round,
    dot,
    length,
    neg,
    num,
    role_of,
    scale,
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

#: How far a tube's bore, built alone, runs past each end of the tube (mm).
_BORE_PAST = 1.0
#: How far a cylinder taken from a feature round a side runs past it, each way (mm).
_SIDE_PAST = 1.0
#: How far a cut's tool is carried into the air past its mouth or far side, or a standing
#: feature's sunk into what it stands on (docs/V2-stage4.md 5.2, 5.3), in mm.
CARRY = 0.05
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


# ----------------------------------------------------------------------
# Reading fields
# ----------------------------------------------------------------------
def _mm(item: Item, name: str) -> float:
    value = item.get(name)
    if not isinstance(value, Value):
        raise PlanError(f"its {name} is no size", item=item.id)
    return value.made_in("mm")


def _mm_or(item: Item, name: str, default: float) -> float:
    value = item.get(name)
    return value.made_in("mm") if isinstance(value, Value) else default


def _choice(item: Item, name: str) -> str | None:
    value = item.get(name)
    return value.value if isinstance(value, Choice) else None


def _axes(copy: Instance) -> tuple[str, str]:
    if copy.face_axes is None:
        raise PlanError("it has no axes to lie along", item=copy.item)
    return copy.face_axes


def _id(item: str, copy: int, part: str) -> str:
    return f"{item}.{copy}.{part}"


def _box_faces(chain: Chain, item: str, copy: int, *steps: str) -> None:
    """A box-like tool's six faces, each named by the boxes whose planes it lies in."""
    for d in DIRECTIONS:
        chain.name(item, copy, d, *(Ref(s, role_of(d)) for s in steps))


def _bounds_of_cylinder(
    base: Vec, axis: Vec, radius: float, height: float
) -> tuple[Vec, Vec]:
    top = add(base, axis, height)
    lo, hi = [0.0] * 3, [0.0] * 3
    for k in range(3):
        spread = radius * math.sqrt(max(1.0 - axis[k] * axis[k], 0.0))
        lo[k] = min(base[k], top[k]) - spread
        hi[k] = max(base[k], top[k]) + spread
    return (lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2])


def _span_box(
    centre: Vec, u: Vec, low: float, high: float, halves: Mapping[str, float]
) -> tuple[Vec, Vec]:
    """The box from ``low`` to ``high`` along the frame direction ``u`` from ``centre``, ``halves`` across it."""
    up = axis_of(u)
    lo, hi = list(centre), list(centre)
    for axis, half in halves.items():
        k = "xyz".index(axis)
        lo[k], hi[k] = centre[k] - half, centre[k] + half
    k = "xyz".index(up)
    a, b = centre[k] + u[k] * low, centre[k] + u[k] * high
    lo[k], hi[k] = min(a, b), max(a, b)
    return (lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2])


def _up(u: Vec) -> str:
    """The frame direction a body or a standing feature rises along, by name."""
    axis = axis_of(u)
    return ("+" if u["xyz".index(axis)] > 0 else "-") + axis


# ----------------------------------------------------------------------
# Box-like tools, and a rounding of their vertical edges made early (5.5)
# ----------------------------------------------------------------------
def _box_tool(chain: Chain, item: Item, k: int, lo: Vec, hi: Vec, up: str) -> str:
    """A box-like tool from ``lo`` to ``hi``, its six faces named; its vertical edges rounded first if a rounding is to be made early.

    Early (5.5), the tool is its section along ``up`` with its corners
    rounded (or bevelled) by the rounding's size, pushed from its low end
    to its high end: a ``profile_rectangle`` with a corner radius (to half
    its shorter side, where the arcs meet: a strap whose ends are round) or
    a corner chamfer. Its four sides are the extrusion's ``side`` faces told
    apart by which way they face, its corners the rest of them; the
    rounding is noted as made on the copy, its faces the corners.
    """
    made = [e for e in chain.early.get(item.id, []) if e.which == "vertical"]
    if not made:
        tool = chain.box(_id(item.id, k, "box"), lo, hi, item=item.id)
        _box_faces(chain, item.id, k, tool)
        return tool
    if len(made) > 1:
        raise PlanError(
            "two roundings of its vertical edges are made early", item=item.id
        )
    early = made[0]
    axis = up[1]
    base, datum_sign = DATUMS[axis]
    a1, a2 = PLANE_AXES[base]
    i1, i2, kz = "xyz".index(a1), "xyz".index(a2), "xyz".index(axis)
    plane = chain.datum(_id(item.id, k, "plane"), axis, lo[kz], item=item.id)
    corner = "corner_chamfer" if early.bevel else "corner_radius"
    profile = chain.profile(_id(item.id, k, "outline"), "profile_rectangle", plane, {
        "width": length(hi[i1] - lo[i1]), "height": length(hi[i2] - lo[i2]),
        "center_u": length((lo[i1] + hi[i1]) / 2), "center_v": length((lo[i2] + hi[i2]) / 2),
        corner: length(early.size)}, item=item.id)  # fmt: skip
    mode = "normal" if datum_sign > 0 else "reverse"
    tool = chain.extrude(
        _id(item.id, k, "box"), profile, hi[kz] - lo[kz], mode, item=item.id
    )
    # The extrusion's start is its low end along the datum's normal: at the plane, or at the far end reversed.
    low, high = (
        ("start_face", "end_face") if mode == "normal" else ("end_face", "start_face")
    )
    for d in DIRECTIONS:
        if d[1] == axis:
            chain.name(item.id, k, d, Ref(tool, low if d[0] == "-" else high))
        else:
            chain.name(item.id, k, d, Ref(tool, "side", unit(d)))
    pairs = frozenset(frozenset(p) for p in _vertical(item.kind, up))
    chain.rounded.setdefault((item.id, k), []).append(
        Done(tool, early.bevel, early.size, pairs, (Ref(tool, "side"),), early.rounding))  # fmt: skip
    chain.made_early.add((early.rounding, k))
    return tool


def _vertical(kind: str, up: str) -> list[tuple[str, str]]:
    """A box-like item's vertical edges, by the faces each lies between."""
    sides = [d for d in DIRECTIONS if d[1] != up[1]]
    return [(a, b) for n, a in enumerate(sides) for b in sides[n + 1 :] if a[1] != b[1]]


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
    k, kind = copy.index, item.kind
    o, u = copy.origin, copy.normal
    if kind == "block":
        assert copy.lo is not None and copy.hi is not None
        tool = _box_tool(chain, item, k, copy.lo, copy.hi, _up(u))
        chain.add_box(Box(copy.lo, copy.hi, item.id, k))
        return tool
    if kind == "cylinder":
        return _rod(chain, item, k, o, u, _mm(item, "diameter"), _mm(item, "length"))
    if kind == "tube":
        outer, inner, long = (
            _mm(item, "outer_diameter"),
            _mm(item, "inner_diameter"),
            _mm(item, "length"),
        )
        rod = chain.cylinder(_id(item.id, k, "outer"), o, u, outer, long, item=item.id)
        bore = chain.cylinder(_id(item.id, k, "bore"), add(o, u, -_BORE_PAST), u, inner,
                              long + 2 * _BORE_PAST, item=item.id)  # fmt: skip
        tool = chain.boolean(
            _id(item.id, k, "tube"), "subtract", [rod, bore], item=item.id
        )
        chain.name(item.id, k, "+end", Ref(rod, "top"))
        chain.name(item.id, k, "-end", Ref(rod, "base"))
        chain.name(item.id, k, "side", Ref(rod, "lateral"))
        chain.name(item.id, k, "bore", Ref(bore, "lateral"))
        chain.add_box(Box(*_bounds_of_cylinder(o, u, outer / 2, long), item.id, k))
        return tool
    if kind == "cone":
        base, top, long = (
            _mm(item, "base_diameter"),
            _mm(item, "top_diameter"),
            _mm(item, "length"),
        )
        tool = chain.cone(_id(item.id, k, "cone"), o, u, base, top, long, item=item.id)
        if top > 0.0:
            chain.name(item.id, k, "+end", Ref(tool, "top"))
        chain.name(item.id, k, "-end", Ref(tool, "base"))
        chain.name(item.id, k, "side", Ref(tool, "lateral"))
        chain.add_box(
            Box(*_bounds_of_cylinder(o, u, max(base, top) / 2, long), item.id, k)
        )
        return tool
    if kind == "extrusion":
        return _extrusion(chain, item, copy)
    if kind == "revolution":
        return _revolution(chain, item, copy)
    if kind == "sphere":
        d = _mm(item, "diameter")
        r = d / 2
        if _choice(item, "portion") == "upper_half":
            return _dome(chain, item, k, o, u, r, cut=dome_cut)
        assert copy.lo is not None and copy.hi is not None
        centre = scale(add(copy.lo, copy.hi), 0.5)
        tool = chain.sphere(_id(item.id, k, "ball"), centre, d, item=item.id)
        chain.name(item.id, k, "surface", Ref(tool, "surface"))
        chain.add_box(Box(copy.lo, copy.hi, item.id, k))
        return tool
    raise PlanError(f"a {kind} body isn't compiled", item=item.id)


def outline_points(
    profile: Profile, offset: tuple[float, float] = (0.0, 0.0)
) -> list[list[float]]:
    """The spec's outline as a ``profile_outline``'s points, moved by ``offset``: its start, then each segment's end, an arc's with its middle (4.3).

    The arc's middle is on its circle halfway round from its start, the way
    it turns (the reader has put its centre where both its ends are on its
    circle: extrusion.md).
    """
    ou, ov = offset
    rows = [[num(profile.start[0] + ou), num(profile.start[1] + ov)]]
    here = profile.start
    for seg in profile.segments:
        to = [num(seg.to[0] + ou), num(seg.to[1] + ov)]
        if seg.centre is None:
            rows.append(to)
        else:
            (cx, cy), r = seg.centre, math.dist(here, seg.centre)
            a0 = math.atan2(here[1] - cy, here[0] - cx)
            a1 = math.atan2(seg.to[1] - cy, seg.to[0] - cx)
            sweep = ((a0 - a1) if seg.clockwise else (a1 - a0)) % (2 * math.pi)
            middle = a0 + (-sweep if seg.clockwise else sweep) / 2
            rows.append(
                [
                    *to,
                    num(cx + r * math.cos(middle) + ou),
                    num(cy + r * math.sin(middle) + ov),
                ]
            )
        here = seg.to
    return rows


def _profile(item: Item) -> Profile:
    profile = item.get("profile")
    if not isinstance(profile, Profile):
        raise PlanError("it has no outline", item=item.id)
    return profile


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


def _rod(chain: Chain, item: Item, k: int, o: Vec, u: Vec, diameter: float, height: float, *,
         own: tuple[Vec, Vec] | None = None) -> str:  # fmt: skip
    """A cylinder from ``o`` along ``u``; ``own``, the item's box where the tool reaches past it (sunk, 5.3)."""
    tool = chain.cylinder(_id(item.id, k, "rod"), o, u, diameter, height, item=item.id)
    chain.name(item.id, k, "+end", Ref(tool, "top"))
    chain.name(item.id, k, "-end", Ref(tool, "base"))
    chain.name(item.id, k, "side", Ref(tool, "lateral"))
    chain.add_box(
        Box(*(own or _bounds_of_cylinder(o, u, diameter / 2, height)), item.id, k)
    )
    return tool


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
    ball = chain.sphere(_id(item.id, k, "ball"), o, 2 * r, item=item.id)
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
    chain.name(item.id, k, "surface", Ref(ball, "surface"))
    chain.add_box(Box(lo, hi, item.id, k))
    return tool


# ----------------------------------------------------------------------
# Cuts (4.4)
# ----------------------------------------------------------------------
def _on_face(face: FlatFace, w: Vec) -> tuple[float, float]:
    """A point's place on a flat face, along its two axes from its centre."""
    a1, a2 = face.axes
    return along(w, a1) - along(face.centre, a1), along(w, a2) - along(face.centre, a2)


def _through(item: Item) -> bool:
    return isinstance(item.get("depth"), Through)


def _cut_depth(item: Item, face: FlatFace, parts: tuple[Part, ...], w: Vec) -> float:
    """How deep a cut on a flat face goes: its depth, or through the most material under its mouth."""
    if not _through(item):
        return _mm(item, "depth")
    p1, p2 = _on_face(face, w)
    deep = most_material_under(face, parts, p1, p2)
    if deep <= 0.0:
        raise PlanError(
            "there is no material under its mouth to go through", item=item.id
        )
    return deep


def _start(face: FlatFace | SideFace) -> float:
    """Where a cut starts along its way in: at the face, or at a bore's axis (hole.md)."""
    if isinstance(face, SideFace) and not face.outward:
        return -face.radius
    return 0.0


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
    if item.kind == "hole":
        return _hole(chain, ctx, item, copy, face, mouth, far)
    if not isinstance(face, FlatFace):
        raise PlanError(f"a {item.kind} goes into flat faces only", item=item.id)
    if item.kind == "slot":
        return [_slot(chain, item, copy, face, mouth, far)]
    if item.kind == "pocket":
        return [_pocket(chain, item, copy, face, mouth, far)]
    raise PlanError(f"a {item.kind} cut isn't compiled", item=item.id)


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
    if not isinstance(face, FlatFace):
        return None, None
    w, d = copy.origin, neg(copy.normal)
    a1, a2 = face.axes
    if item.kind == "hole":
        radius, widest = _widest(ctx, item)
        mouth = _span_box(w, d, -CARRY, 0.0, {a1: widest, a2: widest})
        if not _through(item):
            return mouth, None
        depth = _cut_depth(item, face, (disc(radius),), w)
        return mouth, _span_box(w, d, depth, depth + CARRY, {a1: radius, a2: radius})
    halves, parts = _outline_of(item, face)
    mouth = _span_box(w, d, -CARRY, 0.0, {a1: halves[0], a2: halves[1]})
    if not _through(item):
        return mouth, None
    depth = _cut_depth(item, face, parts, w)
    return mouth, _span_box(w, d, depth, depth + CARRY, {a1: halves[0], a2: halves[1]})


def _widest(ctx: Context, item: Item) -> tuple[float, float]:
    """A hole's radius, and its widest radius (its counterbore's or countersink's, if wider)."""
    diameter = ctx.layout.diameters.get(item.id)
    if diameter is None:
        raise PlanError("its diameter wasn't resolved", item=item.id)
    radius = widest = diameter / 2
    counterbore, countersink = item.get("counterbore"), item.get("countersink")
    if isinstance(counterbore, Counterbore):
        widest = max(widest, counterbore.diameter.made_in("mm") / 2)
    if isinstance(countersink, Countersink):
        widest = max(widest, countersink.diameter.made_in("mm") / 2)
    return radius, widest


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
    if not isinstance(face, SideFace) or item.kind != "hole":
        return None, None
    radius, widest = _widest(ctx, item)
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
        return host is not None and host.kind == "tube"
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


def _outline_of(
    item: Item, face: FlatFace
) -> tuple[tuple[float, float], tuple[Part, ...]]:
    """A slot's or pocket's half sizes along the face's axes, and its outline's parts."""
    if item.kind == "slot":
        long, wide = _mm(item, "length"), _mm(item, "width")
        first = _choice(item, "along") == face.axes[0]
        if _choice(item, "ends") == "round":
            parts = slot_outline(long, wide, along_first=first)
        else:
            parts = (
                (rect(long / 2, wide / 2),) if first else (rect(wide / 2, long / 2),)
            )
        return ((long / 2, wide / 2) if first else (wide / 2, long / 2)), parts
    if _choice(item, "shape") == "circle":
        r = _mm(item, "diameter") / 2
        return (r, r), (disc(r),)
    long, wide = _mm(item, "length"), _mm(item, "width")
    return (long / 2, wide / 2), rounded_rect(
        long / 2, wide / 2, _mm_or(item, "corner_radius", 0.0)
    )


def _hole(chain: Chain, ctx: Context, item: Item, copy: Instance, face: FlatFace | SideFace,
          mouth: float, far: float) -> list[str]:  # fmt: skip
    k, w = copy.index, copy.origin
    d = neg(copy.normal)
    diameter = ctx.layout.diameters.get(item.id)
    if diameter is None:
        raise PlanError("its diameter wasn't resolved", item=item.id)
    radius = diameter / 2
    start = _start(face)
    if isinstance(face, SideFace):
        depth = (
            side_most_material(face, radius) if _through(item) else _mm(item, "depth")
        )
    else:
        depth = _cut_depth(item, face, (disc(radius),), w)
    pieces: list[str] = []
    begin = start - mouth
    bore = chain.cylinder(_id(item.id, k, "bore"), add(w, d, begin), d, diameter, depth + far - begin,
                          item=item.id)  # fmt: skip
    pieces.append(bore)
    chain.name(item.id, k, "wall", Ref(bore, "lateral"))
    chain.name(item.id, k, "floor", Ref(bore, "top"))
    lo, hi = _bounds_of_cylinder(add(w, d, start), d, radius, depth - start)
    counterbore, countersink = item.get("counterbore"), item.get("countersink")
    if isinstance(counterbore, Counterbore):
        wide = counterbore.diameter.made_in("mm")
        deep = counterbore.depth.made_in("mm")
        step = chain.cylinder(_id(item.id, k, "counterbore"), add(w, d, begin), d, wide, deep - begin,
                              item=item.id)  # fmt: skip
        pieces.append(step)
        chain.name(item.id, k, "counterbore_wall", Ref(step, "lateral"))
        chain.name(item.id, k, "counterbore_floor", Ref(step, "top"))
        lo, hi = box_round(
            [lo, hi, *_bounds_of_cylinder(add(w, d, start), d, wide / 2, deep - start)]
        )
    if isinstance(countersink, Countersink):
        wide = countersink.diameter.made_in("mm")
        angle = countersink.angle.made_in("deg")
        deep = (wide - diameter) / 2 / math.tan(math.radians(angle) / 2)
        cone = chain.cone(
            _id(item.id, k, "countersink"), w, d, wide, diameter, deep, item=item.id
        )
        pieces.append(cone)
        chain.name(item.id, k, "countersink", Ref(cone, "lateral"))
        lo, hi = box_round([lo, hi, *_bounds_of_cylinder(w, d, wide / 2, deep)])
        if (
            start < 0.0
        ):  # inside a bore: no lip of the wall left in front of it (hole.md)
            front = chain.cylinder(_id(item.id, k, "countersink_front"), add(w, d, start), d, wide,
                                   -start, item=item.id)  # fmt: skip
            pieces.append(front)
        elif mouth:  # carried: the countersink's mouth runs on into the air as wide
            air = chain.cylinder(_id(item.id, k, "countersink_air"), add(w, d, -mouth), d, wide, mouth,
                                 item=item.id)  # fmt: skip
            pieces.append(air)
    chain.cut_box(Box(lo, hi, item.id, k))
    return pieces


def _extrude_into(chain: Chain, item: Item, k: int, face: FlatFace, w: Vec, depth: float,
                  op: str, params: Mapping[str, object], mouth: float = 0.0,
                  far: float = 0.0) -> tuple[str, str, str]:  # fmt: skip
    """A profile on the face's plane through ``w``, pushed into the material by ``depth``: (extrusion, mouth role, floor role).

    Carried (5.2), the profile is ``mouth`` out from the face and pushed
    ``mouth + depth + far``: its floor stays ``depth`` in.
    """
    normal = unit(face.normal)
    axis = axis_of(normal)
    plane = chain.datum(
        _id(item.id, k, "plane"), axis, along(add(w, normal, mouth), axis), item=item.id
    )
    a1, a2 = face.axes
    profile = chain.profile(_id(item.id, k, "outline"), op, plane, {
        **params, "center_u": length(along(w, a1)), "center_v": length(along(w, a2))}, item=item.id)  # fmt: skip
    _, datum_sign = DATUMS[axis]
    inward = -normal["xyz".index(axis)]  # the way in, along the axis
    mode = "normal" if inward == datum_sign else "reverse"
    tool = chain.extrude(
        _id(item.id, k, "cut"), profile, mouth + depth + far, mode, item=item.id
    )
    # The extrusion's start is its low end along the datum's normal: the plane, or the far end reversed.
    opening, floor = (
        ("start_face", "end_face") if mode == "normal" else ("end_face", "start_face")
    )
    return tool, opening, floor


def _footprint_box(
    face: FlatFace, w: Vec, halves: tuple[float, float], depth: float
) -> tuple[Vec, Vec]:
    a1, a2 = face.axes
    return _span_box(
        w, neg(unit(face.normal)), 0.0, depth, {a1: halves[0], a2: halves[1]}
    )


def _slot(
    chain: Chain, item: Item, copy: Instance, face: FlatFace, mouth: float, far: float
) -> str:
    k, w = copy.index, copy.origin
    long, wide = _mm(item, "length"), _mm(item, "width")
    first = _choice(item, "along") == face.axes[0]
    round_ends = _choice(item, "ends") == "round"
    _, parts = _outline_of(item, face)
    depth = _cut_depth(item, face, parts, w)
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


# ----------------------------------------------------------------------
# Standing features (4.5), and bodies standing on faces
# ----------------------------------------------------------------------
def _section(item: Item, axes: tuple[str, str]) -> tuple[dict[str, float], float]:
    """A box-like standing item's half sizes across its direction, by frame axis, and its height."""
    a1, a2 = axes
    kind = item.kind
    if kind in ("post", "block"):
        return {a1: _mm(item, "length") / 2, a2: _mm(item, "width") / 2}, _mm(
            item, "height"
        )
    if kind == "rib":
        run = _choice(item, "along") or a1
        other = a2 if run == a1 else a1
        return {run: _mm(item, "length") / 2, other: _mm(item, "thickness") / 2}, _mm(
            item, "height"
        )
    if kind == "tab":
        thin = _choice(item, "thickness_along") or a2
        wide = a1 if thin == a2 else a2
        return {thin: _mm(item, "thickness") / 2, wide: _mm(item, "width") / 2}, _mm(
            item, "length"
        )
    raise PlanError(f"a {kind} has no box section", item=item.id)


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
    k, w, u = copy.index, copy.origin, copy.normal
    behind = CARRY if sink and sink_box(chain, ctx, item, copy) is not None else 0.0
    if item.kind == "boss":
        d, h = _mm(item, "diameter"), _mm(item, "height")
        # Its box is the boss's own: the sunk part is within the part already.
        return _rod(
            chain,
            item,
            k,
            add(w, u, -behind),
            u,
            d,
            h + behind,
            own=_bounds_of_cylinder(w, u, d / 2, h),
        )
    halves, height = _section(item, _axes(copy))
    if item.kind == "tab" and _choice(item, "end") == "round":
        return _round_tab(chain, item, copy, halves, height, 0.0)
    lo, hi = _span_box(w, u, -behind, height, halves)
    tool = _box_tool(chain, item, k, lo, hi, _up(u))
    chain.add_box(Box(*_span_box(w, u, 0.0, height, halves), item.id, k))
    return tool


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
    if not isinstance(face, FlatFace) or copy.host is None:
        return None
    if item.kind == "tab" and _choice(item, "end") == "round":
        return None
    w, u = copy.origin, copy.normal
    p1, p2 = _on_face(face, w)
    if item.kind == "boss":
        r = _mm(item, "diameter") / 2
        parts: tuple[Part, ...] = (disc(r),)
        halves = dict.fromkeys(face.axes, r)
    else:
        halves, _ = _section(item, _axes(copy))
        parts = (rect(halves[face.axes[0]], halves[face.axes[1]]),)
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


def _round_side(chain: Chain, item: Item, copy: Instance, face: SideFace) -> str:
    """A standing feature round a side: its section out to its height, on the open side of the side's surface (4.5)."""
    k, w, u = copy.index, copy.origin, copy.normal
    radius, side_axis = face.radius, face.axis
    run = unit("+" + side_axis)
    # Outside: from the plane through the side's axis. Inside: from behind the plane that touches
    # the side at its point (every point of the bore is in front of it, so where behind it the
    # prism starts changes nothing, and its face never touches the bore's surface).
    reach = radius if face.outward else _SIDE_PAST
    if item.kind == "boss":
        d, h = _mm(item, "diameter"), _mm(item, "height")
        prism = chain.cylinder(
            _id(item.id, k, "rod"), add(w, u, -reach), u, d, reach + h, item=item.id
        )
        chain.name(item.id, k, "+end", Ref(prism, "top"))
        chain.name(item.id, k, "side", Ref(prism, "lateral"))
        lo, hi = _bounds_of_cylinder(add(w, u, -reach), u, d / 2, reach + h)
    else:
        halves, h = _section(item, _axes(copy))
        if item.kind == "tab" and _choice(item, "end") == "round":
            prism = _round_tab(chain, item, copy, halves, h, reach, record=False)
        else:
            lo_p, hi_p = _span_box(w, u, -reach, h, halves)
            prism = chain.box(_id(item.id, k, "box"), lo_p, hi_p, item=item.id)
            _box_faces(chain, item.id, k, prism)
        lo, hi = _span_box(w, u, -reach, h, halves)
    side = chain.cylinder(_id(item.id, k, "side"), add(face.start, run, -_SIDE_PAST), run, 2 * radius,
                          face.length + 2 * _SIDE_PAST, item=item.id)  # fmt: skip
    op = "subtract" if face.outward else "intersect"
    tool = chain.boolean(_id(item.id, k, "on_side"), op, [prism, side], item=item.id)
    chain.add_box(Box(lo, hi, item.id, k))
    return tool
