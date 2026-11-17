"""Outlines of lines and arcs, as the placement solver reasons with them (extrusion.md, revolution.md; docs/V2-stage4.md, 6.6).

An extrusion's or a revolution's ``profile`` is a closed outline: a start,
then each piece a straight line to a point or an arc about a centre to a
point (anticlockwise unless ``clockwise``; an arc back to where it starts is
a whole circle). Here it is a :class:`Shape` of :class:`Line` and
:class:`Arc` pieces, and everything asked of it is answered exactly, from
closed forms, never by sampling:

- **inside**, by the crossing rule: a ray along the first axis, each line
  crossed where it is, each arc split where it turns back along the second
  axis, so every piece is crossed at most once and an end is counted on one
  side only; the **signed distance**, the nearest piece's distance,
  negative inside;
- **its box** (the pieces' ends and the arcs' points furthest along each
  axis) and **its area** (Green's theorem: each line's and each arc's share);
- **where two pieces meet**, exactly (line and line, line and circle, circle
  and circle);
- **within**: whether a convex footprint (a rectangle or a disc, the parts
  every outline Forge places is made of) lies in it, and whether it lies
  in a face (:func:`boundary_within`): its boundary split where it meets
  the face's, and each stretch's ends and middle on the face; a simple
  outline whose boundary lies in a simple region lies in it;
- **the material under a revolution's end** (:func:`turned_depth`): from
  the end down the line at a distance from the axis to where it first
  leaves the outline.

This is the solver's own code: the judge and the generator have theirs
(rule R2).

>>> L = Shape.of((0.0, 0.0), [((30.0, 0.0), None, False), ((30.0, 5.0), None, False),
...     ((5.0, 5.0), None, False), ((5.0, 20.0), None, False), ((0.0, 20.0), None, False),
...     ((0.0, 0.0), None, False)])
>>> L.contains((2.0, 10.0)), L.contains((10.0, 10.0)), L.box(), L.area()
(True, False, ((0.0, 0.0), (30.0, 20.0)), 225.0)
>>> L.holds_rect((15.0, 2.5), (2.0, 2.0)), L.holds_rect((15.0, 2.5), (2.0, 3.0))
(True, False)
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING

from forge_numeric import scalar as fs

if TYPE_CHECKING:
    from .draft import Profile

__all__ = [
    "TOL",
    "Arc",
    "Line",
    "Piece",
    "Shape",
    "boundary_within",
    "corners",
    "meet",
    "runs_on",
    "sizes",
    "turned_depth",
    "turned_extremes",
    "turned_rims",
]

Point = tuple[float, float]
#: A piece as a profile writes it: where it goes, an arc's centre (None for a line), and whether it turns clockwise.
Segment = tuple[Point, Point | None, bool]

#: A point this close to an outline is on it (mm).
TOL = 1e-9
_TURN = 2 * math.pi


@dataclass(frozen=True)
class Line:
    """A straight piece, from ``a`` to ``b``."""

    a: Point
    b: Point

    def at(self, t: float) -> Point:
        return (
            self.a[0] + t * (self.b[0] - self.a[0]),
            self.a[1] + t * (self.b[1] - self.a[1]),
        )

    def ends(self) -> tuple[Point, Point]:
        return self.a, self.b

    def distance(self, p: Point) -> float:
        (ax, ay), (bx, by) = self.a, self.b
        dx, dy = bx - ax, by - ay
        length2 = dx * dx + dy * dy
        t = (
            0.0
            if length2 == 0.0
            else min(max(((p[0] - ax) * dx + (p[1] - ay) * dy) / length2, 0.0), 1.0)
        )
        q = self.at(t)
        return fs.hypot(p[0] - q[0], p[1] - q[1])

    def param(self, p: Point) -> float:
        """How far along the line a point of it is (0 at ``a``, 1 at ``b``)."""
        dx, dy = self.b[0] - self.a[0], self.b[1] - self.a[1]
        length2 = dx * dx + dy * dy
        return (
            0.0
            if length2 == 0.0
            else ((p[0] - self.a[0]) * dx + (p[1] - self.a[1]) * dy) / length2
        )

    def extremes(self) -> list[Point]:
        return [self.a, self.b]

    def area_share(self) -> float:
        """Its share of the outline's signed area: ½ ∮ (x dy - y dx)."""
        return 0.5 * (self.a[0] * self.b[1] - self.b[0] * self.a[1])


@dataclass(frozen=True)
class Arc:
    """A circular piece: from angle ``start`` (radians) turning ``sweep`` (anticlockwise positive; ±2π a whole circle)."""

    centre: Point
    radius: float
    start: float
    sweep: float

    def at(self, t: float) -> Point:
        angle = self.start + t * self.sweep
        return (
            self.centre[0] + self.radius * fs.cos(angle),
            self.centre[1] + self.radius * fs.sin(angle),
        )

    def ends(self) -> tuple[Point, Point]:
        return self.at(0.0), self.at(1.0)

    @property
    def whole(self) -> bool:
        return abs(self.sweep) >= _TURN - 1e-12

    def fraction(self, angle: float) -> float | None:
        """Where on the arc the circle's point at ``angle`` is (0 to 1), or None when it isn't on it."""
        turned = ((angle - self.start) * (1.0 if self.sweep > 0 else -1.0)) % _TURN
        span = abs(self.sweep)
        slack = TOL / self.radius
        if self.whole:
            return turned / span
        if turned <= span + slack:
            return min(turned / span, 1.0)
        if _TURN - turned <= slack:
            return 0.0
        return None

    def distance(self, p: Point) -> float:
        dx, dy = p[0] - self.centre[0], p[1] - self.centre[1]
        far = fs.hypot(dx, dy)
        if far > 0.0 and self.fraction(fs.atan2(dy, dx)) is not None:
            return abs(far - self.radius)
        if far == 0.0:
            return self.radius
        return min(fs.hypot(p[0] - q[0], p[1] - q[1]) for q in self.ends())

    def param(self, p: Point) -> float:
        found = self.fraction(fs.atan2(p[1] - self.centre[1], p[0] - self.centre[0]))
        return 0.0 if found is None else found

    def turning(self, angles: Iterable[float]) -> list[float]:
        """The fractions along the arc, strictly between its ends, of the circle's points at these angles (each turn round)."""
        found = set()
        for angle in angles:
            for k in range(-2, 3):
                t = (angle + k * _TURN - self.start) / self.sweep
                if 1e-12 < t < 1 - 1e-12:
                    found.add(t)
        return sorted(found)

    def extremes(self) -> list[Point]:
        """Its ends, and its points furthest along either axis either way."""
        return [
            *self.ends(),
            *(self.at(t) for t in self.turning(k * math.pi / 2 for k in range(4))),
        ]

    def area_share(self) -> float:
        """Its share of the outline's signed area: ½ ∮ (x dy - y dx), in closed form."""
        cx, cy = self.centre
        r, a0, a1 = self.radius, self.start, self.start + self.sweep
        return 0.5 * (
            r * r * self.sweep
            + cx * r * (fs.sin(a1) - fs.sin(a0))
            - cy * r * (fs.cos(a1) - fs.cos(a0))
        )


Piece = Line | Arc


def _pieces(
    start: Point, segments: Sequence[tuple[Point, Point | None, bool]]
) -> tuple[Piece, ...]:
    found: list[Piece] = []
    here = start
    for to, centre, clockwise in segments:
        if centre is None:
            found.append(Line(here, to))
        else:
            a0 = fs.atan2(here[1] - centre[1], here[0] - centre[0])
            a1 = fs.atan2(to[1] - centre[1], to[0] - centre[0])
            sweep = ((a0 - a1) if clockwise else (a1 - a0)) % _TURN
            if sweep <= 1e-12:
                sweep = _TURN  # an arc back to where it starts is a whole circle
            radius = fs.hypot(here[0] - centre[0], here[1] - centre[1])
            found.append(Arc(centre, radius, a0, -sweep if clockwise else sweep))
        here = to
    return tuple(found)


@dataclass(frozen=True)
class Shape:
    """A closed outline of lines and arcs, in a face's (or a half-plane's) two coordinates."""

    pieces: tuple[Piece, ...]

    @classmethod
    def of(
        cls, start: Point, segments: Sequence[Segment], at: Point = (0.0, 0.0)
    ) -> Shape:
        """An outline from its start and its segments, each ``(to, centre or None, clockwise)``, moved by ``at``."""

        def move(p: Point) -> Point:
            return (p[0] + at[0], p[1] + at[1])

        return cls(_pieces(move(start), [(move(to), None if centre is None else move(centre), bool(clockwise))
                                         for to, centre, clockwise in segments]))  # fmt: skip

    @classmethod
    def disc(cls, centre: Point, radius: float) -> Shape:
        """A disc: one arc, all the way round."""
        return cls((Arc(centre, radius, 0.0, _TURN),))

    @classmethod
    def rect(
        cls,
        centre: Point,
        half: Point,
        corners: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
    ) -> Shape:
        """A rectangle along the axes, each corner rounded by its radius (by quadrant: (+, +), (-, +), (-, -), (+, -)), anticlockwise."""
        c1, c2 = centre
        h1, h2 = half
        r1, r2, r3, r4 = corners
        x0, x1, y0, y1 = c1 - h1, c1 + h1, c2 - h2, c2 + h2
        straight = (Line((x1 - r1, y1), (x0 + r2, y1)), Line((x0, y1 - r2), (x0, y0 + r3)),
                    Line((x0 + r3, y0), (x1 - r4, y0)), Line((x1, y0 + r4), (x1, y1 - r1)))  # fmt: skip
        found: list[Piece] = []
        for k, (s1, s2) in enumerate(((1, 1), (-1, 1), (-1, -1), (1, -1))):
            r = corners[k]
            if r > 0:
                found.append(
                    Arc(
                        (c1 + s1 * (h1 - r), c2 + s2 * (h2 - r)),
                        r,
                        k * math.pi / 2,
                        math.pi / 2,
                    )
                )
            side = straight[k]
            if side.a != side.b:
                found.append(side)
        return cls(tuple(found))

    @classmethod
    def of_profile(cls, profile: Profile, at: Point = (0.0, 0.0)) -> Shape:
        """A spec's ``Profile`` (forge_spec.draft) as an outline, moved by ``at``."""
        return cls.of(
            profile.start, [(s.to, s.centre, s.clockwise) for s in profile.segments], at
        )

    def moved(self, d1: float, d2: float) -> Shape:
        def move(p: Point) -> Point:
            return (p[0] + d1, p[1] + d2)

        return Shape(tuple(Line(move(q.a), move(q.b)) if isinstance(q, Line)
                           else Arc(move(q.centre), q.radius, q.start, q.sweep) for q in self.pieces))  # fmt: skip

    def turned(self, c: float, s: float) -> Shape:
        """The outline turned about the origin, by the angle whose cosine and sine are ``c`` and ``s`` (1b's ``turn``)."""

        def turn(p: Point) -> Point:
            return (c * p[0] - s * p[1], s * p[0] + c * p[1])

        angle = fs.atan2(s, c)
        return Shape(tuple(Line(turn(q.a), turn(q.b)) if isinstance(q, Line)
                           else Arc(turn(q.centre), q.radius, q.start + angle, q.sweep) for q in self.pieces))  # fmt: skip

    def swapped(self) -> Shape:
        """The outline with its two coordinates swapped: seen from a face that names the same two axes the other way round."""

        def swap(p: Point) -> Point:
            return (p[1], p[0])

        return Shape(tuple(Line(swap(q.a), swap(q.b)) if isinstance(q, Line)
                           else Arc(swap(q.centre), q.radius, math.pi / 2 - q.start, -q.sweep) for q in self.pieces))  # fmt: skip

    # --- its box and area --------------------------------------------------------------
    def box(self) -> tuple[Point, Point]:
        points = [p for q in self.pieces for p in q.extremes()]
        return (min(p[0] for p in points), min(p[1] for p in points)), (max(p[0] for p in points),
                                                                        max(p[1] for p in points))  # fmt: skip

    def signed_area(self) -> float:
        return sum(q.area_share() for q in self.pieces)

    def area(self) -> float:
        return abs(self.signed_area())

    # --- inside, and how far ----------------------------------------------------------
    def inside(self, p: Point) -> bool:
        """Whether ``p`` is inside, by the crossing rule (a point on the outline may go either way: use :meth:`contains`)."""
        crossed = 0
        for q in self.pieces:
            for (_, y0), (_, y1), x_at in _monotone(q, 1):
                if (y0 > p[1]) != (y1 > p[1]) and x_at(p[1]) > p[0]:
                    crossed += 1
        return crossed % 2 == 1

    def distance(self, p: Point) -> float:
        """How far ``p`` is from the outline itself."""
        return min(q.distance(p) for q in self.pieces)

    def signed_distance(self, p: Point) -> float:
        d = self.distance(p)
        return -d if self.inside(p) else d

    def contains(self, p: Point, tol: float = TOL) -> bool:
        """Whether ``p`` is in the closed outline (within ``tol`` of it counts)."""
        return self.distance(p) <= tol or self.inside(p)

    # --- what lies in it --------------------------------------------------------------
    def holds_disc(self, centre: Point, radius: float, tol: float = TOL) -> bool:
        """Whether a disc (a point when ``radius`` is 0) lies in the outline."""
        return self.contains(centre, tol) and (radius <= 0.0 or (self.inside(centre)
                                                                 and self.distance(centre) >= radius - tol))  # fmt: skip

    def holds_rect(self, centre: Point, half: Point, tol: float = TOL) -> bool:
        """Whether a rectangle (along the axes, sharp-cornered) lies in the outline.

        A convex footprint lies in a simple outline when a point of it does
        and no piece of the outline enters it: each piece's ends are not
        inside it, nor the middle of any stretch of the piece between two of
        the points where it meets the rectangle's sides.
        """
        if not self.contains(centre, tol):
            return False
        c1, c2 = centre
        h1, h2 = half

        def deep(p: Point) -> bool:  # inside the rectangle by more than the tolerance
            return abs(p[0] - c1) < h1 - tol and abs(p[1] - c2) < h2 - tol

        corners = [
            (c1 + s1 * h1, c2 + s2 * h2)
            for s1, s2 in ((1, 1), (-1, 1), (-1, -1), (1, -1))
        ]
        sides = [Line(corners[k], corners[(k + 1) % 4]) for k in range(4)]
        for q in self.pieces:
            if any(deep(p) for p in q.ends()):
                return False
            cuts = sorted(
                {0.0, 1.0, *(q.param(x) for side in sides for x in meet(q, side))}
            )
            if any(deep(q.at((a + b) / 2)) for a, b in pairwise(cuts) if b - a > 1e-12):
                return False
        return True


# ----------------------------------------------------------------------
# Pieces split where they turn back, and where two meet
# ----------------------------------------------------------------------
def _monotone(
    q: Piece, axis: int
) -> list[tuple[Point, Point, Callable[[float], float]]]:
    """The piece in stretches each monotone along ``axis`` (1: the second coordinate), each with its other coordinate at a given value of that one."""
    other = 1 - axis
    if isinstance(q, Line):
        a, b = q.a, q.b

        def on_line(v: float) -> float:
            if b[axis] == a[axis]:
                return a[other]
            return a[other] + (v - a[axis]) * (b[other] - a[other]) / (
                b[axis] - a[axis]
            )

        return [(a, b, on_line)]
    # An arc turns back along the second axis at its top and bottom (along the first: at its far left and right).
    turns = q.turning((math.pi / 2, 3 * math.pi / 2) if axis == 1 else (0.0, math.pi))
    cuts = [0.0, *turns, 1.0]
    found: list[tuple[Point, Point, Callable[[float], float]]] = []
    for t0, t1 in pairwise(cuts):
        p0, p1 = q.at(t0), q.at(t1)
        middle = q.start + (t0 + t1) / 2 * q.sweep
        side = fs.cos(middle) if axis == 1 else fs.sin(middle)
        sign = 1.0 if side >= 0 else -1.0
        cx, cy = q.centre

        def on_arc(
            v: float, sign: float = sign, c: Point = (cx, cy), r: float = q.radius
        ) -> float:
            d = v - c[axis]
            return c[other] + sign * math.sqrt(max(r * r - d * d, 0.0))

        found.append((p0, p1, on_arc))
    return found


def meet(p: Piece, q: Piece) -> list[Point]:
    """Where two pieces meet (touching included; where they overlap along a line, the overlap's ends)."""
    if isinstance(p, Line) and isinstance(q, Line):
        return _line_line(p, q)
    if isinstance(p, Line) and isinstance(q, Arc):
        return _line_arc(p, q)
    if isinstance(p, Arc) and isinstance(q, Line):
        return _line_arc(q, p)
    assert isinstance(p, Arc) and isinstance(q, Arc)
    return _arc_arc(p, q)


def _line_line(p: Line, q: Line) -> list[Point]:
    (ax, ay), (bx, by) = p.a, p.b
    (cx, cy), (dx, dy) = q.a, q.b
    rx, ry, sx, sy = bx - ax, by - ay, dx - cx, dy - cy
    denom = rx * sy - ry * sx
    scale = max(1.0, *(abs(v) for v in (ax, ay, bx, by, cx, cy, dx, dy)))
    if abs(denom) <= 1e-12 * scale * scale:
        # Parallel: where they lie along one line, the ends of their overlap.
        if (
            q.distance(p.a) > TOL
            and q.distance(p.b) > TOL
            and p.distance(q.a) > TOL
            and p.distance(q.b) > TOL
        ):
            return []
        return [
            x
            for x in (p.a, p.b, q.a, q.b)
            if p.distance(x) <= TOL and q.distance(x) <= TOL
        ]
    t = ((cx - ax) * sy - (cy - ay) * sx) / denom
    u = ((cx - ax) * ry - (cy - ay) * rx) / denom
    slack_t = TOL / max(fs.hypot(rx, ry), 1e-300)
    slack_u = TOL / max(fs.hypot(sx, sy), 1e-300)
    if -slack_t <= t <= 1 + slack_t and -slack_u <= u <= 1 + slack_u:
        return [p.at(min(max(t, 0.0), 1.0))]
    return []


def _line_arc(p: Line, q: Arc) -> list[Point]:
    (ax, ay), (bx, by) = p.a, p.b
    dx, dy = bx - ax, by - ay
    fx, fy = ax - q.centre[0], ay - q.centre[1]
    a = dx * dx + dy * dy
    b = 2 * (fx * dx + fy * dy)
    c = fx * fx + fy * fy - q.radius * q.radius
    disc = b * b - 4 * a * c
    if a == 0.0:
        return []
    # A line touching the circle (within the tolerance of its nearest point) meets it once there.
    t_near = -b / (2 * a)
    near = p.at(t_near)
    gap = fs.hypot(near[0] - q.centre[0], near[1] - q.centre[1]) - q.radius
    if disc < 0 and gap > TOL:
        return []
    roots = [t_near] if disc <= 0 or abs(gap) <= TOL * 1e-3 else [(-b - math.sqrt(disc)) / (2 * a),
                                                                    (-b + math.sqrt(disc)) / (2 * a)]  # fmt: skip
    slack = TOL / math.sqrt(a)
    found = []
    for t in roots:
        if -slack <= t <= 1 + slack:
            x = p.at(min(max(t, 0.0), 1.0))
            if q.fraction(fs.atan2(x[1] - q.centre[1], x[0] - q.centre[0])) is not None:
                found.append(x)
    return found


def _arc_arc(p: Arc, q: Arc) -> list[Point]:
    (x0, y0), r0 = p.centre, p.radius
    (x1, y1), r1 = q.centre, q.radius
    d = fs.hypot(x1 - x0, y1 - y0)
    if d <= TOL:
        if abs(r0 - r1) > TOL:
            return []
        # One circle: where the arcs overlap, their ends that lie on both.
        return [
            x
            for x in (*p.ends(), *q.ends())
            if p.distance(x) <= TOL and q.distance(x) <= TOL
        ]
    if d > r0 + r1 + TOL or d < abs(r0 - r1) - TOL:
        return []
    a = (r0 * r0 - r1 * r1 + d * d) / (2 * d)
    h = math.sqrt(max(r0 * r0 - a * a, 0.0))
    mx, my = x0 + a * (x1 - x0) / d, y0 + a * (y1 - y0) / d
    points = [(mx, my)] if h <= TOL else [(mx + h * (y1 - y0) / d, my - h * (x1 - x0) / d),
                                          (mx - h * (y1 - y0) / d, my + h * (x1 - x0) / d)]  # fmt: skip
    return [x for x in points if p.fraction(fs.atan2(x[1] - y0, x[0] - x0)) is not None
            and q.fraction(fs.atan2(x[1] - y1, x[0] - x1)) is not None]  # fmt: skip


def boundary_within(
    pieces: Sequence[Piece], holds: Callable[[Point], bool], walls: Sequence[Piece]
) -> bool:
    """Whether every point of ``pieces`` is in a region that ``holds`` says a point is in, whose boundary is ``walls``.

    Each piece is split where it meets a wall; between two such points it
    doesn't cross the boundary, so it is in or out all along: its ends and
    its middle are asked. A simple outline whose boundary lies in a simple
    region lies in it.
    """
    for q in pieces:
        cuts = sorted({0.0, 1.0, *(q.param(x) for w in walls for x in meet(q, w))})
        if not all(holds(q.at(t)) for t in cuts):
            return False
        if not all(
            holds(q.at((a + b) / 2)) for a, b in pairwise(cuts) if b - a > 1e-12
        ):
            return False
    return True


# ----------------------------------------------------------------------
# A revolution's ends, and the material under them
# ----------------------------------------------------------------------
def _turned_end(shape: Shape, top: bool) -> int | None:
    """Which piece is a revolution's end (revolution.md): the one straight piece across the axis at the greatest (least) height, with no other piece reaching that height but where it meets that one's ends."""
    (lo, hi) = shape.box()
    height = hi[1] if top else lo[1]
    flat = [n for n, q in enumerate(shape.pieces) if isinstance(q, Line) and abs(q.a[1] - height) <= TOL
            and abs(q.b[1] - height) <= TOL and abs(q.a[0] - q.b[0]) > TOL]  # fmt: skip
    if len(flat) != 1:
        return None
    end = shape.pieces[flat[0]]
    for q in shape.pieces:
        if q is end:
            continue
        for p in q.extremes():
            if abs(p[1] - height) <= TOL and not any(
                fs.hypot(p[0] - e[0], p[1] - e[1]) <= 1e-6 for e in end.ends()
            ):
                return None
    return flat[0]


def turned_extremes(shape: Shape, top: bool) -> tuple[float, float, float] | None:
    """A revolution's end, from its half outline (distance from the axis, height): (height, inner radius, outer radius), or None.

    The end is the one straight piece across the axis at the outline's
    greatest height (``top``) or least, with no other piece reaching that
    height but where it meets that one's ends.
    """
    found = _turned_end(shape, top)
    if found is None:
        return None
    end = shape.pieces[found]
    assert isinstance(end, Line)
    r0, r1 = sorted((end.a[0], end.b[0]))
    return end.a[1], max(r0, 0.0), r1


def _direction(q: Piece, at_end: bool) -> Point:
    """The way a piece runs at its start or its end, as a unit vector."""
    if isinstance(q, Line):
        dx, dy = q.b[0] - q.a[0], q.b[1] - q.a[1]
        length = fs.hypot(dx, dy)
        return dx / length, dy / length
    angle = q.start + (q.sweep if at_end else 0.0)
    turn = 1.0 if q.sweep > 0 else -1.0
    return -turn * fs.sin(angle), turn * fs.cos(angle)


def runs_on(before: Piece, after: Piece) -> bool:
    """Whether ``after`` leaves where ``before`` ends the way ``before`` arrives: they meet smoothly, with no edge (edges.md: an edge is where two faces meet at an angle).

    An outline never turns straight back (extrusion.md), so the other way
    round never comes up.
    """
    t_in, t_out = _direction(before, True), _direction(after, False)
    return t_in[0] * t_out[0] + t_in[1] * t_out[1] > 1.0 - 1e-9


def sizes(shape: Shape, *, turned: bool = False) -> tuple[list[float], set[int]]:
    """The sizes an outline has, exactly (docs/V2-stage4.md, 6.7), and the counts it has.

    Sizes: across it along each axis; each straight piece's length; the
    distance between two parallel straight pieces; between two of its points
    (its ends: its corners, and where arcs meet lines; and its arcs'
    centres), straight and along each of its axes (a lever's from its pivot
    to its far end's centre, a lug's along the bar and across it); each
    arc's radius and diameter.
    Turned (a revolution's half outline, its first coordinate the distance
    from the axis): its height, and the diameter of the circle each end and
    each arc's centre turns on, and its widest. Counts: how many pieces it
    has, and how many corners.

    >>> hexagon = Shape.of((10.0, 0.0), [((5.0, 8.660254), None, False), ((-5.0, 8.660254), None, False),
    ...     ((-10.0, 0.0), None, False), ((-5.0, -8.660254), None, False), ((5.0, -8.660254), None, False),
    ...     ((10.0, 0.0), None, False)])
    >>> found, counts = sizes(hexagon)
    >>> [any(abs(s - want) < 1e-5 for s in found) for want in (20.0, 17.320508, 10.0)], counts
    ([True, True, True], {6})
    >>> lever = Shape.of((5.0, -3.0), [((40.0, -3.0), None, False), ((40.0, 3.0), (40.0, 0.0), False),
    ...     ((5.0, 3.0), None, False), ((5.0, -3.0), (0.0, 0.0), False)])
    >>> [any(abs(s - want) < 1e-9 for s in sizes(lever)[0]) for want in (40.0, 35.0, 13.0)]  # pivot to far end
    [True, True, False]
    >>> ring, _ = sizes(Shape.disc((20.0, 0.0), 4.0), turned=True)
    >>> sorted({round(s, 6) for s in ring} & {8.0, 40.0, 48.0})
    [8.0, 40.0, 48.0]
    """
    (lo1, lo2), (hi1, hi2) = shape.box()
    found = [hi1 - lo1, hi2 - lo2]
    lines = [q for q in shape.pieces if isinstance(q, Line)]
    arcs = [q for q in shape.pieces if isinstance(q, Arc)]
    ends = [q.ends()[0] for q in shape.pieces]
    found += [fs.dist(q.a, q.b) for q in lines]
    found += [r for q in arcs for r in (q.radius, 2 * q.radius)]
    # An arc split in two (a circle's halves) has one centre: each is said once.
    points = [*ends, *dict.fromkeys(q.centre for q in arcs)]
    for n, p in enumerate(points):
        for q in points[n + 1 :]:
            found += [fs.dist(p, q), abs(p[0] - q[0]), abs(p[1] - q[1])]
    for n, one in enumerate(lines):
        dx, dy = one.b[0] - one.a[0], one.b[1] - one.a[1]
        length = fs.hypot(dx, dy)
        for other in lines[n + 1 :]:
            ex, ey = other.b[0] - other.a[0], other.b[1] - other.a[1]
            # Parallel to within a ten-thousandth of a radian (an outline written to a few figures): the
            # distance from the other's middle to the line through the one.
            if length > 0 and abs(dx * ey - dy * ex) <= 1e-4 * length * fs.hypot(
                ex, ey
            ):
                mx, my = (other.a[0] + other.b[0]) / 2, (other.a[1] + other.b[1]) / 2
                gap = abs((mx - one.a[0]) * dy - (my - one.a[1]) * dx) / length
                if gap > 0:
                    found.append(gap)
    if turned:
        found += [2 * hi1] + [2 * p[0] for p in ends] + [2 * q.centre[0] for q in arcs]
    return found, {len(shape.pieces), len(corners(shape))}


def corners(shape: Shape) -> list[Point]:
    """Where one piece of an outline meets the next at an angle: its corners, each an edge along an extrusion's length.

    >>> stadium = Shape.of((0.0, 0.0), [((10.0, 0.0), None, False), ((10.0, 4.0), (10.0, 2.0), False),
    ...     ((0.0, 4.0), None, False), ((0.0, 0.0), (0.0, 2.0), False)])
    >>> corners(stadium), len(corners(Shape.rect((0.0, 0.0), (2.0, 1.0), (0.5, 0.0, 0.0, 0.0))))
    ([], 3)
    """
    count = len(shape.pieces)
    return [
        q.ends()[1]
        for n, q in enumerate(shape.pieces)
        if not runs_on(q, shape.pieces[(n + 1) % count])
    ]


def turned_rims(shape: Shape, top: bool) -> list[float] | None:
    """The radii of a revolution's end's rims, where it meets the side next to it at an angle, off the axis; None when it has no flat end.

    A rim where the side runs on smoothly into the end is no edge.

    >>> knob = Shape.of((0.0, 0.0), [((4.0, 0.0), None, False), ((4.0, 2.0), None, False),
    ...     ((2.0, 4.0), (2.0, 2.0), False), ((0.0, 4.0), None, False), ((0.0, 0.0), None, False)])
    >>> turned_rims(knob, True), turned_rims(knob, False)
    ([], [4.0])
    """
    found = _turned_end(shape, top)
    if found is None:
        return None
    count = len(shape.pieces)
    end = shape.pieces[found]
    assert isinstance(end, Line)
    before, after = shape.pieces[(found - 1) % count], shape.pieces[(found + 1) % count]
    rims = []
    if end.a[0] > TOL and not runs_on(before, end):
        rims.append(end.a[0])
    if end.b[0] > TOL and not runs_on(end, after):
        rims.append(end.b[0])
    return sorted(rims, reverse=True)


def _down_from(shape: Shape, rho: float, height: float, top: bool) -> float:
    """How far the line at ``rho`` from the axis runs inside the outline from ``height`` (down from the top end, up from the bottom)."""
    crossings = []
    for q in shape.pieces:
        for (x0, y0), (x1, y1), y_at in _monotone(q, 0):
            lo, hi = min(x0, x1), max(x0, x1)
            if lo - TOL <= rho <= hi + TOL and hi - lo > 1e-12:
                crossings.append(y_at(min(max(rho, lo), hi)))
            elif hi - lo <= 1e-12 and abs(rho - lo) <= TOL:
                crossings += [y0, y1]
    if top:
        below = [height - y for y in crossings if y < height - 1e-9]
    else:
        below = [y - height for y in crossings if y > height + 1e-9]
    return min(below, default=0.0)


def turned_depth(
    shape: Shape, top: bool, near: float, far: float, extra: float = 0.0
) -> tuple[float, float]:
    """The least and the most material under a revolution's end over distances ``near`` to ``far`` from the axis.

    The material at a distance is from the end along the line there to
    where it first leaves the outline. Between the pieces' ends and the
    arcs' turning points it changes along one piece, monotonically, so the
    least and the most are at the ends of those stretches: each is taken
    just inside its stretch (a billionth of it in), where the line meets no
    corner and runs along no piece. Where the line runs right through (to
    the other end's height), ``extra`` is under it too (what the
    revolution stands on).
    """
    end = turned_extremes(shape, top)
    if end is None:
        return 0.0, 0.0
    height = end[0]
    (_, lo), (_, hi) = shape.box()
    whole = hi - lo

    def total(rho: float) -> float:
        d = _down_from(shape, rho, height, top)
        return d + (extra if extra and d >= whole - 1e-9 else 0.0)

    critical = {near, far}
    for q in shape.pieces:
        for p in q.extremes():
            critical.add(p[0])
        if isinstance(q, Arc):
            critical.add(q.centre[0])
    at = sorted(rho for rho in critical if near <= rho <= far)
    if len(at) < 2 or at[-1] - at[0] <= 1e-12:
        depths = [total(near)]
    else:
        depths = []
        for a, b in pairwise(at):
            if b - a > 1e-12:
                step = 1e-9 * (b - a)
                depths += [total(a + step), total(b - step)]
    return min(depths), max(depths)
