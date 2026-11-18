"""Outlines in a face's plane: rectangles (their corners possibly rounded), discs, rings, and outlines of lines and arcs.

A face, an item's footprint on a face, and the regions the material under a
face is described over are all outlines, in two coordinates: the frame's
coordinates along the face's two axes (x and y for a face facing +z or -z).
So outlines on parallel faces, a post's top and the plate it stands on, are
compared directly.

- A **rectangle** has half sizes along the two axes and a radius for each
  corner, by quadrant: (+, +), (-, +), (-, -), (+, -). A slot with round ends
  is a rectangle whose four corners are rounded to half its width; a
  round-ended tab's broad face, one with two corners rounded to half the
  tab's width. The two corners at the ends of a side may take up the whole
  side, but no more.
- A **disc** has a radius; a **ring** an outer radius and an inner one.
- A **profile** is any closed outline of straight sides and arcs that
  doesn't cross itself: an extrusion's end, or a revolution's half outline
  (:meth:`Outline.profile`). It is inside by the crossing rule (a ray along
  the first axis; each arc split where it turns back along the second, so
  every side is crossed at most once and an end counted on one side only),
  and one outline lies in it when each of its sides, split where it crosses
  the profile's, has its ends and middles in it.

Everything here is decided from closed forms, never by sampling: the signed
distance to an outline, whether a point is in it (within :data:`TOL`), the
farthest point of an outline from a point, the nearest point of where
several outlines overlap, and whether one outline lies within another.

The last two rest on a property of shapes bounded by straight sides and
circular arcs: the nearest point of an overlap, and the point of an outline
where another's signed distance is greatest, is always at a corner, where
two sides cross, or where one side comes closest to (or farthest from) a
point that defines another. Each of those points is computed, and the answer
is the best one that qualifies.

>>> plate = Outline.rect(35, 25)
>>> plate.contains((35, 0)), plate.contains((35.1, 0))
(True, False)
>>> slot = Outline.stadium(20, 6, along_first=True, centre=(10, 0))
>>> round(slot.signed_distance((23, 0)), 9)
3.0
>>> Outline.disc(3, (1, 1)).within(Outline.rect(5, 5))
True
>>> nearest_common((0, 0), [Outline.ring(10, 4), Outline.rect(2, 2, (5, 0))])
4.0
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import pairwise

from forge_numeric import scalar as fs

__all__ = [
    "TOL",
    "Arc",
    "Outline",
    "Piece",
    "Segment",
    "nearest_common",
    "nearest_point",
    "overlap",
    "turned_range",
]

Point = tuple[float, float]

#: A point this close to an outline is in it, and two outlines this close touch (mm).
TOL = 1e-9

#: The quadrants of a rectangle's corners, in the order their radii are given.
QUADRANTS = ((1, 1), (-1, 1), (-1, -1), (1, -1))

_TURN = 2 * math.pi


def _finite(*values: float) -> bool:
    return all(math.isfinite(v) for v in values)


@dataclass(frozen=True)
class Segment:
    """A straight side, from ``a`` to ``b``."""

    a: Point
    b: Point

    def ends(self) -> list[Point]:
        return [self.a, self.b]

    def nearest_to(self, c: Point) -> list[Point]:
        """The point of the side nearest ``c``."""
        (ax, ay), (bx, by) = self.a, self.b
        dx, dy = bx - ax, by - ay
        length2 = dx * dx + dy * dy
        if length2 == 0.0:
            return [self.a]
        t = min(max(((c[0] - ax) * dx + (c[1] - ay) * dy) / length2, 0.0), 1.0)
        return [(ax + t * dx, ay + t * dy)]

    def farthest_from(self, c: Point) -> list[Point]:
        return [self.a, self.b]

    def distance(self, c: Point) -> float:
        p = self.nearest_to(c)[0]
        return fs.hypot(c[0] - p[0], c[1] - p[1])


@dataclass(frozen=True)
class Arc:
    """A circular side: from angle ``start`` (radians), ``sweep`` anticlockwise; a whole circle sweeps 2π."""

    centre: Point
    radius: float
    start: float
    sweep: float

    def at(self, angle: float) -> Point:
        return (
            self.centre[0] + self.radius * fs.cos(angle),
            self.centre[1] + self.radius * fs.sin(angle),
        )

    def holds(self, angle: float) -> bool:
        """Whether the point of the circle at ``angle`` is on the arc."""
        if self.sweep >= _TURN:
            return True
        # Within an arc length of TOL of either end counts as on it.
        slack = TOL / self.radius if self.radius > 0 else _TURN
        return (angle - self.start) % _TURN <= self.sweep + slack or (
            self.start - angle
        ) % _TURN <= slack

    def ends(self) -> list[Point]:
        if self.sweep >= _TURN:
            return [self.at(k * math.pi / 2) for k in range(4)]
        return [self.at(self.start), self.at(self.start + self.sweep)]

    def toward(self, c: Point, sign: float) -> list[Point]:
        """The point of the circle nearest ``c`` (``sign`` 1) or farthest from it (-1), if it is on the arc."""
        dx, dy = c[0] - self.centre[0], c[1] - self.centre[1]
        if dx == 0.0 and dy == 0.0:
            return []  # every point of the circle is as near: its ends and quarters stand for them
        angle = fs.atan2(sign * dy, sign * dx)
        return [self.at(angle)] if self.holds(angle) else []

    def nearest_to(self, c: Point) -> list[Point]:
        return self.toward(c, 1.0)

    def farthest_from(self, c: Point) -> list[Point]:
        return self.toward(c, -1.0)

    def quarters(self) -> list[Point]:
        """The points of the arc furthest along each axis, either way."""
        return [
            self.at(k * math.pi / 2) for k in range(4) if self.holds(k * math.pi / 2)
        ]

    def distance(self, c: Point) -> float:
        near = self.nearest_to(c)
        candidates = near + self.ends()
        return min(fs.hypot(c[0] - p[0], c[1] - p[1]) for p in candidates)


Piece = Segment | Arc


@dataclass(frozen=True)
class Outline:
    """A rectangle with corners possibly rounded, a disc, a ring, or a profile, centred on ``centre`` (a profile's: its box's middle)."""

    shape: str  # "rect", "disc", "ring", "profile"
    centre: Point
    half: Point  # a rectangle's half sizes; a disc's or ring's radius, twice; a profile's box's half sizes
    corners: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    inner: float = 0.0  # a ring's inner radius
    sides: tuple[Piece, ...] = ()  # a profile's, in turn

    def __post_init__(self) -> None:
        if self.shape == "profile":
            if not self.sides or self.inner or any(self.corners):
                raise ValueError("a profile is its sides alone")
            return
        if self.sides:
            raise ValueError(f"only a profile is given its sides: {self.shape}")
        values = (*self.centre, *self.half, *self.corners, self.inner)
        if not _finite(*values):
            raise ValueError(f"an outline's sizes are finite numbers: {self}")
        h1, h2 = self.half
        if h1 <= 0 or h2 <= 0:
            raise ValueError(f"an outline has some size: {self}")
        if self.shape == "rect":
            if self.inner or min(self.corners) < 0:
                raise ValueError(f"a rectangle's corner radii are 0 or more: {self}")
            r1, r2, r3, r4 = self.corners
            sides = ((r1 + r4, 2 * h2), (r1 + r2, 2 * h1), (r2 + r3, 2 * h2), (r3 + r4, 2 * h1))  # fmt: skip
            if any(used > room + TOL for used, room in sides):
                raise ValueError(f"two rounded corners overlap along a side: {self}")
        elif self.shape in ("disc", "ring"):
            if h1 != h2 or any(self.corners):
                raise ValueError(f"a {self.shape} has one radius: {self}")
            if self.shape == "disc" and self.inner:
                raise ValueError(f"a disc has no inner radius: {self}")
            if self.shape == "ring" and not 0 < self.inner < h1:
                raise ValueError(f"a ring's inner radius is between 0 and its outer: {self}")  # fmt: skip
        else:
            raise ValueError(
                f"an outline is a rect, a disc or a ring, not {self.shape!r}"
            )

    # ------------------------------------------------------------------
    @staticmethod
    def rect(
        h1: float,
        h2: float,
        centre: Point = (0.0, 0.0),
        corners: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
    ) -> Outline:
        return Outline("rect", centre, (h1, h2), corners)

    @staticmethod
    def disc(radius: float, centre: Point = (0.0, 0.0)) -> Outline:
        return Outline("disc", centre, (radius, radius))

    @staticmethod
    def ring(radius: float, inner: float, centre: Point = (0.0, 0.0)) -> Outline:
        return Outline("ring", centre, (radius, radius), inner=inner)

    @staticmethod
    def stadium(
        length: float, width: float, *, along_first: bool, centre: Point = (0.0, 0.0)
    ) -> Outline:
        """A slot with round ends: ``length`` overall along one axis, ``width`` across."""
        if length < width:
            raise ValueError(f"a stadium {length} long can't be {width} wide")
        h = (length / 2, width / 2) if along_first else (width / 2, length / 2)
        r = width / 2
        return Outline("rect", centre, h, (r, r, r, r))

    @staticmethod
    def profile(sides: Sequence[Piece]) -> Outline:
        """A closed outline of sides and arcs, in turn, that doesn't cross itself."""
        points = [
            p
            for side in sides
            for p in (*side.ends(), *(side.quarters() if isinstance(side, Arc) else ()))
        ]
        if not points:
            raise ValueError("a profile has sides")
        lo = (min(p[0] for p in points), min(p[1] for p in points))
        hi = (max(p[0] for p in points), max(p[1] for p in points))
        return Outline("profile", ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2), ((hi[0] - lo[0]) / 2,
                       (hi[1] - lo[1]) / 2), sides=tuple(sides))  # fmt: skip

    @property
    def radius(self) -> float:
        return self.half[0]

    def moved(self, d1: float, d2: float) -> Outline:
        if self.shape == "profile":

            def move(p: Point) -> Point:
                return (p[0] + d1, p[1] + d2)

            return Outline.profile([Segment(move(q.a), move(q.b)) if isinstance(q, Segment)
                                    else Arc(move(q.centre), q.radius, q.start, q.sweep) for q in self.sides])  # fmt: skip
        return Outline(
            self.shape,
            (self.centre[0] + d1, self.centre[1] + d2),
            self.half,
            self.corners,
            self.inner,
        )

    # ------------------------------------------------------------------
    def _corner(self, k: int) -> tuple[Point, float, Point]:
        """Corner ``k``'s arc centre, radius, and the corner of the rectangle round it."""
        s1, s2 = QUADRANTS[k]
        r = self.corners[k]
        h1, h2 = self.half
        c1, c2 = self.centre
        return (
            (c1 + s1 * (h1 - r), c2 + s2 * (h2 - r)),
            r,
            (c1 + s1 * h1, c2 + s2 * h2),
        )

    def pieces(self) -> list[Piece]:
        """Its sides, in turn anticlockwise (a profile's as it runs): straight sides and arcs."""
        if self.shape == "profile":
            return list(self.sides)
        if self.shape != "rect":
            found: list[Piece] = [Arc(self.centre, self.half[0], 0.0, _TURN)]
            if self.shape == "ring":
                found.append(Arc(self.centre, self.inner, 0.0, _TURN))
            return found
        c1, c2 = self.centre
        h1, h2 = self.half
        r1, r2, r3, r4 = self.corners
        x0, x1, y0, y1 = c1 - h1, c1 + h1, c2 - h2, c2 + h2
        straight = (
            Segment((x1 - r1, y1), (x0 + r2, y1)),
            Segment((x0, y1 - r2), (x0, y0 + r3)),
            Segment((x0 + r3, y0), (x1 - r4, y0)),
            Segment((x1, y0 + r4), (x1, y1 - r1)),
        )
        found = []
        for k in range(4):
            centre, r, _ = self._corner(k)
            if r > 0:
                found.append(Arc(centre, r, k * math.pi / 2, math.pi / 2))
            side = straight[k]
            if side.a != side.b:
                found.append(side)
        return found

    def contains(self, p: Point, tol: float = TOL) -> bool:
        return self.signed_distance(p) <= tol

    def _inside(self, p: Point) -> bool:
        """Whether ``p`` is in the closed outline, exactly as its closed form says."""
        if self.shape == "profile":
            return _crossed(self.sides, p) % 2 == 1
        c1, c2 = self.centre
        d1, d2 = p[0] - c1, p[1] - c2
        if self.shape != "rect":
            far = fs.hypot(d1, d2)
            return far <= self.half[0] and (self.shape == "disc" or far >= self.inner)
        h1, h2 = self.half
        if abs(d1) > h1 or abs(d2) > h2:
            return False
        for k, (s1, s2) in enumerate(QUADRANTS):
            r = self.corners[k]
            if r > 0 and s1 * d1 > h1 - r and s2 * d2 > h2 - r:
                centre, _, _ = self._corner(k)
                return fs.hypot(p[0] - centre[0], p[1] - centre[1]) <= r
        return True

    def signed_distance(self, p: Point) -> float:
        """How far ``p`` is outside the outline: negative inside, by how far it is from the edge."""
        c1, c2 = self.centre
        if self.shape in ("disc", "ring"):
            far = fs.hypot(p[0] - c1, p[1] - c2)
            out = far - self.half[0]
            return out if self.shape == "disc" else max(out, self.inner - far)
        edge = min(piece.distance(p) for piece in self.pieces())
        return -edge if self._inside(p) else edge

    def nearest(self, c: Point) -> float:
        """How far ``c`` is from the nearest point of the outline: 0 when it is in it."""
        return max(self.signed_distance(c), 0.0)

    def farthest(self, c: Point) -> float:
        """How far ``c`` is from the farthest point of the outline."""
        points = [
            p
            for piece in self.pieces()
            for p in (*piece.ends(), *piece.farthest_from(c))
        ]
        return max(fs.hypot(c[0] - p[0], c[1] - p[1]) for p in points)

    def _features(self) -> list[Point]:
        """The points its signed distance is measured from, near its corners: the arcs' centres."""
        if self.shape == "profile":
            return [q.centre for q in self.sides if isinstance(q, Arc)]
        if self.shape != "rect":
            return [self.centre]
        return [self._corner(k)[0] for k in range(4)]

    def within(self, outer: Outline, tol: float = TOL) -> bool:
        """Whether every point of this outline lies in ``outer`` (to within ``tol``).

        This outline must be a rectangle, a disc or a profile: a footprint, or
        a mouth. Where either is a profile, each of this one's sides is split
        where it crosses the other's, and its ends and middles must lie in it
        (a simple outline whose boundary lies in a simple region lies in it;
        in a ring, besides, the ring's opening mustn't lie in this one).
        """
        if self.shape == "ring":
            raise ValueError(
                "only a rectangle, a disc or a profile is tested for lying within"
            )
        if "profile" in (self.shape, outer.shape):
            for side in self.pieces():
                cuts = sorted(
                    {
                        0.0,
                        1.0,
                        *(
                            _param(side, x)
                            for q in outer.pieces()
                            for x in crossings(side, q)
                        ),
                    }
                )
                for t in [
                    *cuts,
                    *((a + b) / 2 for a, b in pairwise(cuts) if b - a > 1e-12),
                ]:
                    if not outer.contains(_at(side, t), tol):
                        return False
            if outer.shape == "profile":  # nor any of its edge in this one: a hole in it (a block's rim round its mouth)
                return not any(self.signed_distance(_at(q, 0.5)) < -tol for q in outer.pieces())
            return not (outer.shape == "ring" and self._inside(outer.centre))
        if outer.shape == "ring":
            return (
                self.farthest(outer.centre) <= outer.half[0] + tol
                and self.nearest(outer.centre) >= outer.inner - tol
            )
        candidates: list[Point] = []
        for piece in self.pieces():
            candidates += piece.ends()
            if isinstance(piece, Arc):
                candidates += piece.quarters()
                for z in outer._features():
                    candidates += piece.toward(z, 1.0) + piece.toward(z, -1.0)
        return max(outer.signed_distance(p) for p in candidates) <= tol


# ----------------------------------------------------------------------
# Where sides cross
# ----------------------------------------------------------------------
def _cross(u: Point, v: Point) -> float:
    return u[0] * v[1] - u[1] * v[0]


def _segment_segment(s: Segment, t: Segment) -> list[Point]:
    p, r = s.a, (s.b[0] - s.a[0], s.b[1] - s.a[1])
    q, w = t.a, (t.b[0] - t.a[0], t.b[1] - t.a[1])
    denominator = _cross(r, w)
    if denominator == 0.0:
        return []  # parallel: where collinear sides overlap, their ends stand for it
    qp = (q[0] - p[0], q[1] - p[1])
    u, v = _cross(qp, w) / denominator, _cross(qp, r) / denominator
    if -1e-12 <= u <= 1 + 1e-12 and -1e-12 <= v <= 1 + 1e-12:
        return [(p[0] + u * r[0], p[1] + u * r[1])]
    return []


def _line_circle(s: Segment, arc: Arc) -> list[Point]:
    (ax, ay), (bx, by) = s.a, s.b
    dx, dy = bx - ax, by - ay
    length = fs.hypot(dx, dy)
    if length == 0.0:
        return []
    ux, uy = dx / length, dy / length
    cx, cy = arc.centre[0] - ax, arc.centre[1] - ay
    along = cx * ux + cy * uy  # the foot of the centre on the line, from a
    across = cx * uy - cy * ux
    gap = arc.radius * arc.radius - across * across
    if gap < -2 * arc.radius * TOL:
        return []
    half = math.sqrt(max(gap, 0.0))
    found = []
    for t in {along - half, along + half}:
        if -TOL <= t <= length + TOL:
            point = (ax + t * ux, ay + t * uy)
            angle = fs.atan2(point[1] - arc.centre[1], point[0] - arc.centre[0])
            if arc.holds(angle):
                found.append(point)
    return found


def _circle_circle(a: Arc, b: Arc) -> list[Point]:
    dx, dy = b.centre[0] - a.centre[0], b.centre[1] - a.centre[1]
    d = fs.hypot(dx, dy)
    if d == 0.0:
        return []  # one centre: where the circles are one, their ends stand for it
    if d > a.radius + b.radius + TOL or d < abs(a.radius - b.radius) - TOL:
        return []
    along = (d * d + a.radius * a.radius - b.radius * b.radius) / (2 * d)
    half = math.sqrt(max(a.radius * a.radius - along * along, 0.0))
    ux, uy = dx / d, dy / d
    mx, my = a.centre[0] + along * ux, a.centre[1] + along * uy
    found = []
    for sign in (1.0, -1.0):
        point = (mx - sign * half * uy, my + sign * half * ux)
        on_a = fs.atan2(point[1] - a.centre[1], point[0] - a.centre[0])
        on_b = fs.atan2(point[1] - b.centre[1], point[0] - b.centre[0])
        if a.holds(on_a) and b.holds(on_b):
            found.append(point)
    return found


def crossings(p: Piece, q: Piece) -> list[Point]:
    """Where two sides cross or touch (not where they lie along each other)."""
    if isinstance(p, Segment) and isinstance(q, Segment):
        return _segment_segment(p, q)
    if isinstance(p, Segment) and isinstance(q, Arc):
        return _line_circle(p, q)
    if isinstance(p, Arc) and isinstance(q, Segment):
        return _line_circle(q, p)
    assert isinstance(p, Arc) and isinstance(q, Arc)
    return _circle_circle(p, q)


def nearest_point(
    c: Point, outlines: Sequence[Outline], tol: float = TOL
) -> Point | None:
    """The point nearest ``c`` that lies in every outline; None if they share none.

    Outlines that only touch share the points where they touch.
    """
    if not outlines:
        raise ValueError("nearest_point needs at least one outline")

    def common(p: Point) -> bool:
        return all(o.contains(p, tol) for o in outlines)

    if common(c):
        return c
    every = [(n, piece) for n, o in enumerate(outlines) for piece in o.pieces()]
    candidates: list[Point] = []
    for _, piece in every:
        candidates += piece.ends() + piece.nearest_to(c)
    for i, (n, p) in enumerate(every):
        for m, q in every[i + 1 :]:
            if m != n:
                candidates += crossings(p, q)
    found = [p for p in candidates if common(p)]
    if not found:
        return None
    return min(found, key=lambda p: fs.hypot(c[0] - p[0], c[1] - p[1]))


def nearest_common(
    c: Point, outlines: Sequence[Outline], tol: float = TOL
) -> float | None:
    """How far ``c`` is from the nearest point that lies in every outline; None if they share none."""
    p = nearest_point(c, outlines, tol)
    return None if p is None else fs.hypot(c[0] - p[0], c[1] - p[1])


def overlap(outlines: Iterable[Outline], tol: float = TOL) -> bool:
    """Whether the outlines share a point."""
    listed = list(outlines)
    return nearest_common(listed[0].centre, listed, tol) is not None


# ----------------------------------------------------------------------
# Profiles: where a side is, crossing it, and the material under a turned end
# ----------------------------------------------------------------------
def _at(side: Piece, t: float) -> Point:
    """The point a fraction ``t`` along a side (an arc: along its sweep)."""
    if isinstance(side, Segment):
        return (
            side.a[0] + t * (side.b[0] - side.a[0]),
            side.a[1] + t * (side.b[1] - side.a[1]),
        )
    return side.at(side.start + t * side.sweep)


def _param(side: Piece, p: Point) -> float:
    """How far along a side a point of it is, as a fraction."""
    if isinstance(side, Segment):
        dx, dy = side.b[0] - side.a[0], side.b[1] - side.a[1]
        length2 = dx * dx + dy * dy
        return (
            0.0
            if length2 == 0.0
            else min(
                max(((p[0] - side.a[0]) * dx + (p[1] - side.a[1]) * dy) / length2, 0.0),
                1.0,
            )
        )
    turned = (
        fs.atan2(p[1] - side.centre[1], p[0] - side.centre[0]) - side.start
    ) % _TURN
    if turned > side.sweep + TOL / side.radius:
        turned = 0.0 if _TURN - turned < turned - side.sweep else side.sweep
    return min(turned / side.sweep, 1.0)


def _runs(side: Piece, axis: int) -> list[tuple[Point, Point, float]]:
    """A side as runs each monotone along ``axis`` (0: the first coordinate), each with its arc's sign across (0 for a straight one)."""
    if isinstance(side, Segment):
        return [(side.a, side.b, 0.0)]
    # An arc runs back along the second axis at its top and bottom, along the first at its far left and right.
    turns = (math.pi / 2, 3 * math.pi / 2) if axis == 1 else (0.0, math.pi)
    stops = {0.0, side.sweep}
    for angle in turns:
        for k in range(-2, 3):
            d = angle + k * _TURN - side.start
            if 1e-12 < d < side.sweep - 1e-12:
                stops.add(d)
    found = []
    ordered = sorted(stops)
    for a, b in pairwise(ordered):
        middle = side.start + (a + b) / 2
        sign = fs.cos(middle) if axis == 1 else fs.sin(middle)
        found.append(
            (
                side.at(side.start + a),
                side.at(side.start + b),
                1.0 if sign >= 0 else -1.0,
            )
        )
    return found


def _across(side: Piece, run: tuple[Point, Point, float], axis: int, v: float) -> float:
    """Where a run is across ``axis`` where its coordinate along it is ``v``."""
    (p0, p1, sign) = run
    other = 1 - axis
    if isinstance(side, Segment):
        if p1[axis] == p0[axis]:
            return p0[other]
        return p0[other] + (v - p0[axis]) * (p1[other] - p0[other]) / (
            p1[axis] - p0[axis]
        )
    d = v - side.centre[axis]
    return side.centre[other] + sign * math.sqrt(
        max(side.radius * side.radius - d * d, 0.0)
    )


def _crossed(sides: Sequence[Piece], p: Point) -> int:
    """How many times a ray from ``p`` along the first axis crosses the sides (each run counted once, by its ends' sides of the ray)."""
    count = 0
    for side in sides:
        for run in _runs(side, 1):
            y0, y1 = run[0][1], run[1][1]
            if (y0 > p[1]) != (y1 > p[1]) and _across(side, run, 1, p[1]) > p[0]:
                count += 1
    return count


def _column(sides: Sequence[Piece], rho: float, height: float, top: bool) -> float:
    """How far the line at ``rho`` from the axis runs in a half outline from ``height``, down (``top``) or up."""
    found = []
    for side in sides:
        for run in _runs(side, 0):
            lo, hi = sorted((run[0][0], run[1][0]))
            if hi - lo <= 1e-12:
                if abs(rho - lo) <= TOL:
                    found += [run[0][1], run[1][1]]
            elif lo - TOL <= rho <= hi + TOL:
                found.append(_across(side, run, 0, min(max(rho, lo), hi)))
    if top:
        return min((height - z for z in found if z < height - 1e-9), default=0.0)
    return min((z - height for z in found if z > height + 1e-9), default=0.0)


def turned_range(section: Outline, height: float, top: bool, near: float, far: float,
                 extra: float = 0.0) -> tuple[float, float]:  # fmt: skip
    """The least and most material under a turned part's end at ``height``, between ``near`` and ``far`` from its axis.

    ``section`` is the half outline (distance from the axis, height). The
    material at a distance is along the line there, from the end to where it
    first leaves the outline, and ``extra`` more where it runs right through
    to the other end (what the part stands on). Between the sides' ends and
    the arcs' turning points it changes along one side, steadily: so it is
    asked just inside each run between them, a billionth of the run in.
    """
    sides = section.pieces()
    whole = 2 * section.half[1]
    stops = {near, far}
    for side in sides:
        stops.update(p[0] for p in side.ends())
        if isinstance(side, Arc):
            stops.update(p[0] for p in side.quarters())
            stops.add(side.centre[0])

    def total(rho: float) -> float:
        d = _column(sides, rho, height, top)
        return d + (extra if extra and d >= whole - 1e-9 else 0.0)

    at = sorted(r for r in stops if near <= r <= far)
    if len(at) < 2 or at[-1] - at[0] <= 1e-12:
        found = [total(near)]
    else:
        found = []
        for a, b in pairwise(at):
            if b - a > 1e-12:
                found += [total(a + 1e-9 * (b - a)), total(b - 1e-9 * (b - a))]
    return min(found), max(found)
