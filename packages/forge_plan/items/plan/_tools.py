"""Helpers the ``plan`` role's kinds and program share (a leaf: it imports neither the kinds' modules nor the program), moved at stage 4b.0b's step 3."""

from __future__ import annotations

import math
from collections.abc import Mapping

from forge_numeric import scalar as fs
from forge_spec.draft import Choice, Item, Profile
from forge_spec.ends import ThroughAll, end_of
from forge_spec.geometry import FlatFace, Part, SideFace, most_material_under
from forge_spec.placement import Instance
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
    length,
    neg,
    num,
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
