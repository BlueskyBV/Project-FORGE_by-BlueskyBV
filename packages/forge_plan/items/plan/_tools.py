"""Helpers the ``plan`` role's kinds and program share (a leaf: it imports neither the kinds' modules nor the program), moved at stage 4b.0b's step 3."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from forge_numeric import scalar as fs
from forge_spec.draft import Choice, Item, Place, Profile
from forge_spec.ends import ThroughAll, end_of
from forge_spec.geometry import (
    Face,
    FlatFace,
    Footprint,
    SideFace,
)
from forge_spec.items.solve._common import _turn, degrees
from forge_spec.outline import Line, Shape
from forge_spec.placement import Instance, Layout, turned_outline
from forge_spec.schema import DIRECTIONS
from forge_spec.values import Value

from forge_plan.errors import PlanError
from forge_plan.write import (
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
    direction,
    length,
    neg,
    num,
    point,
    role_of,
    unit,
)

#: How far a tube's bore, built alone, runs past each end of the tube (mm).
_BORE_PAST = 1.0


#: How far a cylinder taken from a feature round a side runs past it, each way (mm).
_SIDE_PAST = 1.0


#: How far a cut's tool is carried into the air past its mouth or far side, or a standing
#: feature's sunk into what it stands on (docs/V2-stage4.md 5.2, 5.3), in mm.
CARRY = 0.05


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
            (cx, cy), r = seg.centre, fs.dist(here, seg.centre)
            a0 = fs.atan2(here[1] - cy, here[0] - cx)
            a1 = fs.atan2(seg.to[1] - cy, seg.to[0] - cx)
            sweep = ((a0 - a1) if seg.clockwise else (a1 - a0)) % (2 * math.pi)
            middle = a0 + (-sweep if seg.clockwise else sweep) / 2
            rows.append(
                [
                    *to,
                    num(cx + r * fs.cos(middle) + ou),
                    num(cy + r * fs.sin(middle) + ov),
                ]
            )
        here = seg.to
    return rows


def _profile(item: Item) -> Profile:
    profile = item.get("profile")
    if not isinstance(profile, Profile):
        raise PlanError("it has no outline", item=item.id)
    return profile


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


# ----------------------------------------------------------------------
# Cuts (4.4)
# ----------------------------------------------------------------------
def _on_face(face: FlatFace, w: Vec) -> tuple[float, float]:
    """A point's place on a flat face, along its two axes from its centre."""
    a1, a2 = face.axes
    return along(w, a1) - along(face.centre, a1), along(w, a2) - along(face.centre, a2)


def _through(item: Item) -> bool:
    return isinstance(end_of(item), ThroughAll)


def _cut_depth(item: Item, face: FlatFace, parts: Footprint, copy: Instance) -> float:
    """How deep a cut on a flat face goes: its depth; through everything or up to a face, as the solver worked it out
    for the copy (item 2b's first step); or through the most material under its mouth."""
    if copy.depth is not None:
        return copy.depth
    if not _through(item):
        return _mm(item, "depth")
    w = copy.origin
    p1, p2 = _on_face(face, w)
    deep = face.most_material_under(parts, (p1, p2))
    if deep <= 0.0:
        raise PlanError(
            "there is no material under its mouth to go through", item=item.id
        )
    return deep


def _start(face: Face) -> float:
    """Where a cut starts along its way in: at the face, or at a bore's axis (hole.md)."""
    if isinstance(face, SideFace) and not face.outward:
        return -face.radius
    return 0.0


def _extrude_into(chain: Chain, item: Item, k: int, face: FlatFace, w: Vec, depth: float,
                  op: str, params: Mapping[str, object], mouth: float = 0.0,
                  far: float = 0.0) -> tuple[str, str, str]:  # fmt: skip
    """A profile on the face's plane through ``w``, pushed into the material by ``depth``: (extrusion, mouth role, floor role).

    Carried (5.2), the profile is ``mouth`` out from the face and pushed
    ``mouth + depth + far``: its floor stays ``depth`` in.
    """
    return _extrude_along(chain, item, k, face.normal, face.axes, w, depth, op, params, mouth, far)


def _extrude_along(chain: Chain, item: Item, k: int, normal_: str, axes: tuple[str, str], w: Vec, depth: float,
                   op: str, params: Mapping[str, object], mouth: float = 0.0,
                   far: float = 0.0) -> tuple[str, str, str]:  # fmt: skip
    """As :func:`_extrude_into`, on the plane through ``w`` square to ``normal_`` (a frame axis's way, named), its ``axes``
    the face's that faces it would have (a keyway made upright: slot.md, "Round a side")."""
    normal = unit(normal_)
    axis = axis_of(normal)
    plane = chain.datum(
        _id(item.id, k, "plane"), axis, along(add(w, normal, mouth), axis), item=item.id
    )
    a1, a2 = axes
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


# ----------------------------------------------------------------------
# Turned in the face's plane (V2-stage4b-0c.md, 3.3, 1b's first move)
# ----------------------------------------------------------------------
def turned_on(layout: Layout, item: Item, face: Face) -> Shape | None:
    """A copy's outline on its flat face turned by its ``place.turn``, about its point, in the face's axes; None if it
    isn't turned. The solver's own outline (:func:`forge_spec.placement.turned_outline`), so what is built is what was
    placed."""
    if not isinstance(face, FlatFace):
        return None
    return turned_outline(item, layout, face.axes)


def turn_of(item: Item) -> tuple[float, float] | None:
    """The cosine and sine of an item's ``place.turn`` (exact on the quarter turns, as the solver takes them); None if
    it isn't turned."""
    place = item.get("place")
    if not isinstance(place, Place) or place.turn is None:
        return None
    return _turn(degrees(place.turn))


def turned_halves(shape: Shape) -> tuple[float, float]:
    """The half sizes of the box round a turned outline, along the face's axes, about its point."""
    (l1, l2), (h1, h2) = shape.box()
    return max(-l1, h1), max(-l2, h2)


def shape_points(shape: Shape, offset: tuple[float, float] = (0.0, 0.0)) -> list[list[float]]:
    """An outline as a ``profile_outline``'s points, moved by ``offset``: its first piece's start, then each piece's end,
    an arc's with its middle, the last written as the start so the outline closes exactly."""
    ou, ov = offset

    def at(p: tuple[float, float]) -> list[float]:
        return [num(p[0] + ou), num(p[1] + ov)]

    first = at(shape.pieces[0].ends()[0])
    rows = [first]
    for n, q in enumerate(shape.pieces):
        end = first if n == len(shape.pieces) - 1 else at(q.ends()[1])
        rows.append(end if isinstance(q, Line) else [*end, *at(q.at(0.5))])
    return rows


def plane_outline(chain: Chain, item: Item, k: int, axes: tuple[str, str], w: Vec, level: Vec, shape: Shape,
                  name: str = "") -> tuple[str, str, float]:  # fmt: skip
    """A turned outline drawn about ``w`` on the standard plane through ``level`` square to the face's normal axis: (the
    outline's step, the axis, the plane's normal sign along it). ``name`` starts its steps' names."""
    normal_axis = next(a for a in "xyz" if a not in axes)
    base, datum_sign = DATUMS[normal_axis]
    if tuple(axes) != PLANE_AXES[base]:
        raise PlanError(f"its outline lies along {axes}, not the plane's {PLANE_AXES[base]}", item=item.id)
    plane = chain.datum(_id(item.id, k, name + "plane"), normal_axis, along(level, normal_axis), item=item.id)
    points = shape_points(shape, (along(w, axes[0]), along(w, axes[1])))
    outline = chain.profile(_id(item.id, k, name + "outline"), "profile_outline", plane,
                            {"points": {"points": points, "unit": "mm"}}, item=item.id)  # fmt: skip
    return outline, normal_axis, datum_sign


def turned_cut(chain: Chain, item: Item, copy: Instance, face: FlatFace, shape: Shape, mouth: float,
               far: float, floor_name: str = "floor") -> str:  # fmt: skip
    """One copy of a slot or a rectangular pocket turned in its face's plane: its turned outline (straight sides and
    true arcs) on the face's plane through its point, pushed into the material by its depth (4.4), carried ``mouth``
    out from the face and ``far`` past a cut through's far side (5.2). Its wall and its floor (a pocket's bottom) are
    named; its box is the box round its turned outline, the cut's depth deep."""
    if chain.early.get(item.id):
        raise PlanError("a rounding of a turned item's edges is made early", item=item.id)
    k, w = copy.index, copy.origin
    normal = unit(face.normal)
    depth = _cut_depth(item, face, shape, copy)
    outline, axis, datum_sign = plane_outline(chain, item, k, face.axes, w, add(w, normal, mouth), shape)
    inward = -normal["xyz".index(axis)]
    mode = "normal" if inward == datum_sign else "reverse"
    tool = chain.extrude(_id(item.id, k, "cut"), outline, mouth + depth + far, mode, item=item.id)
    floor = "end_face" if mode == "normal" else "start_face"
    chain.name(item.id, k, "wall", Ref(tool, "side"))
    chain.name(item.id, k, floor_name, Ref(tool, floor))
    a1, a2 = face.axes
    h1, h2 = turned_halves(shape)
    chain.cut_box(Box(*_span_box(w, neg(normal), 0.0, depth, {a1: h1, a2: h2}), item.id, k))
    return tool


def turned_prism(chain: Chain, item: Item, copy: Instance, axes: tuple[str, str], shape: Shape, height: float,
                 behind: float) -> str:  # fmt: skip
    """One copy of a rib or a block standing turned in its face's plane: its turned outline on the plane of its foot,
    pushed ``height`` out along its face's normal (4.3, 4.5), sunk ``behind`` into what it stands on (5.3). Its far and
    near ends are named by the way it rises; its box is the box round its turned outline, its height tall."""
    if chain.early.get(item.id):
        raise PlanError("a rounding of a turned item's edges is made early", item=item.id)
    k, w, u = copy.index, copy.origin, copy.normal
    outline, axis, datum_sign = plane_outline(chain, item, k, axes, w, add(w, u, -behind), shape)
    mode = "normal" if u["xyz".index(axis)] == datum_sign else "reverse"
    tool = chain.extrude(_id(item.id, k, "body"), outline, behind + height, mode, item=item.id)
    near, far_end = ("start_face", "end_face") if mode == "normal" else ("end_face", "start_face")
    up = ("+" if u["xyz".index(axis)] > 0 else "-") + axis
    chain.name(item.id, k, up, Ref(tool, far_end))
    chain.name(item.id, k, ("-" if up[0] == "+" else "+") + axis, Ref(tool, near))
    h1, h2 = turned_halves(shape)
    chain.add_box(Box(*_span_box(w, u, 0.0, height, {axes[0]: h1, axes[1]: h2}), item.id, k))
    _turned_sides(chain, item, copy, axes, height, tool)
    return tool


def _turned_sides(chain: Chain, item: Item, copy: Instance, axes: tuple[str, str], height: float, tool: str) -> None:
    """A turned box's sides, each named by the way it faces as it is turned (an extrusion's ``side`` faces), and the box
    round it as it stands unturned with the turn that moves it onto the part: what its edges are found on (edges.md,
    "A turned item's edges")."""
    from forge_spec.frames import Rigid

    from forge_plan.items.plan import PLAN

    turn = turn_of(item)
    if turn is None:
        return
    c, s = turn
    e1, e2 = unit("+" + axes[0]), unit("+" + axes[1])
    ways = {axes[0]: tuple(c * e1[i] + s * e2[i] + 0.0 for i in range(3)),
            axes[1]: tuple(c * e2[i] - s * e1[i] + 0.0 for i in range(3))}  # fmt: skip
    for axis, way in ways.items():
        chain.name(item.id, copy.index, "+" + axis, Ref(tool, "side", way))  # type: ignore[arg-type]
        chain.name(item.id, copy.index, "-" + axis, Ref(tool, "side", tuple(-x + 0.0 for x in way)))  # type: ignore[arg-type]
    halves, _ = PLAN[item.kind].section(item, axes)
    lo, hi = _span_box(copy.origin, copy.normal, 0.0, height, halves)
    square = (e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0])
    chain.motions[(item.id, copy.index)] = (lo, hi, Rigid.turn_about(copy.origin, square, c, s))


# ----------------------------------------------------------------------
# Leaning from square to the face (V2-stage4b-0c.md, 3.3, 1b's second move)
# ----------------------------------------------------------------------
def _leaning(copy: Instance, face: FlatFace) -> tuple[Vec, Vec, Vec, float, float]:
    """A leaning copy's direction ``u``, its face's outward normal ``n``, its lean's way ``w`` in the face, and the
    cosine and sine of its tilt."""
    assert copy.direction is not None
    u, n = copy.direction, unit(face.normal)
    c = sum(u[k] * n[k] for k in range(3))
    s = math.sqrt(max(1.0 - c * c, 0.0))
    w = (
        (u[0] - c * n[0]) / s,
        (u[1] - c * n[1]) / s,
        (u[2] - c * n[2]) / s,
    )
    return u, n, w, c, s


def _leaning_names(chain: Chain, item: Item, copy: Instance, face: FlatFace, upright: str, far_end: str,
                   lean: tuple[float, float], hinge: Vec, height: float, back: float) -> None:  # fmt: skip
    """A leaning box's far face and sides, each named as the extrusion has it, its sides by the way each faces leaning;
    and the box round it as it stands upright and unturned, with the motion that turns and leans it: what its far end's
    edges are found on (edges.md, "A leaning item's edges")."""
    from forge_plan.items.plan import PLAN

    k = copy.index
    n = unit(face.normal)
    a1, a2 = face.axes
    e1, e2 = unit("+" + a1), unit("+" + a2)
    halves, _ = PLAN[item.kind].section(item, face.axes)
    motion = _leaning_motion(chain, item, copy, face, lean, hinge, height, halves, back)
    up = ("+" if n["xyz".index(axis_of(n))] > 0 else "-") + axis_of(n)
    chain.name(item.id, k, up, Ref(upright, far_end))
    for axis, way in ((a1, e1), (a2, e2)):
        for sign in (1.0, -1.0):
            normal = motion.vector(tuple(sign * x + 0.0 for x in way))
            chain.name(item.id, k, ("+" if sign > 0 else "-") + axis, Ref(upright, "side", normal))


def _leaning_motion(chain: Chain, item: Item, copy: Instance, face: FlatFace, lean: tuple[float, float], hinge: Vec,
                    height: float, halves: Mapping[str, float], back: float) -> Any:  # fmt: skip
    """The motion that turns a leaning copy in its face (its own turn) and leans it, about the line through its point
    in the face square to its lean; kept with the box round it upright and unturned (Chain.motions), from ``back``
    behind its point, where its tool starts, so that an edge along its lean is held to all of the line it lies on
    out of the face (where it meets the face's plane differs from one edge to the next)."""
    from forge_spec.frames import Rigid

    w, n = copy.origin, unit(face.normal)
    e1, e2 = unit("+" + face.axes[0]), unit("+" + face.axes[1])
    c, s = turn_of(item) or (1.0, 0.0)
    square = (e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0])
    motion = Rigid.turn_about(w, hinge, *lean).after(Rigid.turn_about(w, square, c, s))
    lo, hi = _span_box(w, n, -back, height, halves)
    chain.motions[(item.id, copy.index)] = (lo, hi, motion)
    return motion


def _keep(chain: Chain, item: Item, k: int, face: FlatFace, w: Vec, n: Vec, low: float, high: float, half: float,
          ) -> str:  # fmt: skip
    """A box square to the face round a leaning copy's point, from ``low`` to ``high`` along its outward normal and
    ``half`` each way along its axes: what of a leaning tool lies on the right side of the face is kept by it."""
    a1, a2 = face.axes
    return chain.box(_id(item.id, k, "keep"), *_span_box(w, n, low, high, {a1: half, a2: half}), item=item.id)


def leaning_cut(chain: Chain, item: Item, copy: Instance, face: FlatFace, radius: float,
                bore: tuple[float, float] | None) -> str:  # fmt: skip
    """One copy of a hole leaning on its face (hole.md, place.md): its cylinder, and its counterbore's (``bore``: its
    radius and depth along the axis), from far enough out that all of each is past the face's plane, along its axis
    into the material; kept within the face's material, a box from the face's plane in: to the far face (right
    through; its cylinder runs on past it, so it comes out all across its mouth there) or past its floor. The face
    has the same material under all of it, ``T`` (the solver holds that): through, it goes ``(T + r sin) / cos``.
    Its faces take nothing yet, so none is named; its box is the keeping box's."""
    if chain.early.get(item.id):
        raise PlanError("a rounding of a leaning item's edges is made early", item=item.id)
    k, w = copy.index, copy.origin
    u, n, _, c, s = _leaning(copy, face)
    thick = face.depth_below
    widest = max(radius, bore[0] if bore is not None else 0.0)
    back = widest * s / c + 1.0
    through = _through(item)
    depth = (thick + radius * s) / c + 1.0 if through else _mm(item, "depth")
    start = add(w, u, back)
    tools = [chain.cylinder(_id(item.id, k, "rod"), start, neg(u), 2 * radius, back + depth, item=item.id)]
    if bore is not None:
        tools.append(chain.cylinder(_id(item.id, k, "bore"), start, neg(u), 2 * bore[0], back + bore[1], item=item.id))
    tool = tools[0] if len(tools) == 1 else chain.boolean(_id(item.id, k, "cylinders"), "union", tools, item=item.id)
    deepest = thick if through else depth * c + widest * s + 1.0
    half = (back + depth) * s + widest / c + 1.0
    keep = _keep(chain, item, k, face, w, neg(n), 0.0, deepest, half)
    cut = chain.boolean(_id(item.id, k, "cut"), "intersect", [tool, keep], item=item.id)
    a1, a2 = face.axes
    chain.cut_box(Box(*_span_box(w, neg(n), 0.0, deepest, {a1: half, a2: half}), item.id, k))
    return cut


def leaning_standing(chain: Chain, item: Item, copy: Instance, face: FlatFace, shape: Shape | None, radius: float,
                     height: float) -> str:  # fmt: skip
    """One copy of a boss or a post leaning on its face: its solid from far enough back that all of its cross-section is
    past the face's plane to ``height`` along its direction, kept on the face's open side by a box from its plane
    out (its foot then lies in the face's plane, joined to it as an unleaning foot is). A boss is its cylinder; a post,
    its cross-section (``shape``, turned with it) pushed out square to the face and turned about the line through its
    point in the face square to its lean, by its tilt (a ``transform``, ForgeIR v2's rigid motion). Its faces take
    nothing yet; its far end and its sides are named, and the box round it upright and its lean kept, for its far
    end's edges (edges.md, "A leaning item's edges"); its box is the solver's."""
    if chain.early.get(item.id):
        raise PlanError("a rounding of a leaning item's edges is made early", item=item.id)
    k, w = copy.index, copy.origin
    u, n, way, c, s = _leaning(copy, face)
    reach = radius
    if shape is not None:
        (l1, l2), (h1, h2) = shape.box()
        reach = fs.hypot(max(-l1, h1), max(-l2, h2))
    back = reach * s / c + 1.0
    if shape is None:
        solid = chain.cylinder(_id(item.id, k, "rod"), add(w, u, -back), u, 2 * radius, back + height, item=item.id)
        chain.name(item.id, k, "+end", Ref(solid, "top"))
        chain.name(item.id, k, "side", Ref(solid, "lateral"))
        hinge = (n[1] * way[2] - n[2] * way[1], n[2] * way[0] - n[0] * way[2], n[0] * way[1] - n[1] * way[0])
        _leaning_motion(chain, item, copy, face, (c, s), hinge, height, {face.axes[0]: radius, face.axes[1]: radius},
                        back)  # fmt: skip
    else:
        outline, axis, datum_sign = plane_outline(chain, item, k, face.axes, w, add(w, n, -back), shape)
        mode = "normal" if n["xyz".index(axis)] == datum_sign else "reverse"
        upright = chain.extrude(_id(item.id, k, "upright"), outline, back + height, mode, item=item.id)
        hinge = (n[1] * way[2] - n[2] * way[1], n[2] * way[0] - n[0] * way[2], n[0] * way[1] - n[1] * way[0])
        tilt = math.degrees(fs.atan2(s, c))
        solid = chain.step(_id(item.id, k, "leaning"), "transform", {
            "rotate_axis": direction(hinge), "rotate_angle": {"magnitude": num(tilt), "unit": "deg"},
            "rotate_origin": point(w)}, item=item.id, inputs=(upright,))  # fmt: skip
        _leaning_names(chain, item, copy, face, upright, "end_face" if mode == "normal" else "start_face", (c, s),
                       hinge, height, back)  # fmt: skip
    top = height * c + reach * s + 1.0
    half = height * s + reach / c + 1.0
    keep = _keep(chain, item, k, face, w, n, 0.0, top, half)
    tool = chain.boolean(_id(item.id, k, "standing"), "intersect", [solid, keep], item=item.id)
    assert copy.lo is not None and copy.hi is not None
    chain.add_box(Box(copy.lo, copy.hi, item.id, k))
    return tool
