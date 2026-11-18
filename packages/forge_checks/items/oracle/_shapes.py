"""The shapes and edges the oracle's kinds are made of (the ``oracle`` role's leaf: it imports neither the kinds' modules, but for the registry when asked, nor ``oracle.py``).

Moved from ``oracle.py`` at stage 4b.0b's step 3, unchanged but for each
kind's branch, which is its own module's, and what another kind publishes,
asked of the registry: a standing item's solid, a cut's, a rounding's
chains of edges, and the small geometry they are written with.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import TYPE_CHECKING

import numpy as np
from forge_numeric import scalar as fs
from forge_numeric import vector as fv
from forge_spec.draft import Choice, Item
from forge_spec.values import Value
from numpy.typing import NDArray

from forge_checks import rounds
from forge_checks.convex import ConvexError, Pieces, convex_pieces
from forge_checks.csg import Inter, Minus, Node, Union, leaves
from forge_checks.outlines import Arc as OutlineArc
from forge_checks.outlines import Outline
from forge_checks.outlines import Segment as OutlineSegment
from forge_checks.place import (
    FLAT_AXES,
    Copy,
    Face,
    FlatFace,
    Hollow,
    Placed,
    PlaceError,
    RoundBall,
    RoundSide,
    direction_of,
    opposite,
    section_of,
    unit,
)
from forge_checks.shapes import (
    Ball,
    Complement,
    Disc,
    Frame,
    Halfspace,
    Prism,
    Round,
    RoundRect,
    Shape2D,
)

if TYPE_CHECKING:
    from forge_checks.items.oracle.protocol import OracleKind
    from forge_checks.oracle import _Making


class Piece(StrEnum):
    """A side of an outline in a plane (:data:`Piece2`): a straight segment or an arc."""

    SEG = "seg"
    ARC = "arc"


Array = NDArray[np.float64]


Vec = tuple[float, float, float]


Vec3 = tuple[float, float, float]


class OracleError(ValueError):
    """The definitions don't give this spec's shape (for now)."""


# ----------------------------------------------------------------------
# Building the steps
# ----------------------------------------------------------------------
def _mm(value: object) -> float:
    if not isinstance(value, Value):
        raise OracleError(f"not a length: {value!r}")
    return value.made_in("mm")


def _choice(item: Item, name: str) -> str | None:
    value = item.get(name)
    return value.value if isinstance(value, Choice) else None


def _vec(v: Sequence[float] | Array) -> Vec:
    return (float(v[0]), float(v[1]), float(v[2]))


def _frame(
    origin: Sequence[float] | Array,
    first: Sequence[float] | Array,
    second: Sequence[float] | Array,
) -> Frame:
    """A frame from two axes across it; its third is their cross product."""
    u, v = np.asarray(first, dtype=float), np.asarray(second, dtype=float)
    w = np.cross(u, v)
    return Frame(_vec(origin), _vec(u), _vec(v), _vec(w))


def _axis(name: str) -> NDArray[np.float64]:
    return np.asarray(unit("+" + name), dtype=float)


def copy_axes(copy: Copy) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """The two axes a copy's outline is drawn in: its face's, turned by the copy's ``place.turn`` where it has one."""
    assert copy.axes is not None
    first, second = _axis(copy.axes[0]), _axis(copy.axes[1])
    if copy.turn is None:
        return first, second
    c, s = copy.turn
    return c * first + s * second, -s * first + c * second


def _on_side(section: Prism, side: RoundSide) -> Node:
    """A feature standing round a side: its section's prism, on the open side of the side's surface."""
    axis = Frame.along(side.start, unit("+" + side.axis))
    if side.outward:
        return Inter((section, Complement(Round(axis, side.radius))))
    return Inter((section, Round(axis, side.radius)))


def leaning_axes(copy: Copy) -> tuple[NDArray[np.float64], NDArray[np.float64], float, float]:
    """A leaning copy's own two axes across its direction (its face's, turned with it, then tilted with it about the line
    in the face square to its lean), and the cosine and sine of its tilt."""
    assert copy.lean is not None
    n, u = np.asarray(copy.direction, dtype=float), np.asarray(copy.lean, dtype=float)
    c = float(fv.matmul(u, n))
    s = math.sqrt(max(1.0 - c * c, 0.0))
    w = (u - c * n) / s  # its lean's way, in the face
    found = []
    for e in copy_axes(copy):
        along = float(fv.matmul(e, w))  # +1, -1 (along its lean) or 0 (across it)
        found.append(e if abs(along) < 0.5 else c * e - s * along * n)
    return found[0], found[1], c, s


def leaning_node(copy: Copy, outline: Shape2D, reach: float, height: float, into: bool) -> Node:
    """A leaning item's solid (place.md, "Leaning on the face"): its outline across its direction, from far enough back
    for its whole outline to be past its face's plane to ``height`` along it, kept on the face's open side (standing,
    ``into`` False) or within its material (a cut, ``into`` True, ``height`` its depth into it)."""
    first, second, c, s = leaning_axes(copy)
    frame = _frame(copy.point, first, second)
    u = np.asarray(copy.lean, dtype=float)
    sign = float(fv.matmul(np.asarray(frame.w), u))  # +1 or -1: the frame's third axis is its way, or back
    back = reach * s / c + 1.0  # far enough back that its whole outline is past the face's plane
    lo, hi = (-back, height) if not into else (-height, back)
    t0, t1 = sorted((sign * lo, sign * hi))
    n = np.asarray(copy.direction, dtype=float)
    keep = Halfspace(copy.point, tuple(float(x) for x in (n if into else -n)))  # type: ignore[arg-type]
    return Inter((Prism(frame, outline, t0, t1), keep))


def _standing_prism(
    copy: Copy, outline: Shape2D, height: float, face: FlatFace | RoundSide | RoundBall | None
) -> Node:
    """A standing item's solid: its outline across its direction, from its point out to ``height``."""
    assert copy.axes is not None
    if copy.lean is not None and isinstance(outline, RoundRect):
        return leaning_node(copy, outline, fs.hypot(outline.h1, outline.h2), height, False)
    u = np.asarray(copy.direction, dtype=float)
    first, second = copy_axes(copy)
    frame = _frame(copy.point, first, second)
    sign = float(
        fv.matmul(np.asarray(frame.w), u)
    )  # +1 or -1: the frame's third axis is the way it grows, or back
    if isinstance(face, RoundSide):
        bottom = -face.radius if face.outward else 0.0
        t0, t1 = sorted((sign * bottom, sign * height))
        return _on_side(Prism(frame, outline, t0, t1), face)
    if isinstance(face, RoundBall):  # from the plane through its centre, outside the ball (item 3b's second step)
        t0, t1 = sorted((-sign * face.radius, sign * height))
        return Inter((Prism(frame, outline, t0, t1), Complement(Ball(face.centre, face.radius))))
    t0, t1 = sorted((0.0, sign * height))
    return Prism(frame, outline, t0, t1)


def convex_pieces_of(item: Item) -> Pieces:
    """An extrusion's outline, or a revolution's half outline, in convex pieces (:mod:`forge_checks.convex`)."""
    try:
        return convex_pieces(section_of(item))
    except (ConvexError, PlaceError) as e:
        raise OracleError(f"{item.id}: {e}") from None


def _together(added: Sequence[Node], taken: Sequence[Node]) -> Node:
    """The pieces an outline holds, less those it doesn't."""
    whole = added[0] if len(added) == 1 else Union(tuple(added))
    if not taken:
        return whole
    return Minus(whole, taken[0] if len(taken) == 1 else Union(tuple(taken)))


def _off_axis(p: tuple[float, float]) -> tuple[float, float]:
    """A point of a half outline: on the axis exactly where it is within a billionth of a millimetre of it."""
    return (0.0 if p[0] < 1e-9 else p[0], p[1])


def _round_bulge(centre: tuple[float, float], r: float, a: tuple[float, float],
                 outward: tuple[float, float]) -> tuple[tuple[float, float], ...]:  # fmt: skip
    """A convex polygon on the arc's side of a chord through ``a``, holding all the disc on that side, none across the axis.

    The square round the disc (a quarter of its radius and a millimetre
    wider), cut by the chord's line and by the axis: the disc meets it in
    the bulge alone, since the bulge is off the axis.
    """
    m = r * 1.25 + 1.0
    (cx, cy), (nx, ny) = centre, outward
    corners = [(cx + m, cy + m), (cx - m, cy + m), (cx - m, cy - m), (cx + m, cy - m)]

    def chord_side(p: tuple[float, float]) -> float:
        return (p[0] - a[0]) * nx + (p[1] - a[1]) * ny

    def off_axis(p: tuple[float, float]) -> float:
        return p[0]

    for keep in (chord_side, off_axis):
        cut: list[tuple[float, float]] = []
        for k, p in enumerate(corners):
            q = corners[(k + 1) % len(corners)]
            fp, fq = keep(p), keep(q)
            if fp >= 0:
                cut.append(p)
            if (fp < 0) != (fq < 0):
                t = fp / (fp - fq)
                cut.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])))
        corners = cut
    found: list[tuple[float, float]] = []
    for p in map(_off_axis, corners):
        if not found or fs.dist(p, found[-1]) > 1e-9:
            found.append(p)
    if len(found) > 1 and fs.dist(found[0], found[-1]) <= 1e-9:
        found.pop()
    return tuple(found)


# --- Edges, as each kind's page names them --------------------------------
def _cyclic(k: int) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Two frame axes across axis ``k``, turning the right way round it."""
    e = np.eye(3)
    return e[(k + 1) % 3], e[(k + 2) % 3]


def _box_edge(
    lo: Vec, hi: Vec, f1: str, f2: str, inward: tuple[str, ...] = ()
) -> rounds.StraightEdge:
    """The edge of an axis-aligned box between faces ``f1`` and ``f2`` (a face in ``inward`` faces into the box: a hollow's wall)."""
    i1, i2 = "xyz".index(f1[1]), "xyz".index(f2[1])
    k = 3 - i1 - i2
    origin = [0.0, 0.0, 0.0]
    for i, f in ((i1, f1), (i2, f2)):
        origin[i] = hi[i] if f[0] == "+" else lo[i]
    origin[k] = lo[k]
    u, v = _cyclic(k)
    bounds = []
    for f in (f1, f2):
        n = np.asarray(unit(f), dtype=float) * (-1.0 if f in inward else 1.0)
        bounds.append(rounds.Line2((float(fv.matmul(n, u)), float(fv.matmul(n, v)))))
    along = np.eye(3)[k]
    return rounds.StraightEdge(
        _vec(origin), _vec(along), hi[k] - lo[k], _vec(u), _vec(v), bounds[0], bounds[1]
    )


def _prism_of(node: Node) -> Prism:
    found = next((leaf for leaf in leaves(node) if isinstance(leaf, Prism)), None)
    if found is None:
        raise OracleError("a body made of no prism has no straight edges")
    return found


def _whole_face(pairs: Sequence[tuple[str, str]]) -> str | None:
    """The face, if the edges are the four all round it."""
    if len(pairs) != 4:
        return None
    shared = set(pairs[0])
    for pair in pairs[1:]:
        shared &= set(pair)
    if len(shared) != 1:
        return None
    face = shared.pop()
    sides = {f for pair in pairs for f in pair} - {face}
    return face if len(sides) == 4 and all(f[1] != face[1] for f in sides) else None


def _wall(target: Item, making: _Making) -> float:
    from forge_checks.items.oracle import ORACLE

    shell = next(
        i
        for i in making.items.values()
        if ORACLE[i.kind].hollows and i.get("of") == target.id
    )
    return _mm(shell.get("thickness"))


def _hollow_loop(
    prism: Prism,
    hollow: Hollow,
    face: str,
    corners: Mapping[frozenset[str], tuple[str, float]],
    wall: float,
) -> rounds.Chain:
    """The inside edge of an open face's rim: round the hollow, where the walls end, its corners following the body's."""
    inner: dict[frozenset[str], tuple[str, float]] = {}
    for pair, (kind, size) in corners.items():
        less = (
            size - wall
            if kind == rounds.Corner.FILLET
            else size - (2 - math.sqrt(2)) * wall
        )
        if less > 0:
            inner[pair] = (kind, less)
    lo, hi = list(hollow.lo), list(hollow.hi)
    k = "xyz".index(face[1])
    lo[k] = hi[k] = prism.hi[k] if face[0] == "+" else prism.lo[k]
    return _face_loop(lo, hi, face, inner, False)


def _across_at(
    side: OutlineSegment | OutlineArc, p: tuple[float, float]
) -> tuple[float, float]:
    """The line a side runs along at its point ``p``, as a unit vector (either way along it)."""
    if isinstance(side, OutlineSegment):
        return _unit2(side.b[0] - side.a[0], side.b[1] - side.a[1])
    out = _unit2(p[0] - side.centre[0], p[1] - side.centre[1])
    return -out[1], out[0]


def _outline_boundary(outline: Outline, side: OutlineSegment | OutlineArc, corner: tuple[float, float],
                      at: tuple[float, float], *, material: bool, axes: tuple[Array, Array] | None = None) -> rounds.Boundary:  # fmt: skip
    """A side of an outline as a boundary of the section across an edge at ``corner``: a line square to its normal away from the material (or, ``material`` False, towards it), or its circle.

    The section's coordinates are the outline's, less ``at``; or, given
    ``axes`` (the section's two axes, each as its components along the
    outline's two), along those.
    """
    if isinstance(side, OutlineSegment):
        other = side.b if fs.dist(side.a, corner) <= 1e-9 else side.a
        d = _unit2(other[0] - corner[0], other[1] - corner[1])
        normal = (d[1], -d[0])
        middle = ((side.a[0] + side.b[0]) / 2, (side.a[1] + side.b[1]) / 2)
        step = 1e-6 * max(1.0, fs.dist(side.a, side.b))
        if (
            outline.signed_distance(
                (middle[0] + step * normal[0], middle[1] + step * normal[1])
            )
            < 0
        ):
            normal = (-normal[0], -normal[1])  # it pointed into the material
        if not material:
            normal = (-normal[0], -normal[1])
        if axes is not None:
            normal = (
                float(fv.matmul(axes[0], normal)),
                float(fv.matmul(axes[1], normal)),
            )
        return rounds.Line2(normal)
    middle = side.at(side.start + side.sweep / 2)
    towards = _unit2(side.centre[0] - middle[0], side.centre[1] - middle[1])
    step = 1e-6 * max(1.0, side.radius)
    inside = (
        outline.signed_distance(
            (middle[0] + step * towards[0], middle[1] + step * towards[1])
        )
        < 0
    )
    centre = (side.centre[0] - at[0], side.centre[1] - at[1])
    if axes is not None:
        centre = (float(fv.matmul(axes[0], centre)), float(fv.matmul(axes[1], centre)))
    return rounds.Circle2(centre, side.radius, inside == material)


def _circle(
    frame: Frame, rho: float, z: float, b1: rounds.Boundary, b2: rounds.Boundary
) -> rounds.Chain:
    edge = rounds.RoundEdge(frame.origin, frame.w, frame.u, frame.v, rho, z, b1, b2)
    return rounds.Chain((edge,), closed=True, smooth=(True,))


def _unit2(x: float, y: float) -> tuple[float, float]:
    length = fs.hypot(x, y)
    return (x / length, y / length)


#: A side of an outline in a plane: ("seg", (x0, y0, x1, y1)) or ("arc", (cx, cy, r, start, sweep)).
Piece2 = tuple[str, tuple[float, ...]]


def _outline_chain(
    frame: Frame,
    pieces: Sequence[Piece2],
    z: float,
    sign: float,
    region_inside: bool,
    region_above: bool,
) -> rounds.Chain:
    """The edge all round an outline in a frame's (u, v) plane, at height ``z`` along its third axis.

    The face the edge runs along faces ``sign`` times the frame's third
    axis. The corner's region (the material, or the air an inside edge's
    rounding fills) is inside the outline or out of it, and on the side of
    the face it faces or behind it.
    """
    u, v, w = (np.asarray(x, dtype=float) for x in (frame.u, frame.v, frame.w))
    n_face = sign * w
    face_way = -1.0 if region_above else 1.0
    wall_way = 1.0 if region_inside else -1.0
    edges: list[rounds.Edge] = []
    kinds: list[str] = []
    for kind, data in pieces:
        if kind == "seg":
            x0, y0, x1, y1 = data
            length = fs.hypot(x1 - x0, y1 - y0)
            along = ((x1 - x0) * u + (y1 - y0) * v) / length
            out = ((y1 - y0) * u - (x1 - x0) * v) / length
            su = n_face
            sv = np.asarray(np.cross(along, su), dtype=np.float64)
            origin = frame.world(np.array([x0]), np.array([y0]), np.array([z]))[0]
            wall = wall_way * out
            edges.append(rounds.StraightEdge(_vec(origin), _vec(along), length, _vec(su), _vec(sv),
                                             rounds.Line2((face_way, 0.0)),
                                             rounds.Line2((float(fv.matmul(wall, su)), float(fv.matmul(wall, sv))))))  # fmt: skip
        else:
            cx, cy, r, start_, sweep = data
            centre = frame.world(np.array([cx]), np.array([cy]), np.array([z]))[0]
            edges.append(rounds.RoundEdge(_vec(centre), frame.w, frame.u, frame.v, r, 0.0,
                                          rounds.Line2((0.0, face_way * sign)), rounds.Line2((wall_way, 0.0)),
                                          start_, sweep))  # fmt: skip
        kinds.append(kind)
    n = len(edges)
    # An arc meets its neighbours along their own line: no corner there.
    smooth = tuple(
        kinds[i] == Piece.ARC or kinds[(i + 1) % n] == Piece.ARC for i in range(n)
    )
    return rounds.Chain(tuple(edges), closed=True, smooth=smooth)


def _corner_pieces(
    h1: float, h2: float, corners: Sequence[tuple[str, float] | None]
) -> list[Piece2]:
    """A rectangle's sides in turn, anticlockwise: each corner (by quadrant) sharp, rounded, or bevelled."""
    cut = [0.0 if c is None else c[1] for c in corners]
    d0, d1, d2, d3 = cut
    sides = (
        (h1 - d0, h2, -h1 + d1, h2),
        (-h1, h2 - d1, -h1, -h2 + d2),
        (-h1 + d2, -h2, h1 - d3, -h2),
        (h1, -h2 + d3, h1, h2 - d0),
    )
    found: list[Piece2] = []
    for k, (s1, s2) in enumerate(((1, 1), (-1, 1), (-1, -1), (1, -1))):
        c = corners[k]
        if c is not None and c[0] == rounds.Corner.FILLET:
            r = c[1]
            found.append(
                ("arc", (s1 * (h1 - r), s2 * (h2 - r), r, k * math.pi / 2, math.pi / 2))
            )
        elif c is not None:
            before = sides[k - 1]
            found.append(("seg", (before[2], before[3], sides[k][0], sides[k][1])))
        x0, y0, x1, y1 = sides[k]
        if (x0, y0) != (x1, y1):
            found.append(("seg", sides[k]))
    return found


def _face_loop(
    lo: Sequence[float],
    hi: Sequence[float],
    face: str,
    corners: Mapping[frozenset[str], tuple[str, float]],
    region_inside: bool,
) -> rounds.Chain:
    """The edges all round an axis-aligned box's face, its corners as earlier roundings left them."""
    axis = face[1]
    a1, a2 = FLAT_AXES[axis]
    i1, i2, k = "xyz".index(a1), "xyz".index(a2), "xyz".index(axis)
    middle = [(lo[i] + hi[i]) / 2 for i in range(3)]
    middle[k] = hi[k] if face[0] == "+" else lo[k]
    frame = _frame(middle, _axis(a1), _axis(a2))
    sign = float(fv.matmul(np.asarray(frame.w), np.asarray(unit(face))))
    quadrant = [
        frozenset({s1 + a1, s2 + a2})
        for s1, s2 in (("+", "+"), ("-", "+"), ("-", "-"), ("+", "-"))
    ]
    pieces = _corner_pieces(
        (hi[i1] - lo[i1]) / 2, (hi[i2] - lo[i2]) / 2, [corners.get(q) for q in quadrant]
    )
    return _outline_chain(frame, pieces, 0.0, sign, region_inside, False)


def round_band(face: RoundSide | RoundBall, reach: float) -> Node:
    """What lies within ``reach`` of a round side's or a ball's surface, where it is on the part (moved with its item)."""
    at = face.placed_frame
    if isinstance(face, RoundBall):
        inner = Ball(at.origin, max(face.radius - reach, 1e-9))
        return Inter((Ball(at.origin, face.radius + reach), Complement(inner)))
    axis = Frame.along(at.origin, at.n)
    return Inter(
        (
            Round(axis, face.radius + reach),
            Complement(Round(axis, max(face.radius - reach, 1e-9))),
        )
    )


def _rim_band(
    item: Item, copy: Copy, face: FlatFace | RoundSide | RoundBall, placed: Placed, size: float
) -> Node:
    """Round a mouth on a round side, a ball's surface (item 3b's second step) or in a bore: no circle; the zone where
    its rounding must be."""
    if isinstance(face, FlatFace):
        raise OracleError(
            f"{item.id}: a cut starting inside a bore is on its round side"
        )
    reach = 4 * size
    radius = (
        placed.diameters.get(item.id, 0.0)
        or max(
            _mm(item.get(n))
            for n in ("width", "length", "diameter")
            if item.get(n) is not None
        )
    ) / 2
    # The rim's curve on the side (or the ball) falls back from the mouth's
    # point, along the way the cut goes, by at most its sagitta over the mouth.
    sag = face.radius - math.sqrt(max(face.radius * face.radius - radius * radius, 0.0))
    radius += reach
    u = np.asarray(copy.direction, dtype=float)
    near = Prism(
        Frame.along(_vec(np.asarray(copy.point) - u * (reach + sag)), u),
        Disc(radius),
        0.0,
        2 * (reach + sag),
    )
    return Inter((near, round_band(face, reach)))


def standing_box(
    copy: Copy,
    first: float,
    second: float,
    height: float,
    face: Face | None,
) -> Node:
    """A box standing on a face: ``first`` and ``second`` along its copy's axes, ``height`` out of the face."""
    return _standing_prism(copy, RoundRect(first / 2, second / 2), height, face)


def rod_node(
    copy: Copy, face: FlatFace | RoundSide | RoundBall | None, radius: float, height: float
) -> Node:
    """A cylinder's or a boss's solid: ``radius`` round its axis, ``height`` along it."""
    if copy.lean is not None:
        return leaning_node(copy, Disc(radius), radius, height, False)
    u = np.asarray(copy.direction, dtype=float)
    frame = Frame.along(copy.point, u)
    if isinstance(face, (RoundSide, RoundBall)):
        assert copy.axes is not None
        return _standing_prism(copy, Disc(radius), height, face)
    return Prism(frame, Disc(radius), 0.0, height)


def flat_cut_node(
    entry: OracleKind, item: Item, copy: Copy, face: Face
) -> Node:
    """What a slot or a pocket takes away: its outline (``entry``'s), from its mouth to its depth."""
    assert copy.span is not None
    start, depth = copy.span
    inward = -np.asarray(copy.direction, dtype=float)
    assert isinstance(face, FlatFace) and copy.axes is not None
    first, second = copy_axes(copy)
    flat = _frame(copy.point, first, second)
    sign = float(fv.matmul(np.asarray(flat.w), inward))
    t0, t1 = sorted((sign * start, sign * depth))
    return Prism(flat, entry.outline(item, copy.axes), t0, t1)


def round_rim(
    item: Item, copy: Copy, which: str, placed: Placed, size: float
) -> tuple[list[rounds.Chain], bool, list[Node], Node | None] | None:
    """A cut's rim where it is cut round a side, on a ball's surface, or from inside a bore: bounded by a band round it;
    None on a flat face."""
    assert copy.host is not None and copy.span is not None
    face = placed.face(copy.host)
    fill = which == "bottom"
    if isinstance(face, (RoundSide, RoundBall)) or copy.span[0] < 0:
        return [], fill, [_rim_band(item, copy, face, placed, size)], None
    return None


def flat_cut_chains(
    entry: OracleKind, item: Item, copy: Copy, which: str, placed: Placed, size: float
) -> tuple[list[rounds.Chain], bool, list[Node], Node | None]:
    """A slot's or a pocket's rim (its mouth's edge, taking material away) or a pocket's floor's edge (filling the corner): round its outline (``entry``'s)."""
    found = round_rim(item, copy, which, placed, size)
    if found is not None:
        return found
    assert copy.span is not None
    fill = which == "bottom"
    n_f = np.asarray(copy.direction, dtype=float)
    assert copy.axes is not None
    flat = _frame(copy.point, *copy_axes(copy))
    sign = float(fv.matmul(np.asarray(flat.w), n_f))
    depth = copy.span[1]
    z = -depth * sign if fill else 0.0
    return (
        [
            _outline_chain(
                flat, entry.outline(item, copy.axes).pieces(), z, sign, fill, fill
            )
        ],
        fill,
        [],
        None,
    )


def box_chains(
    target: Item,
    copy: Copy,
    pairs: Sequence[tuple[str, str]],
    making: _Making,
    whole: Node,
    hollow: Hollow | None,
) -> tuple[list[rounds.Chain], list[tuple[rounds.Chain, frozenset[str]]]]:
    """A box-like body's edges a rounding names: all round one face, its corners as earlier roundings left them, or each edge alone (with a rim's inside edge where an open face meets the hollow's wall); and each single edge with its two faces.

    A turned one's, or one's on a turned item's face, are found as with it
    upright and unturned (:func:`forge_checks.oracle._edge_chains`), then
    moved onto the part with it (edges.md, "A turned item's edges").
    """
    if copy.lean is not None:
        raise OracleError(f"{target.id} leans on its face: its edges aren't rounded, for now")
    assert copy.turn is None and copy.frame is None, "found as it stands upright and unturned (_edge_chains)"
    key = (target.id, copy.index)
    chains: list[rounds.Chain] = []
    single: list[tuple[rounds.Chain, frozenset[str]]] = []
    prism = _prism_of(whole)
    corners = making.corners.get(key, {})
    face = _whole_face(pairs)
    if face is not None:
        # All round one face: its corners as earlier roundings of the body's own edges left them.
        chains.append(_face_loop(prism.lo, prism.hi, face, corners, True))
        if hollow is not None and face in hollow.open:
            chains.append(
                _hollow_loop(prism, hollow, face, corners, _wall(target, making))
            )
    else:
        for f1, f2 in pairs:
            chain = rounds.Chain((_box_edge(prism.lo, prism.hi, f1, f2),))
            chains.append(chain)
            single.append((chain, frozenset({f1, f2})))
            if (
                hollow is not None
                and hollow.open & {f1, f2}
                and not {f1, f2} <= hollow.open
            ):
                # A rim's inside edge, where the open face meets the hollow's wall.
                side = f2 if f1 in hollow.open else f1
                opened = f1 if side == f2 else f2
                lo, hi = list(hollow.lo), list(hollow.hi)
                i = "xyz".index(opened[1])
                lo[i] = hi[i] = prism.hi[i] if opened[0] == "+" else prism.lo[i]
                chains.append(
                    rounds.Chain(
                        (_box_edge(_vec(lo), _vec(hi), opened, side, (side,)),)
                    )
                )
    return chains, single


def _rim_chains(
    target: Item,
    copy: Copy,
    pairs: tuple[tuple[str, str], ...],
    hollow: Hollow | None,
    placed: Placed,
    r0: float,
    r1: float,
    length: float,
) -> list[rounds.Chain]:
    """A round body's rims: each end's edge with its side or its bore, a circle round the axis; ``r0`` its radius at its base, ``r1`` at its far end, ``length`` along its axis."""
    from forge_checks.items.oracle import ORACLE

    u = np.asarray(copy.direction, dtype=float)
    frame = Frame.along(copy.point, u)
    slope = _unit2(length, -(r1 - r0))
    found = []
    for end, side in pairs:
        z, radius, sign = (length, r1, 1.0) if end == "+end" else (0.0, r0, -1.0)
        if side == "bore":
            radius = _mm(target.get("inner_diameter")) / 2
            wall: rounds.Boundary = rounds.Line2((-1.0, 0.0))
        else:
            wall = rounds.Line2(slope)
        found.append(_circle(frame, radius, z, rounds.Line2((0.0, sign)), wall))
        if hollow is not None and end in hollow.open and side == "side":
            # The rim's inside edge, on the hollow's wall.
            inner = ORACLE[target.kind].hollow(target, copy, placed)
            assert isinstance(inner, Prism) and isinstance(inner.shape, Disc)
            found.append(
                _circle(
                    frame,
                    inner.shape.r,
                    z,
                    rounds.Line2((0.0, sign)),
                    rounds.Line2((-1.0, 0.0)),
                )
            )
    return found


def round_footprint(copy: Copy, radius: float, side: rounds.Boundary) -> rounds.Chain:
    """The corner round a round item's foot (``radius`` round its axis, its side ``side``), in the air above the face and outside the item."""
    g = np.asarray(copy.direction, dtype=float)
    frame = Frame.along(copy.point, g)
    return _circle(frame, radius, 0.0, rounds.Line2((0.0, -1.0)), side)


def box_footprint(
    copy: Copy, corners: Mapping[frozenset[str], tuple[str, float]]
) -> rounds.Chain:
    """The corner round a box-like item's foot, in the air above the face and outside the item."""
    assert copy.lo is not None and copy.hi is not None
    up = direction_of(copy.direction)
    assert up is not None
    # Its foot: round the face of its box it stands with, its corners as its own roundings left them;
    # the air beside it, on the host's side of that face.
    return _face_loop(copy.lo, copy.hi, opposite(up), corners, False)
