"""An outline of lines and arcs as convex pieces, exactly (docs/V2-stage4.md, 6.6).

The oracle makes an extrusion and a revolution from solids it knows, each
convex: so a profile (:meth:`forge_checks.outlines.Outline.profile`) is
taken apart into

- **polygons**: the polygon through the ends of its sides (its arcs replaced
  by their chords), cut into convex pieces: ears clipped, then joined again
  wherever two pieces sharing a cut stay convex;
- **bulges**: for each arc, the region between it and its chord (a disc
  meeting the half-plane on the arc's side of the chord). One the outline
  holds is added to the polygons; one it doesn't is taken from them.

That is exact once no bulge holds anything else of the outline, nor any
other bulge: each arc is split in halves until its bulge holds no point of
another side, nor touches one but at its own ends (and no arc sweeps more
than a quarter turn). The polygon is then simple (two chords that crossed
would each enter the other's bulge, through a side), and each bulge lies
wholly in the polygon or wholly out of it, wholly in the outline or wholly
out of it.

>>> from forge_checks.outlines import Arc, Outline, Segment
>>> import math
>>> stadium = Outline.profile([Segment((-10, -10), (10, -10)), Arc((10, 0), 10, -math.pi / 2, math.pi),
...                            Segment((10, 10), (-10, 10)), Arc((-10, 0), 10, math.pi / 2, math.pi)])
>>> pieces = convex_pieces(stadium)
>>> len(pieces.bulges), all(b.adds for b in pieces.bulges)
(4, True)
>>> round(pieces.area(), 9) == round(400 + math.pi * 100, 9)
True
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from forge_numeric import scalar as fs

from .outlines import Arc, Outline, Segment, crossings

__all__ = ["Bulge", "ConvexError", "Pieces", "Side", "convex_pieces", "sides_in_turn"]

Point = tuple[float, float]

#: Points this close are one (mm).
SAME = 1e-9
#: The most times an arc is halved before the outline is taken to touch itself.
DEEPEST = 30


class ConvexError(ValueError):
    """The outline can't be taken apart: it crosses or touches itself, or has no area."""


@dataclass(frozen=True)
class Bulge:
    """The region between an arc and its chord from ``a`` to ``b``; ``adds``: the outline holds it."""

    arc: Arc
    a: Point
    b: Point
    adds: bool

    @property
    def outward(self) -> Point:
        """The unit normal of the chord toward the arc."""
        (ax, ay), (bx, by) = self.a, self.b
        length = fs.hypot(bx - ax, by - ay)
        nx, ny = -(by - ay) / length, (bx - ax) / length
        mid = self.arc.at(self.arc.start + self.arc.sweep / 2)
        if (mid[0] - ax) * nx + (mid[1] - ay) * ny < 0:
            nx, ny = -nx, -ny
        return (nx, ny)

    def area(self) -> float:
        r, sweep = self.arc.radius, self.arc.sweep
        return r * r * (sweep - fs.sin(sweep)) / 2


@dataclass(frozen=True)
class Pieces:
    """A profile as convex polygons (each anticlockwise, turning left at every corner) and bulges."""

    polygons: tuple[tuple[Point, ...], ...]
    bulges: tuple[Bulge, ...]

    def area(self) -> float:
        found = sum(_signed_area(p) for p in self.polygons)
        return found + sum(b.area() if b.adds else -b.area() for b in self.bulges)


# ----------------------------------------------------------------------
# The outline's sides in the order they run
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class Side:
    """A side as it runs, from ``a`` to ``b``; an arc's ``arc`` (anticlockwise, whichever way it runs) and its depth of halving."""

    a: Point
    b: Point
    arc: Arc | None = None
    depth: int = 0


def _path(outline: Outline) -> list[Side]:
    """The profile's sides in turn, each from where the last ended: an arc's ends taken from its straight neighbours where it has them, exactly."""
    sides = outline.pieces()
    ends: list[list[Point]] = []
    for q in sides:
        if isinstance(q, Arc):
            whole = q.sweep >= 2 * math.pi - 1e-12
            first = q.at(q.start)
            ends.append([first, first] if whole else [first, q.at(q.start + q.sweep)])
        else:
            ends.append([q.a, q.b])
    n = len(sides)
    if n > 1:
        a, b = ends[0]
        if min(_dist(a, e) for e in ends[1]) < min(_dist(b, e) for e in ends[1]):
            ends[0] = [b, a]
        for k in range(1, n):
            start, end = ends[k]
            if _dist(end, ends[k - 1][1]) < _dist(start, ends[k - 1][1]):
                ends[k] = [end, start]
    # An arc's end, where a straight side meets it, is the side's (exact) end.
    for k in range(n):
        if isinstance(sides[k], Arc):
            for j, which in ((k - 1, 0), ((k + 1) % n, 1)):
                if (
                    not isinstance(sides[j], Arc)
                    and _dist(ends[k][which], ends[j][1 - which]) <= SAME
                ):
                    ends[k][which] = ends[j][1 - which]
    for k in range(n):  # where two arcs meet, the first's end is the second's start
        if _dist(ends[k][1], ends[(k + 1) % n][0]) > 1e-6:
            raise ConvexError("the outline's sides don't run end to end")
        ends[(k + 1) % n][0] = ends[k][1]
    found = []
    for q, (a, b) in zip(sides, ends, strict=True):
        found.append(Side(a, b, q if isinstance(q, Arc) else None))
    return found


def sides_in_turn(outline: Outline) -> list[Side]:
    """The profile's sides in turn, anticlockwise: each from where the last ended (an arc's ends its straight neighbours' own)."""
    path = _path(outline)
    if _path_area(path) >= 0:
        return path
    return [Side(s.b, s.a, s.arc, s.depth) for s in reversed(path)]


def _halves(side: Side) -> list[Side]:
    """An arc side halved, the halves in the order the side runs."""
    arc = side.arc
    assert arc is not None
    half = arc.sweep / 2
    first, second = (
        Arc(arc.centre, arc.radius, arc.start, half),
        Arc(arc.centre, arc.radius, arc.start + half, half),
    )
    mid = arc.at(arc.start + half)
    if _dist(side.a, arc.at(arc.start)) > _dist(side.a, arc.at(arc.start + arc.sweep)):
        first, second = second, first  # it runs clockwise
    return [
        Side(side.a, mid, first, side.depth + 1),
        Side(mid, side.b, second, side.depth + 1),
    ]


# ----------------------------------------------------------------------
# Splitting the arcs
# ----------------------------------------------------------------------
def _piece(side: Side) -> Segment | Arc:
    return side.arc if side.arc is not None else Segment(side.a, side.b)


def _in_bulge(p: Point, side: Side) -> bool:
    """Whether ``p`` is strictly inside the bulge of an arc side (by more than :data:`SAME`)."""
    arc = side.arc
    assert arc is not None
    if _dist(p, arc.centre) >= arc.radius - SAME:
        return False
    bulge = Bulge(arc, side.a, side.b, True)
    nx, ny = bulge.outward
    return (p[0] - side.a[0]) * nx + (p[1] - side.a[1]) * ny > SAME


def _holds(side: Side, other: Side) -> bool:
    """Whether an arc side's bulge holds or touches any of another side, but at the arc's own ends.

    (No bulge then holds any of another: two that overlapped would each have
    the other's arc, or its chord, in it, and a chord in a bulge brings its
    arc's ends or the arc itself.)
    """
    arc = side.arc
    assert arc is not None
    q = _piece(other)
    chord = Segment(side.a, side.b)
    for p in crossings(q, arc) + crossings(q, chord):
        if _dist(p, side.a) > SAME and _dist(p, side.b) > SAME:
            return True
    return _in_bulge(other.a, side) or _in_bulge(
        other.b, side
    )  # crossing nothing, it is all in or all out


def _split(path: list[Side]) -> list[Side]:
    """Every arc halved until it sweeps a quarter turn at most and its bulge holds nothing else."""
    found: list[Side] = []
    for side in path:
        pending = [side]
        while pending:
            s = pending.pop(0)
            if s.arc is not None and s.arc.sweep > math.pi / 2 + 1e-12:
                pending[:0] = _halves(s)
            else:
                found.append(s)
    changed = True
    while changed:
        changed = False
        for k, side in enumerate(found):
            if side.arc is None:
                continue
            if any(_holds(side, other) for j, other in enumerate(found) if j != k):
                if side.depth >= DEEPEST:
                    raise ConvexError("the outline touches or crosses itself near its arc about "
                                      f"({side.arc.centre[0]:g}, {side.arc.centre[1]:g})")  # fmt: skip
                found[k : k + 1] = _halves(side)
                changed = True
                break
    return found


# ----------------------------------------------------------------------
# The polygon of chords, in convex pieces
# ----------------------------------------------------------------------
def _dist(p: Point, q: Point) -> float:
    return fs.hypot(p[0] - q[0], p[1] - q[1])


def _turn(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])


def _signed_area(points: Sequence[Point]) -> float:
    n = len(points)
    return (
        sum(
            points[k][0] * points[(k + 1) % n][1]
            - points[(k + 1) % n][0] * points[k][1]
            for k in range(n)
        )
        / 2
    )


def _plain(points: list[Point], eps: float) -> list[Point]:
    """The polygon without repeated corners or corners on a straight run."""
    changed = True
    while changed and len(points) >= 3:
        changed = False
        n = len(points)
        for k in range(n):
            a, b, c = points[k - 1], points[k], points[(k + 1) % n]
            straight = (
                abs(_turn(a, b, c)) <= eps
                and (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1]) >= 0
            )
            if _dist(a, b) <= SAME or straight:
                del points[k]
                changed = True
                break
    return points


def _in_triangle(p: Point, a: Point, b: Point, c: Point, eps: float) -> bool:
    """Whether ``p`` is in the anticlockwise triangle, or on it (but at its corners)."""
    if min(_dist(p, a), _dist(p, b), _dist(p, c)) <= SAME:
        return False
    return _turn(a, b, p) >= -eps and _turn(b, c, p) >= -eps and _turn(c, a, p) >= -eps


def _ears(points: list[Point], eps: float) -> list[list[int]]:
    """The anticlockwise simple polygon as triangles, by their corners' numbers: an ear clipped at a time."""
    left = list(range(len(points)))
    found: list[list[int]] = []
    while len(left) > 3:
        for k in range(len(left)):
            i, j, m = left[k - 1], left[k], left[(k + 1) % len(left)]
            a, b, c = points[i], points[j], points[m]
            turn = _turn(a, b, c)
            if (
                abs(turn) <= eps
                and (b[0] - a[0]) * (c[0] - b[0]) + (b[1] - a[1]) * (c[1] - b[1]) >= 0
            ):
                del left[k]  # a corner on a straight run: no triangle
                break
            if turn <= eps:
                continue
            if any(
                _in_triangle(points[x], a, b, c, eps)
                for x in left
                if x not in (i, j, m)
            ):
                continue
            found.append([i, j, m])
            del left[k]
            break
        else:
            raise ConvexError(
                "the outline's polygon of chords has no ear: it crosses itself"
            )
    if len(left) == 3 and _turn(*(points[x] for x in left)) > eps:
        found.append(left)
    return found


def _convex(points: Sequence[Point], eps: float) -> bool:
    n = len(points)
    return n >= 3 and all(
        _turn(points[k - 1], points[k], points[(k + 1) % n]) > eps for k in range(n)
    )


def _joined(
    pieces: list[list[int]], points: list[Point], eps: float
) -> list[list[int]]:
    """Pieces sharing a cut joined wherever the two together stay convex (Hertel and Mehlhorn)."""
    alive = dict(enumerate(pieces))
    owner: dict[tuple[int, int], int] = {}
    for k, p in alive.items():
        for n in range(len(p)):
            owner[(p[n], p[(n + 1) % len(p)])] = k
    for i, j in [e for e in owner if e[0] < e[1] and (e[1], e[0]) in owner]:
        kept, gone = owner.get((i, j)), owner.get((j, i))
        if kept is None or gone is None or kept == gone:
            continue
        a, b = alive[kept], alive[gone]
        start = a.index(j)
        from_j = a[start:] + a[:start]  # j ... i
        start = b.index(i)
        from_i = b[start:] + b[:start]  # i ... j
        merged = from_j[:-1] + from_i[:-1]
        if not _convex([points[x] for x in merged], eps):
            continue
        del alive[gone]
        alive[kept] = merged
        for n in range(len(merged)):
            owner[(merged[n], merged[(n + 1) % len(merged)])] = kept
        owner.pop((i, j), None)
        owner.pop((j, i), None)
    return list(alive.values())


def convex_pieces(outline: Outline) -> Pieces:
    """The profile as convex polygons and bulges (see the module's docstring)."""
    if outline.shape != "profile":
        raise ConvexError(f"a {outline.shape} is no outline of sides")
    path = _split(_path(outline))
    size = max(max(outline.half), 1.0)
    eps = 1e-12 * size * size
    points = _plain([s.a for s in path], eps)
    polygons: list[tuple[Point, ...]] = []
    if len(points) >= 3:
        if _signed_area(points) < 0:
            points.reverse()
        for piece in _joined(_ears(points, eps), points, eps):
            corners = [points[x] for x in piece]
            if not _convex(corners, eps):
                raise ConvexError("a piece of the outline's polygon is not convex")
            polygons.append(tuple(corners))
    bulges = []
    for side in path:
        if (
            side.arc is not None
        ):  # the outline holds the bulge when it holds a point in it
            mid = side.arc.at(side.arc.start + side.arc.sweep / 2)
            chord_mid = ((side.a[0] + side.b[0]) / 2, (side.a[1] + side.b[1]) / 2)
            within = ((mid[0] + chord_mid[0]) / 2, (mid[1] + chord_mid[1]) / 2)
            bulges.append(
                Bulge(side.arc, side.a, side.b, outline.signed_distance(within) < 0)
            )
    found = Pieces(tuple(polygons), tuple(bulges))
    area = abs(_path_area(path))
    if abs(found.area() - area) > 1e-9 * max(area, 1.0):
        raise ConvexError(
            f"the pieces' area {found.area():.12g} isn't the outline's {area:.12g}"
        )
    return found


def _path_area(path: Sequence[Side]) -> float:
    """The outline's signed area, by Green's theorem: each side's share of the integral of (x dy - y dx) / 2."""
    found = 0.0
    for side in path:
        (ax, ay), (bx, by) = side.a, side.b
        if side.arc is None:
            found += (ax * by - bx * ay) / 2
            continue
        arc = side.arc
        sweep = arc.sweep
        if _dist(side.a, arc.at(arc.start)) > _dist(
            side.a, arc.at(arc.start + arc.sweep)
        ):
            sweep = -sweep  # it runs clockwise
        cx, cy = arc.centre
        found += (arc.radius * arc.radius * sweep + cx * (by - ay) - cy * (bx - ax)) / 2
    return found
