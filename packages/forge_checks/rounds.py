"""Roundings and chamfers, as the oracle makes them (docs/definitions/fillet.md, chamfer.md, edges.md).

A rounding replaces each edge of its edge set: on an outside edge it takes
away the material between the round (or the bevel) and the edge; on an
inside edge it fills the corner. Here each edge is a **corner** in a
section across it: two boundaries through the corner point, each a straight
line (a flat face, a round side, a cone's slope, seen in a section through
the axis) or a circle (a ball's surface), with the region whose corner is
rounded (the material, or for an inside edge the air) on one side of each.

- **Exact** along each straight edge between two flat faces (the section's
  polygon pushed along the edge, less the rolling ball's cylinder) and along
  each round rim or joint, where a flat face meets a round side, a cone or a
  ball (the section turned round the axis, less the ball's torus). A bevel
  is the section's triangle.
- **Bounded** in zones: balls, as wide as the rounding's section reaches
  from its edge and its size again, round each corner where its edges meet
  at an angle, each place a rounded stretch stops (it runs into something
  standing over the edge, or out of the face, or an open edge ends at
  something other than a face square across it), and each place two of its
  stretches end together (they blend there); the stretches' own envelopes
  where it isn't known whether the edge is there; and along an edge on a
  round side, the whole band (a boss's foot on a rod: the line it follows
  is no circle). There the oracle knows only that the part holds what it
  held less the material near the edge (an outside edge), or at most that
  and the zone (an inside edge): the zone's points are unknown, never
  guessed.
- **Every piece of an edge left is rounded** (edges.md): along each edge the
  shape made so far is looked at, on both sides of each face, just off the
  edge. Where it is the corner (material on the corner's side of both
  faces and nowhere else round it), the edge is rounded; where a cut has
  taken the corner away, rounding it takes nothing, so the rounding runs on
  through and is cut off by the cut's walls as the cut found it; where
  something stands over the edge, there is no edge to round, and the
  rounding stops (in a zone). The places along an edge where this can
  change are where it crosses the surface of some solid of the shape made
  so far, found exactly: along a straight edge
  (:meth:`~forge_checks.oracle.Oracle.along`) and round a round one
  (:meth:`~forge_checks.oracle.Oracle.around`).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise

import numpy as np
from forge_numeric import scalar as fs
from forge_numeric import vector as fv
from numpy.typing import NDArray

from .csg import Inter, Minus, Node, Union
from .shapes import (
    ON,
    Ball,
    Disc,
    Frame,
    Halfspace,
    Polygon,
    Prism,
    Revolved,
    Torus,
)

__all__ = [
    "CUT",
    "EDGE",
    "OTHER",
    "UNSURE",
    "CannotMakeError",
    "Chain",
    "Circle2",
    "Line2",
    "Made",
    "RoundEdge",
    "Section",
    "StraightEdge",
    "face_end",
    "make",
    "rounding_reach",
    "section",
    "touches",
]

Array = NDArray[np.float64]
Vec = tuple[float, float, float]
Point = tuple[float, float]

#: What the shape made so far is, round a point of an edge: the corner the
#: edge is; no material there at all (a cut took it); something else (an
#: item over the edge, or the corner not there); not known (letters, a region,
#: a zone of an earlier rounding, a cone's apex).
EDGE, CUT, OTHER, UNSURE = "edge", "cut", "other", "unsure"


class Corner(StrEnum):
    """How a rounding left a box-like body's corner: rounded (by a fillet) or bevelled (by a chamfer), as the rounding's kind names it."""

    FILLET = "fillet"
    CHAMFER = "chamfer"


class CannotMakeError(ValueError):
    """The rounding can't be made on the shape as the spec makes it (a CAN'T, with the reason)."""


# ----------------------------------------------------------------------
# The section across an edge
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class Line2:
    """A straight boundary through the corner point: the region is on the side ``normal`` points away from."""

    normal: Point


@dataclass(frozen=True)
class Circle2:
    """A circular boundary through the corner point (a ball's, in a section through its axis)."""

    centre: Point
    radius: float
    inside: bool  # the region is inside the circle


Boundary = Line2 | Circle2


def _unit2(x: float, y: float) -> Point:
    length = math.hypot(x, y)
    if not (math.isfinite(length) and length > 0):
        raise ValueError(f"not a direction: {(x, y)}")
    return (x / length, y / length)


def _normal_at(b: Boundary, k: Point) -> Point:
    """The boundary's outward normal (away from the region) at the corner point."""
    if isinstance(b, Line2):
        return _unit2(*b.normal)
    away = _unit2(k[0] - b.centre[0], k[1] - b.centre[1])
    return away if b.inside else (-away[0], -away[1])


def _along(b: Boundary, other: Boundary, k: Point) -> Point:
    """The way along ``b`` from the corner that keeps to the region's edge (into the other boundary's side)."""
    n = _normal_at(b, k)
    m = _normal_at(other, k)
    f = (-n[1], n[0])
    return f if f[0] * m[0] + f[1] * m[1] < 0 else (-f[0], -f[1])


@dataclass(frozen=True)
class Section:
    """A rounding's section across its edge: the polygon it fills or takes, less the ball's circle (a fillet).

    ``reach``: how far what it changes reaches from the corner point.
    """

    corners: tuple[Point, ...]
    circle: tuple[Point, float] | None
    reach: float


def section(k: Point, b1: Boundary, b2: Boundary, size: float, fillet: bool) -> Section:
    """The section of a fillet of radius ``size`` (or a chamfer of that size) in the corner at ``k``.

    A fillet's ball touches both boundaries: its centre is ``size`` inside
    each (on the region's side). The polygon runs from where it touches one,
    to its centre, to where it touches the other, and round by the corner:
    by the point where the boundaries' tangents there meet when a boundary
    is a circle bulging out of the region (so the sliver between the circle
    and its chord is in it), by the corner itself otherwise (where the chord
    falls outside the region, which the rounding doesn't change). A chamfer's
    triangle has the corner and the two points ``size`` along the boundaries
    from it (along a circle, by arc length), closed by the tangents in the
    same way.
    """
    if not (math.isfinite(size) and size > 0):
        raise ValueError(f"a rounding has a size: {size}")
    n1, n2 = _normal_at(b1, k), _normal_at(b2, k)
    if abs(n1[0] * n2[1] - n1[1] * n2[0]) < 1e-9:
        raise CannotMakeError(
            "the faces either side of the edge are flat to each other: there is no edge"
        )
    if fillet:
        centre = _ball_centre(k, b1, b2, size)
        t1, t2 = _touch(b1, centre, size), _touch(b2, centre, size)
        corners = [t1, centre, t2, _closing(k, b1, b2, t1, t2)]
        circle: tuple[Point, float] | None = (centre, size)
    else:
        t1, t2 = _step(b1, b2, k, size), _step(b2, b1, k, size)
        corners = [t1, t2, _closing(k, b1, b2, t1, t2)]
        circle = None
    ring = _anticlockwise(corners)
    # What it changes lies between the corner and where it meets the faces:
    # the arc or bevel between those, and the faces' own stretches up to
    # them, are no farther from the corner than they (a closing point where
    # two tangents meet far off is only where the polygon is closed, out in
    # the air).
    reach = max(math.hypot(x - k[0], y - k[1]) for x, y in (t1, t2))
    return Section(ring, circle, reach)


def _ball_centre(k: Point, b1: Boundary, b2: Boundary, r: float) -> Point:
    """The centre of the ball of radius ``r`` that touches both boundaries, in the corner."""
    lines = [b for b in (b1, b2) if isinstance(b, Line2)]
    circles = [b for b in (b1, b2) if isinstance(b, Circle2)]
    if len(lines) == 2:
        m1, m2 = _normal_at(b1, k), _normal_at(b2, k)
        det = m1[0] * m2[1] - m1[1] * m2[0]
        # (c - k) . m1 = -r, (c - k) . m2 = -r
        x = (-r * m2[1] + r * m1[1]) / det
        y = (-r * m1[0] + r * m2[0]) / det
        return (k[0] + x, k[1] + y)
    if len(lines) == 1:
        line, circle = lines[0], circles[0]
        m = _normal_at(line, k)
        f = (-m[1], m[0])
        p0 = (k[0] - r * m[0], k[1] - r * m[1])
        to = circle.radius - r if circle.inside else circle.radius + r
        if to <= 0:
            raise CannotMakeError(
                f"a {r:g} mm rounding is as big as the ball's {circle.radius:g} mm radius"
            )
        dx, dy = p0[0] - circle.centre[0], p0[1] - circle.centre[1]
        half_b = dx * f[0] + dy * f[1]
        c = dx * dx + dy * dy - to * to
        disc = half_b * half_b - c
        if disc < 0:
            raise CannotMakeError(
                f"a {r:g} mm rounding doesn't fit between the flat face and the ball"
            )
        roots = (-half_b - math.sqrt(disc), -half_b + math.sqrt(disc))
        s = min(roots, key=abs)
        return (p0[0] + s * f[0], p0[1] + s * f[1])
    raise CannotMakeError(
        "an edge between two balls' surfaces isn't made by the oracle"
    )


def _touch(b: Boundary, centre: Point, r: float) -> Point:
    """Where a ball of radius ``r`` at ``centre`` touches the boundary."""
    if isinstance(b, Line2):
        m = _unit2(*b.normal)
        return (centre[0] + r * m[0], centre[1] + r * m[1])
    away = _unit2(centre[0] - b.centre[0], centre[1] - b.centre[1])
    return (b.centre[0] + b.radius * away[0], b.centre[1] + b.radius * away[1])


def _step(b: Boundary, other: Boundary, k: Point, size: float) -> Point:
    """The point ``size`` along ``b`` from the corner (by arc length along a circle), on the region's edge."""
    f = _along(b, other, k)
    if isinstance(b, Line2):
        return (k[0] + size * f[0], k[1] + size * f[1])
    if size >= math.pi * b.radius:
        raise CannotMakeError(
            f"a {size:g} mm chamfer is longer than half the ball round"
        )
    ox, oy = b.centre
    angle = fs.atan2(k[1] - oy, k[0] - ox)
    # Which way round the circle the region's edge goes from the corner.
    tangent = (-(k[1] - oy), k[0] - ox)
    turn = 1.0 if tangent[0] * f[0] + tangent[1] * f[1] > 0 else -1.0
    a = angle + turn * size / b.radius
    return (ox + b.radius * fs.cos(a), oy + b.radius * fs.sin(a))


def _closing(k: Point, b1: Boundary, b2: Boundary, p1: Point, p2: Point) -> Point:
    """The corner that closes the section: where the tangents at ``p1`` and ``p2`` meet, or the corner point.

    A circle bulging out of the region (the region inside it) is closed by
    its tangent, so the sliver between it and its chord is in the section;
    otherwise the corner point closes it.
    """
    bulges = [isinstance(b, Circle2) and b.inside for b in (b1, b2)]
    if not any(bulges):
        return k
    t1 = _tangent(b1, p1, k)
    t2 = _tangent(b2, p2, k)
    found = _meet(t1, t2)
    if found is None:
        raise CannotMakeError(
            "the faces either side of the edge are flat to each other: there is no edge"
        )
    return found


def _tangent(b: Boundary, p: Point, k: Point) -> tuple[Point, Point]:
    """The line touching the boundary at ``p``: a point on it and its normal."""
    if isinstance(b, Line2):
        return (k, _unit2(*b.normal))
    return (p, _unit2(p[0] - b.centre[0], p[1] - b.centre[1]))


def _meet(a: tuple[Point, Point], b: tuple[Point, Point]) -> Point | None:
    (p, n), (q, m) = a, b
    det = n[0] * m[1] - n[1] * m[0]
    if abs(det) < 1e-12:
        return None
    c1 = n[0] * p[0] + n[1] * p[1]
    c2 = m[0] * q[0] + m[1] * q[1]
    return ((c1 * m[1] - c2 * n[1]) / det, (n[0] * c2 - m[0] * c1) / det)


def _anticlockwise(corners: Sequence[Point]) -> tuple[Point, ...]:
    """The corners anticlockwise, with coincident ones (a corner that closes onto a touching point) dropped."""
    found: list[Point] = []
    for c in corners:
        if not found or math.dist(c, found[-1]) > 1e-12:
            found.append(c)
    if len(found) > 1 and math.dist(found[0], found[-1]) <= 1e-12:
        found.pop()
    area = sum(
        found[i][0] * found[(i + 1) % len(found)][1]
        - found[(i + 1) % len(found)][0] * found[i][1]
        for i in range(len(found))
    )
    return tuple(found if area > 0 else found[::-1])


# ----------------------------------------------------------------------
# Edges
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class StraightEdge:
    """A straight edge from ``origin``, ``length`` along ``along``; its section in the plane of ``u`` and ``v``.

    ``u``, ``v``, ``along`` are right-handed. The corner point is the edge
    itself, (0, 0) in the section.
    """

    origin: Vec
    along: Vec
    length: float
    u: Vec
    v: Vec
    b1: Boundary
    b2: Boundary

    def at(self, s: float) -> tuple[Array, Array, Array]:
        """The edge's point at ``s``, and the section's axes there."""
        o, d = np.asarray(self.origin), np.asarray(self.along)
        return o + s * d, np.asarray(self.u), np.asarray(self.v)

    @property
    def span(self) -> float:
        return self.length

    def frame(self) -> Frame:
        return Frame(self.origin, self.u, self.v, self.along)

    def corner(self) -> Point:
        return (0.0, 0.0)


@dataclass(frozen=True)
class RoundEdge:
    """A circle round ``axis`` (or an arc of it, from angle ``start`` through ``sweep``, from ``u`` towards ``v``).

    Its section is in the half-plane of distance from the axis and height
    along it, the corner point at ``(rho, z)``; ``centre`` is where height 0
    is on the axis.
    """

    centre: Vec
    axis: Vec
    u: Vec
    v: Vec
    rho: float
    z: float
    b1: Boundary
    b2: Boundary
    start: float = 0.0
    sweep: float = 2 * math.pi

    def at(self, s: float) -> tuple[Array, Array, Array]:
        """The edge's point ``s`` round it (radians from ``start``), and the section's axes there (out, along the axis)."""
        a = self.start + s
        out = fs.cos(a) * np.asarray(self.u) + fs.sin(a) * np.asarray(self.v)
        w = np.asarray(self.axis)
        return np.asarray(self.centre) + self.rho * out + self.z * w, out, w

    @property
    def span(self) -> float:
        return self.sweep

    def frame(self) -> Frame:
        return Frame(self.centre, self.u, self.v, self.axis)

    def corner(self) -> Point:
        return (self.rho, self.z)


Edge = StraightEdge | RoundEdge


@dataclass(frozen=True)
class Chain:
    """Edges end to end: one edge alone, an outline's sides in turn (``closed``), joined smoothly or not.

    ``smooth[i]`` says whether edge ``i`` runs on into edge ``i + 1`` (into
    the first, for the last of a closed chain) without a corner.
    """

    edges: tuple[Edge, ...]
    closed: bool = False
    smooth: tuple[bool, ...] = ()
    #: Whether a rounding reaching an open chain's start, and its end, stops there cleanly: the edge
    #: ends at a face square across it (a box's edge at its corner), not running on into another edge.
    clean: tuple[bool, bool] = (True, True)

    def __post_init__(self) -> None:
        joins = len(self.edges) if self.closed else len(self.edges) - 1
        if not self.smooth:
            object.__setattr__(self, "smooth", (False,) * joins)
        if len(self.smooth) != joins:
            raise ValueError("a chain says, at each join, whether it is smooth")


# ----------------------------------------------------------------------
# Along an edge: what is there
# ----------------------------------------------------------------------
#: Asked of the shape made so far, for many points at once, each with its own directions (points,
#: directions, 3): whether it holds the points just off each along each direction, in its inner and outer
#: forms (points, directions), and where that is known (not at a singular point); with the roundings and
#: chamfers made so far, or (``False``) without them.
Held = Callable[
    [Array, Array, bool],
    tuple[NDArray[np.bool_], NDArray[np.bool_], NDArray[np.bool_]],
]
#: The places along a straight segment where the shape made so far can change: (origin, direction, length) -> distances.
Places = Callable[[Array, Array, float], Array]
#: The places round a circle where it can change: (centre, u, v, radius) -> angles from ``u`` towards ``v``, in [0, 2 pi).
Turns = Callable[[Array, Array, Array, float], Array]


def _quadrants(edge: Edge, s: float) -> tuple[Array, Array]:
    """The edge's point at ``s``, and four directions just off it: into the corner's region, away, and either side."""
    point, e1, e2 = edge.at(s)
    k = edge.corner()
    m1, m2 = _normal_at(edge.b1, k), _normal_at(edge.b2, k)
    n1 = m1[0] * e1 + m1[1] * e2
    n2 = m2[0] * e1 + m2[1] * e2
    ways = np.array([-(n1 + n2), n1 + n2, n1 - n2, n2 - n1])
    return point, ways / fv.norm(ways, axis=1)[:, None]


def _what(held: Held, edge: Edge, at: Sequence[float], fill: bool) -> list[str]:
    """What the shape made so far is round the edge at each of ``at``.

    Where an earlier rounding (not a cut) took the corner away, the edge
    runs on smoothly into that rounding's edge, which this one doesn't
    round: that is no corner to round through (``OTHER``), as a cut's is.
    """
    if not at:
        return []
    quadrants = [_quadrants(edge, s) for s in at]
    points = np.array([q[0] for q in quadrants])
    ways = np.array([q[1] for q in quadrants])
    inner, outer, known = held(points, ways, True)
    found: list[str] = []
    for p in range(len(at)):
        kinds = {_kind(inner[p], fill), _kind(outer[p], fill)}
        found.append(
            UNSURE if not known[p] else kinds.pop() if len(kinds) == 1 else UNSURE
        )
    cut = [p for p, kind in enumerate(found) if kind == CUT]
    if cut:
        inner, outer, known = held(points[cut], ways[cut], False)
        for n, p in enumerate(cut):
            if known[n] and EDGE in (_kind(inner[n], fill), _kind(outer[n], fill)):
                found[p] = OTHER
    return found


def _kind(held: NDArray[np.bool_], fill: bool) -> str:
    """The corner's region is the material (an outside edge) or the air (an inside edge, ``fill``)."""
    region, away, side1, side2 = (bool(x) for x in held)
    if fill:
        return EDGE if not region and away and side1 and side2 else OTHER
    if region and not (away or side1 or side2):
        return EDGE
    if not (region or away or side1 or side2):
        return CUT
    return OTHER


def _pieces(
    edge: Edge,
    held: Held,
    places: Places,
    turns: Turns,
    fill: bool,
    meets: tuple[Point, Point],
) -> list[tuple[float, float, str]]:
    """Along the edge: each stretch between the places what is there can change, and what it is.

    ``meets``: where the rounding meets the faces, in the section. Where the
    edge is there but one of those lines is off its face (the face ends
    before the rounding reaches it: a hole's rim a hair from the plate's
    side), the rounding's shape isn't the one its definition gives: that
    stretch is only bounded (``UNSURE``). The places are where the edge, or
    either of those lines, crosses a surface of the shape made so far.
    """
    lines = [edge.corner(), *meets]
    cuts: list[float] = []
    for c in lines:
        if isinstance(edge, StraightEdge):
            origin = (
                np.asarray(edge.origin)
                + c[0] * np.asarray(edge.u)
                + c[1] * np.asarray(edge.v)
            )
            cuts += [
                float(t) for t in places(origin, np.asarray(edge.along), edge.length)
            ]
        elif c[0] > 1e-9:
            middle = np.asarray(edge.centre) + c[1] * np.asarray(edge.axis)
            angles = turns(middle, np.asarray(edge.u), np.asarray(edge.v), c[0])
            cuts += [float(t) for t in np.mod(angles - edge.start, 2 * math.pi)]
    span = edge.length if isinstance(edge, StraightEdge) else edge.sweep
    scale = 1.0 if isinstance(edge, StraightEdge) else edge.rho
    ends = [0.0, *sorted(t for t in cuts if 0 < t < span), span]
    middles = [(a + b) / 2 for a, b in pairwise(ends)]
    kinds = _what(held, edge, middles, fill)
    edged = [p for p, kind in enumerate(kinds) if kind == EDGE]
    faced = np.ones(len(edged), dtype=bool)
    for side, meet in ((1, meets[0]), (2, meets[1])):
        faced &= _faced(held, edge, [middles[p] for p in edged], side, meet, fill)
    for p, ok in zip(edged, faced, strict=True):
        if not ok:
            kinds[p] = UNSURE
    found = [(a, b, kind) for (a, b), kind in zip(pairwise(ends), kinds, strict=True)]
    return _tidy(found, scale)


def _faced(
    held: Held, edge: Edge, at: Sequence[float], side: int, meet: Point, fill: bool
) -> NDArray[np.bool_]:
    """Whether the face on ``side`` is there where the rounding meets it, at each of ``at`` along the edge: the region's side of it on one hand, the other side on the other."""
    if not at:
        return np.zeros(0, dtype=bool)
    boundary = edge.b1 if side == 1 else edge.b2
    if isinstance(boundary, Line2):
        n = _unit2(*boundary.normal)
    else:
        away = _unit2(meet[0] - boundary.centre[0], meet[1] - boundary.centre[1])
        n = away if boundary.inside else (-away[0], -away[1])
    corner = edge.corner()
    points, ways = [], []
    for s in at:
        point, e1, e2 = edge.at(s)
        points.append(point + (meet[0] - corner[0]) * e1 + (meet[1] - corner[1]) * e2)
        out = n[0] * e1 + n[1] * e2
        ways.append([-out, out])
    inner, outer, known = held(np.array(points), np.array(ways), True)
    region = not fill
    return np.asarray(
        known
        & np.all(
            [
                (form[:, 0] == region) & (form[:, 1] != region)
                for form in (inner, outer)
            ],
            axis=0,
        )
    )


#: Places along an edge closer than this (mm) are one: so short a stretch is none (its points are on its ends' faces).
_APART = 2 * ON


def _tidy(
    found: list[tuple[float, float, str]], scale: float
) -> list[tuple[float, float, str]]:
    """The stretches with each no longer than :data:`_APART` (``scale`` times its span) given to the one before it, or the first to the one after, and neighbours alike made one."""
    kept: list[tuple[float, float, str]] = []
    start: float | None = None
    for a, b, kind in found:
        if (b - a) * scale <= _APART:
            if kept:
                kept[-1] = (kept[-1][0], b, kept[-1][2])
            elif start is None:
                start = a
            continue
        if start is not None:
            a, start = start, None
        if kept and kept[-1][2] == kind:
            kept[-1] = (kept[-1][0], b, kind)
        else:
            kept.append((a, b, kind))
    return kept


# ----------------------------------------------------------------------
# What a rounding makes
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class Made:
    """What a rounding makes on one copy of what it rounds.

    ``pieces``: its exact solids (taken away, or for an inside edge added),
    each with the edge and the stretch of it they round. ``zones``: where it
    is only bounded. ``edged``: whether any of its edges is there, or may be
    (not known where something isn't: letters, a region, an earlier
    rounding's zone).
    """

    pieces: tuple[tuple[Node, Edge, float, float], ...]
    zones: tuple[Node, ...]
    fill: bool
    size: float
    fillet: bool
    edged: bool = True


def make(
    chains: Sequence[Chain],
    size: float,
    fillet: bool,
    fill: bool,
    held: Held,
    places: Places,
    turns: Turns,
) -> Made:
    """A rounding of the given edges on the shape made so far (see the module's docstring).

    Zones go where the rounding's shape isn't known exactly: where a run of
    it stops inside an edge (at something standing over it, or where an
    earlier rounding took the corner away); at a corner within an outline
    where it turns; where an open chain's end isn't a clean stop; where two
    of its runs end at one corner (they blend there); and all along a
    stretch where it isn't known whether the edge is there.
    """
    pieces: list[tuple[Node, Edge, float, float]] = []
    zones: list[Node] = []
    ends: list[tuple[Array, float, bool]] = []
    edged = False
    for chain in chains:
        sections = [section(e.corner(), e.b1, e.b2, size, fillet) for e in chain.edges]
        zone = max(s.reach for s in sections) + size
        stretches: list[tuple[int, float, float, str]] = []
        for i, e in enumerate(chain.edges):
            stretches += [
                (i, a, b, k)
                for a, b, k in _pieces(
                    e, held, places, turns, fill, touches(e, size, fillet)
                )
            ]
        edged = edged or any(k in (EDGE, UNSURE) for _, _, _, k in stretches)
        rounded = [k in (EDGE, CUT) for _, _, _, k in stretches]
        n = len(stretches)
        # Runs of stretches rounded, each with at least one of the edge itself in it.
        if chain.closed and all(rounded):
            runs = [list(range(n))] if any(k == EDGE for *_, k in stretches) else []
            whole = True
        else:
            first = next(i for i in range(n) if not rounded[i]) if chain.closed else 0
            order = (
                [(first + j) % n for j in range(n)] if chain.closed else list(range(n))
            )
            runs, now = [], []
            for i in order:
                if rounded[i]:
                    now.append(i)
                else:
                    if now:
                        runs.append(now)
                    now = []
            if now:
                runs.append(now)
            runs = [r for r in runs if any(stretches[i][3] == EDGE for i in r)]
            whole = False
        through: set[int] = set()
        for run in runs:
            for i in run:
                e_index, a, b, _ = stretches[i]
                edge = chain.edges[e_index]
                pieces.append((_piece(edge, sections[e_index], a, b), edge, a, b))
            through |= {stretches[i][0] for i in run}
            if whole:
                continue
            for i, at_start in ((run[0], True), (run[-1], False)):
                e_index, a, b, _ = stretches[i]
                edge = chain.edges[e_index]
                s_ = a if at_start else b
                point, _, _ = edge.at(s_)
                chain_end = not chain.closed and (
                    (at_start and e_index == 0 and a == 0.0)
                    or (
                        not at_start
                        and e_index == len(chain.edges) - 1
                        and b == edge.span
                    )
                )
                clean = chain_end and chain.clean[0 if at_start else 1]
                ends.append((point, zone, clean))
        # Corners within the chain where its edges meet at an angle, and the rounding turns or stops there.
        for j, smooth in enumerate(chain.smooth):
            if not smooth and (j in through or (j + 1) % len(chain.edges) in through):
                last = chain.edges[j]
                zones.append(_ball(last, last.span, zone))
        # Where it isn't known whether the edge is there: the whole stretch.
        for e_index, a, b, k in stretches:
            if k == UNSURE:
                edge = chain.edges[e_index]
                zones += [
                    _envelope(edge, sections[e_index], a, b),
                    _ball(edge, a, zone),
                    _ball(edge, b, zone),
                ]
    # Each stop that isn't clean, or that another run stops at too (two rounded edges meeting at a corner).
    for at, (point, radius, clean) in enumerate(ends):
        shared = any(
            j != at and float(fv.norm(point - other)) <= 1e-9
            for j, (other, _, _) in enumerate(ends)
        )
        if not clean or shared:
            zones.append(
                Ball((float(point[0]), float(point[1]), float(point[2])), radius)
            )
    return Made(tuple(pieces), tuple(zones), fill, size, fillet, edged)


def _ball(edge: Edge, s: float, radius: float) -> Node:
    point, _, _ = edge.at(s)
    return Ball((float(point[0]), float(point[1]), float(point[2])), radius)


def _piece(edge: Edge, sec: Section, a: float, b: float) -> Node:
    """The rounding's solid along the edge from ``a`` to ``b``: its polygon less its ball's sweep."""
    whole = _envelope(edge, sec, a, b)
    if sec.circle is None:
        return whole
    (c1, c2), r = sec.circle
    if isinstance(edge, StraightEdge):
        f = edge.frame()
        o = np.asarray(f.origin) + c1 * np.asarray(f.u) + c2 * np.asarray(f.v)
        frame = Frame((float(o[0]), float(o[1]), float(o[2])), f.u, f.v, f.w)
        return Minus(whole, Prism(frame, Disc(r), a - r, b + r))
    f = edge.frame()
    o = np.asarray(f.origin) + c2 * np.asarray(f.w)
    frame = Frame((float(o[0]), float(o[1]), float(o[2])), f.u, f.v, f.w)
    return Minus(whole, Torus(frame, max(c1, 0.0), r))


def _envelope(edge: Edge, sec: Section, a: float, b: float) -> Node:
    """The section's polygon along the edge from ``a`` to ``b``: pushed along a straight edge, turned round a round one."""
    if isinstance(edge, StraightEdge):
        return Prism(edge.frame(), Polygon(sec.corners), a, b)
    turned = _turned(edge.frame(), sec.corners)
    if b - a >= 2 * math.pi - 1e-12:
        return turned
    return Inter((turned, *_wedge(edge, edge.start + a, edge.start + b)))


def _turned(frame: Frame, corners: tuple[Point, ...]) -> Node:
    """A section turned round the frame's axis: off the axis, a ring; touching it (a rim rounded right to the middle), a solid round it."""
    if min(x for x, _ in corners) < -1e-9:
        raise CannotMakeError(
            "the rounding is bigger than the round edge it rounds: it reaches past its middle"
        )
    # A corner a hair from the axis is on it; one that then repeats its neighbour, or makes no turn, goes.
    found: list[Point] = []
    for x, z in corners:
        q = (0.0 if abs(x) <= 1e-9 else x, z)
        if not found or math.dist(q, found[-1]) > 1e-12:
            found.append(q)
    if len(found) > 1 and math.dist(found[0], found[-1]) <= 1e-12:
        found.pop()
    turning = [
        found[k]
        for k in range(len(found))
        if abs(
            (found[k][0] - found[k - 1][0])
            * (found[(k + 1) % len(found)][1] - found[k][1])
            - (found[k][1] - found[k - 1][1])
            * (found[(k + 1) % len(found)][0] - found[k][0])
        )
        > 1e-15
    ]
    return Revolved(frame, Polygon(tuple(turning)))


def _wedge(edge: RoundEdge, a0: float, a1: float) -> tuple[Node, ...]:
    """The half-spaces through the axis that hold the angles from ``a0`` to ``a1`` round it."""
    u, v = np.asarray(edge.u), np.asarray(edge.v)
    found: list[Node] = []
    sweep = a1 - a0
    if sweep > math.pi + 1e-12:
        middle = (a0 + a1) / 2
        return (
            Union((Inter(_wedge(edge, a0, middle)), Inter(_wedge(edge, middle, a1)))),
        )
    for angle, sign in ((a0, 1.0), (a1, -1.0)):
        across = -fs.sin(angle) * u + fs.cos(angle) * v
        n = -sign * across
        found.append(Halfspace(edge.centre, (float(n[0]), float(n[1]), float(n[2]))))
    return tuple(found)


# ----------------------------------------------------------------------
# A hollow that follows a rounded edge
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# The walls a shell leaves behind a rounding (shell.md)
# ----------------------------------------------------------------------
def touches(edge: Edge, size: float, fillet: bool) -> tuple[Point, Point]:
    """Where a rounding meets the faces either side of its edge, in the section: where its ball touches them, or its bevel's ends."""
    k = edge.corner()
    if fillet:
        centre = _ball_centre(k, edge.b1, edge.b2, size)
        return _touch(edge.b1, centre, size), _touch(edge.b2, centre, size)
    return _step(edge.b1, edge.b2, k, size), _step(edge.b2, edge.b1, k, size)


def face_end(
    edge: Edge,
    a: float,
    b: float,
    size: float,
    fillet: bool,
    side: int,
    extent: float,
) -> Node:
    """Where a rounding from ``a`` to ``b`` along its edge ends one of the faces either side (``side`` 1 or 2): the part of the face's wall's band it takes off.

    A wall's band reaches its thickness in from its face. The rounding ends
    the face where it meets it, so along the stretch the band stops at the
    line through that point square to the face: the part on the corner's
    side is taken off. (What is within the thickness of the face's new edge
    is in :func:`rounding_reach`.) ``extent``: how far the part reaches, at
    most, from the edge (a half-plane round a round edge is turned within
    it).
    """
    k = edge.corner()
    point = touches(edge, size, fillet)[side - 1]
    boundary = edge.b1 if side == 1 else edge.b2
    if isinstance(boundary, Line2):
        normal = _unit2(*boundary.normal)
    else:
        away = _unit2(point[0] - boundary.centre[0], point[1] - boundary.centre[1])
        normal = away if boundary.inside else (-away[0], -away[1])
    along = (-normal[1], normal[0])
    if along[0] * (point[0] - k[0]) + along[1] * (point[1] - k[1]) < 0:
        along = (-along[0], -along[1])
    return _half_plane(edge, point, along, a, b, extent)


def rounding_reach(
    edge: Edge,
    a: float,
    b: float,
    size: float,
    fillet: bool,
    thickness: float,
    walls: tuple[float, float],
) -> Node | None:
    """Every point within ``thickness`` of a rounding's face along its edge from ``a`` to ``b``, and within each face's wall's (``walls``) of where it ends that face.

    A fillet's face is an arc of its ball's circle: within ``thickness`` of
    it is the ring between the circles ``thickness`` smaller and larger, in
    the arc's sector. A chamfer's is its bevel: the band ``thickness`` either
    side of it. Round each end, the disc as wide as the greater of the
    rounding's and the face's thickness: what is near both the rounding's
    end and the face's new edge. (A fillet meets its faces tangentially: with
    one thickness for both, its ring and the face's band hold that disc.)
    None if none of it is on the near side of a round edge's axis.
    """
    k = edge.corner()
    t1, t2 = touches(edge, size, fillet)
    parts: list[Node] = [
        _disc(edge, t, max(thickness, wall), a, b)
        for t, wall in ((t1, walls[0]), (t2, walls[1]))
        if not (fillet and wall == thickness)
    ]
    if fillet:
        centre = _ball_centre(k, edge.b1, edge.b2, size)
        d1 = _unit2(t1[0] - centre[0], t1[1] - centre[1])
        d2 = _unit2(t2[0] - centre[0], t2[1] - centre[1])
        middle = _unit2(d1[0] + d2[0], d1[1] + d2[1])
        half = fs.acos(max(-1.0, min(1.0, d1[0] * middle[0] + d1[1] * middle[1])))
        far = 2 * (size + thickness) / max(fs.cos(half), 1e-6)
        sector = _anticlockwise(
            [
                centre,
                *(
                    (centre[0] + far * d[0], centre[1] + far * d[1])
                    for d in (d1, middle, d2)
                ),
            ]
        )
        ring: Node = _disc(edge, centre, size + thickness, a, b)
        if size > thickness:
            ring = Minus(ring, _disc(edge, centre, size - thickness, a, b))
        wedge = _polygon(edge, tuple(sector), a, b)
        if wedge is not None:
            parts.append(Inter((ring, wedge)))
    else:
        d = _unit2(t2[0] - t1[0], t2[1] - t1[1])
        n = (-d[1] * thickness, d[0] * thickness)
        band = _anticlockwise([(t1[0] + n[0], t1[1] + n[1]), (t2[0] + n[0], t2[1] + n[1]),
                               (t2[0] - n[0], t2[1] - n[1]), (t1[0] - n[0], t1[1] - n[1])])  # fmt: skip
        found = _polygon(edge, tuple(band), a, b)
        if found is not None:
            parts.append(found)
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else Union(tuple(parts))


def _past_ends(
    edge: StraightEdge, a: float, b: float, by: float
) -> tuple[float, float]:
    """A stretch carried on ``by`` past the edge's own ends, where the body ends: so no face of the solid lies in one of its faces there."""
    return (a - by if a <= 1e-12 else a), (b + by if b >= edge.length - 1e-12 else b)


def _disc(edge: Edge, centre: Point, radius: float, a: float, b: float) -> Node:
    """Every point within ``radius`` of a point of the section, along the edge from ``a`` to ``b``."""
    if isinstance(edge, StraightEdge):
        a, b = _past_ends(edge, a, b, 1.0)
        f = edge.frame()
        o = (
            np.asarray(f.origin)
            + centre[0] * np.asarray(f.u)
            + centre[1] * np.asarray(f.v)
        )
        frame = Frame((float(o[0]), float(o[1]), float(o[2])), f.u, f.v, f.w)
        return Prism(frame, Disc(radius), a, b)
    f = edge.frame()
    o = np.asarray(f.origin) + centre[1] * np.asarray(f.w)
    frame = Frame((float(o[0]), float(o[1]), float(o[2])), f.u, f.v, f.w)
    return _within_sweep(edge, Torus(frame, max(centre[0], 0.0), radius), a, b)


def _polygon(edge: Edge, corners: tuple[Point, ...], a: float, b: float) -> Node | None:
    """A convex polygon of the section, along the edge from ``a`` to ``b``; None if nothing of it is on the near side of a round edge's axis."""
    if isinstance(edge, StraightEdge):
        a, b = _past_ends(edge, a, b, 1.0)
        return Prism(edge.frame(), Polygon(corners), a, b)
    near = _clip(corners)
    if near is None:
        return None
    return _within_sweep(edge, _turned(edge.frame(), near), a, b)


def _half_plane(
    edge: Edge, point: Point, along: Point, a: float, b: float, extent: float
) -> Node:
    """The half-plane of the section on the side of the line through ``point`` square to ``along`` that ``along`` points away from, along the edge from ``a`` to ``b``."""
    if isinstance(edge, StraightEdge):
        f = edge.frame()
        o = (
            np.asarray(f.origin)
            + point[0] * np.asarray(f.u)
            + point[1] * np.asarray(f.v)
        )
        n = along[0] * np.asarray(f.u) + along[1] * np.asarray(f.v)
        half = Halfspace(_vec3(o), _vec3(n))
        # Its ends along the edge: none where the stretch runs to the edge's own end (the body ends there).
        parts: list[Node] = [half]
        if a > 1e-12:
            start = np.asarray(edge.origin) + a * np.asarray(edge.along)
            parts.append(Halfspace(_vec3(start), _neg(edge.along)))
        if b < edge.length - 1e-12:
            end = np.asarray(edge.origin) + b * np.asarray(edge.along)
            parts.append(Halfspace(_vec3(end), edge.along))
        return parts[0] if len(parts) == 1 else Inter(tuple(parts))
    # Round a round edge: the half-plane, as far as the extent, turned.
    across = (along[1], -along[0])
    big = extent
    corners = _anticlockwise([
        (point[0] + big * across[0], point[1] + big * across[1]),
        (point[0] + big * (across[0] - along[0]), point[1] + big * (across[1] - along[1])),
        (point[0] - big * (across[0] + along[0]), point[1] - big * (across[1] + along[1])),
        (point[0] - big * across[0], point[1] - big * across[1]),
    ])  # fmt: skip
    found = _polygon(edge, tuple(corners), a, b)
    if found is None:
        raise CannotMakeError("a rounding's face is across the axis it turns round")
    return found


def _within_sweep(edge: RoundEdge, solid: Node, a: float, b: float) -> Node:
    if b - a >= 2 * math.pi - 1e-12:
        return solid
    return Inter((solid, *_wedge(edge, edge.start + a, edge.start + b)))


def _clip(corners: tuple[Point, ...]) -> tuple[Point, ...] | None:
    """A convex polygon's part on the near side of the axis (distance 0 or more), or None if it has no area there."""
    found: list[Point] = []
    n = len(corners)
    for k in range(n):
        p, q = corners[k], corners[(k + 1) % n]
        if p[0] >= 0:
            found.append(p)
        if (p[0] < 0) != (q[0] < 0):
            t = p[0] / (p[0] - q[0])
            found.append((0.0, p[1] + t * (q[1] - p[1])))
    ring = _anticlockwise(found)
    if len(ring) < 3:
        return None
    area = sum(
        ring[k][0] * ring[(k + 1) % len(ring)][1]
        - ring[(k + 1) % len(ring)][0] * ring[k][1]
        for k in range(len(ring))
    )
    return tuple(ring) if area > 1e-18 else None


def _neg(v: Vec) -> Vec:
    return (-v[0], -v[1], -v[2])


def _vec3(v: Array) -> Vec:
    return (float(v[0]), float(v[1]), float(v[2]))
