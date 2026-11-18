"""The generator's own shape model: where every copy of a generated spec's items is, and the solid the part is.

Written from the field definitions (docs/definitions), it shares no code with
the placement solver, the judge's placement or the oracle, and imports none
of them (rule R2, docs/V2-stage2.md section 9). It doesn't read specs: the
generator (:mod:`forge_eval.generator`) chooses each item's sizes and places
first, works out where the definitions put every copy, and writes the
fields that say so. This module is what it worked out, the part as the
definitions mean it; the solver and the judge, reading only the fields,
must land on it (the three placements tested against each other), and a
part built from it is a reference part that depends on neither.

A part is its **copies** (each item's point, direction and axes, as the
definitions give them: frame.md and place.md) and the **steps** it is made
in, in order (frame.md, "The order the part is made in"): each a solid
added or taken away. A solid is a **prism** (an outline in a plane, a
rectangle with its corners rounded, which makes discs and stadiums too, run
along the plane's normal between two levels), a **frustum** (a piece of a
cone, as a countersink is), an outline of straight sides and arcs **pushed**
along the normal of its plane (an extrusion), a half outline **turned**
about an axis (a revolution), or a prism **kept** between two planes across
another direction (an item leaning on its face: kept on the face's open
side, or within its material). Which side of the part a point is follows
from the steps alone (:meth:`Truth.inside`); an outline's inside is this
module's own (:class:`Outline2`).

Each step also says how far its solid may be carried on past each end
without changing the part, into air a cut opens onto or into the material a
standing item is joined to, so a mesh library can build the part without
two solids meeting in one plane (``reach``).
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cached_property, lru_cache

import numpy as np
from forge_numeric import scalar as fs
from forge_numeric import vector as fv
from numpy.typing import NDArray

__all__ = [
    "QUADRANTS",
    "Copy",
    "Corner",
    "Frustum",
    "Kept",
    "Letters",
    "Outline2",
    "Prism",
    "Pushed",
    "RingCorner",
    "Step",
    "Threaded",
    "Truth",
    "Turned",
    "bounds",
    "ink_box",
    "line_contours",
    "line_pieces",
    "unit_of",
]

Vec = tuple[float, float, float]
Array = NDArray[np.float64]

_AXES = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}
#: A rectangle's corners, in order: by the sign of each one's place along the first and the second direction.
QUADRANTS = ((1, 1), (-1, 1), (-1, -1), (1, -1))


def unit_of(name: str) -> Vec:
    """A frame direction by name: ``+x``, ``-z``; or a frame axis: ``x``."""
    sign = -1.0 if name[0] == "-" else 1.0
    v = _AXES[name[-1]]
    return (sign * v[0] + 0.0, sign * v[1] + 0.0, sign * v[2] + 0.0)


@dataclass(frozen=True)
class Copy:
    """One copy of one item, where the definitions put it.

    ``point``: a body's base centre, a feature's centre on the face it is on
    (round a side, the point of the side's surface); ``direction``: the way a
    body or standing feature grows, or the way the face a cut goes into
    faces; ``axes``: the frame axes its length and width run along, or None
    for a hole round a side; ``host``: the item, copy and face it is on.
    """

    item: str
    index: int
    host: tuple[str, int, str] | None
    point: Vec
    direction: Vec
    axes: tuple[str, str] | None
    #: Leaning on its flat face (tilt; place.md, "Leaning on the face"): the way it stands out or its way out of its
    #: mouth, its face's outward normal (``direction``) turned that far towards its lean.
    lean: Vec | None = None


@dataclass(frozen=True)
class Prism:
    """The points whose position in the plane through ``centre`` (along ``first`` and ``second``) lies within half sizes ``half``, the rectangle's ``rounded`` corners rounded to ``corner``, and whose height along ``normal`` is from ``low`` to ``high``.

    ``rounded`` names the corners in the order of :data:`QUADRANTS`. A disc
    is a square with its corners rounded to its half size; a stadium, a
    rectangle with them rounded to its half width; a round-ended tab seen
    along its thickness, a rectangle with its two far corners rounded to its
    half width (a half-disc, when it is half as long as it is wide). A
    rounded corner's quarter-circle is centred ``corner`` in from both sides
    there, and may reach past the rectangle's middle.
    """

    centre: Vec
    first: Vec
    second: Vec
    normal: Vec
    half: tuple[float, float]
    corner: float
    low: float
    high: float
    rounded: tuple[bool, bool, bool, bool] = (True, True, True, True)

    def __post_init__(self) -> None:
        h1, h2 = self.half
        r = [self.corner if on else 0.0 for on in self.rounded]
        # Along each side, the two corners at its ends leave it whole: the
        # +first side runs between corners 0 and 3, the +second side between 0 and 1.
        sides = ((r[0] + r[3], 2 * h2), (r[0] + r[1], 2 * h1), (r[1] + r[2], 2 * h2), (r[2] + r[3], 2 * h1))  # fmt: skip
        if not (h1 > 0 and h2 > 0 and self.corner >= 0) or any(
            used > room + 1e-12 for used, room in sides
        ):
            raise ValueError(
                f"a prism's outline is {self.half} with corners {self.corner} at {self.rounded}"
            )
        if not self.high > self.low:
            raise ValueError(f"a prism runs from {self.low} to {self.high}")

    def contains(self, points: Array) -> NDArray[np.bool_]:
        d = np.asarray(points, dtype=np.float64) - np.asarray(self.centre)
        u = fv.matmul(d, np.asarray(self.first))
        v = fv.matmul(d, np.asarray(self.second))
        h = fv.matmul(d, np.asarray(self.normal))
        h1, h2 = self.half
        r = self.corner
        found = (
            (np.abs(u) <= h1) & (np.abs(v) <= h2) & (h >= self.low) & (h <= self.high)
        )
        for (q1, q2), on in zip(QUADRANTS, self.rounded, strict=True):
            if on and r > 0:
                # Past the corner's centre along both: within its quarter-circle.
                du, dv = q1 * u - (h1 - r), q2 * v - (h2 - r)
                found &= ~((du > 0) & (dv > 0) & (du * du + dv * dv > r * r))
        return np.asarray(found)


@dataclass(frozen=True)
class Frustum:
    """The points within ``radii[0]`` of the axis at ``base``, narrowing (or widening) in a straight line to ``radii[1]`` at ``length`` along ``axis``."""

    base: Vec
    axis: Vec
    radii: tuple[float, float]
    length: float

    def __post_init__(self) -> None:
        if not (self.length > 0 and min(self.radii) >= 0 and max(self.radii) > 0):
            raise ValueError(
                f"a frustum of radii {self.radii} and length {self.length}"
            )

    def contains(self, points: Array) -> NDArray[np.bool_]:
        d = np.asarray(points, dtype=np.float64) - np.asarray(self.base)
        w = np.asarray(self.axis)
        s = fv.matmul(d, w)
        rho = fv.norm(d - s[:, None] * w, axis=1)
        r0, r1 = self.radii
        radius = r0 + (r1 - r0) * np.clip(s / self.length, 0.0, 1.0)
        return np.asarray((s >= 0) & (s <= self.length) & (rho <= radius))


Point = tuple[float, float]
#: One side of an outline: where it ends, and the centre it turns about (None: straight) and whether clockwise.
Side = tuple[Point, Point | None, bool]


@dataclass(frozen=True)
class Outline2:
    """A closed outline in a plane's two coordinates: where it starts, then each side in turn, straight or an arc about its centre (anticlockwise unless ``clockwise``), the last back at the start (extrusion.md)."""

    start: Point
    sides: tuple[Side, ...]

    def pieces(self) -> list[tuple[Point, Point, Point | None, float, float, float]]:
        """Each side as (from, to, centre, radius, the angle it starts at, its sweep: negative clockwise)."""
        found: list[tuple[Point, Point, Point | None, float, float, float]] = []
        here = self.start
        for to, centre, clockwise in self.sides:
            if centre is None:
                found.append((here, to, None, 0.0, 0.0, 0.0))
            else:
                r = fs.dist(here, centre)
                a0 = fs.atan2(here[1] - centre[1], here[0] - centre[0])
                a1 = fs.atan2(to[1] - centre[1], to[0] - centre[0])
                sweep = ((a0 - a1) if clockwise else (a1 - a0)) % (2 * math.pi)
                found.append((here, to, centre, r, a0, -sweep if clockwise else sweep))
            here = to
        return found

    def inside(self, u: Array, v: Array) -> NDArray[np.bool_]:
        """Whether each point is in the outline (on it counts as in, within a billionth of a millimetre).

        The crossing rule: a ray along the first coordinate, each arc cut where
        it turns back along the second (so each piece runs one way along it,
        on one side of its centre), and each piece crossed where it spans the
        ray's level half-open, as a polygon's sides are.
        """
        u, v = np.asarray(u, dtype=np.float64), np.asarray(v, dtype=np.float64)
        crossings = np.zeros(u.shape, dtype=np.int64)
        on = np.zeros(u.shape, dtype=bool)
        for a, b, centre, r, a0, sweep in self.pieces():
            if centre is None:
                (x0, y0), (x1, y1) = a, b
                spans = (y0 <= v) != (y1 <= v)
                with np.errstate(divide="ignore", invalid="ignore"):
                    x = x0 + (v - y0) * (x1 - x0) / (y1 - y0)
                crossings += spans & (x > u)
                on |= _near_segment(u, v, a, b)
                continue
            cx, cy = centre
            for start, end in _monotone(a0, sweep):
                side = 1.0 if fs.cos((start + end) / 2) > 0 else -1.0
                ys, ye = cy + r * fs.sin(start), cy + r * fs.sin(end)
                spans = (ys <= v) != (ye <= v)
                x = cx + side * np.sqrt(np.maximum(r * r - fv.sq(v - cy), 0.0))
                crossings += spans & (x > u)
            angle = fv.arctan2(v - cy, u - cx)
            along = (
                (angle - a0) % (2 * math.pi)
                if sweep > 0
                else (a0 - angle) % (2 * math.pi)
            )
            on |= (np.abs(fv.hypot(u - cx, v - cy) - r) <= 1e-9) & (
                along <= abs(sweep) + 1e-12
            )
            on |= (fv.hypot(u - a[0], v - a[1]) <= 1e-9) | (
                fv.hypot(u - b[0], v - b[1]) <= 1e-9
            )
        return np.asarray(on | (crossings % 2 == 1))

    def box(self) -> tuple[Point, Point]:
        """The box round it: its corners, and each arc's points furthest along each axis that it passes."""
        points: list[Point] = [self.start]
        for _, b, centre, r, a0, sweep in self.pieces():
            points.append(b)
            if centre is None:
                continue
            for k in range(4):
                angle = k * math.pi / 2
                along = (
                    (angle - a0) % (2 * math.pi)
                    if sweep > 0
                    else (a0 - angle) % (2 * math.pi)
                )
                if along <= abs(sweep):
                    points.append(
                        (
                            centre[0] + r * fs.cos(angle),
                            centre[1] + r * fs.sin(angle),
                        )
                    )
        return (min(p[0] for p in points), min(p[1] for p in points)), (
            max(p[0] for p in points),
            max(p[1] for p in points),
        )

    def followed(self, step: float) -> Array:
        """Points along its sides at most ``step`` apart, each side's ends among them: made once for each step (the generator asks for every footprint it tries on a profile's face), and not to be written to."""
        return _followed(self, step)


@lru_cache(maxsize=256)
def _followed(outline: Outline2, step: float) -> Array:
    found: list[Point] = []
    for a, b, centre, r, a0, sweep in outline.pieces():
        if centre is None:
            n = max(1, math.ceil(fs.dist(a, b) / step))
            found += [
                (a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n)
                for k in range(n)
            ]
        else:
            n = max(1, math.ceil(abs(sweep) * r / step))
            found += [(centre[0] + r * fs.cos(a0 + sweep * k / n), centre[1] + r * fs.sin(a0 + sweep * k / n))
                      for k in range(n)]  # fmt: skip
    found.append(outline.start)
    points = np.asarray(found, dtype=np.float64)
    points.flags.writeable = False
    return points


def _near_segment(u: Array, v: Array, a: Point, b: Point) -> NDArray[np.bool_]:
    (x0, y0), (x1, y1) = a, b
    dx, dy = x1 - x0, y1 - y0
    length2 = dx * dx + dy * dy
    t = (
        np.clip(((u - x0) * dx + (v - y0) * dy) / length2, 0.0, 1.0)
        if length2 > 0
        else np.zeros(u.shape)
    )
    return np.asarray(fv.hypot(u - (x0 + t * dx), v - (y0 + t * dy)) <= 1e-9)


def _monotone(a0: float, sweep: float) -> list[tuple[float, float]]:
    """An arc from angle ``a0`` through ``sweep`` (negative: clockwise) cut where it turns back along the second coordinate (at a quarter or three quarters round): each piece's angles, from and to."""
    cuts = sorted(
        t for k in range(-4, 5)
        for t in (math.pi / 2 + k * math.pi,)
        if 1e-12 < (t - a0) / sweep < 1 - 1e-12
    ) if sweep else []  # fmt: skip
    if sweep < 0:
        cuts.sort(reverse=True)
    stops = [a0, *cuts, a0 + sweep]
    return list(itertools.pairwise(stops))


@dataclass(frozen=True)
class Pushed:
    """The points whose place in the plane through ``origin`` (along ``first`` and ``second``) lies in ``outline`` and whose height along ``normal`` is from ``low`` to ``high``: an extrusion."""

    origin: Vec
    first: Vec
    second: Vec
    normal: Vec
    outline: Outline2
    low: float
    high: float

    def contains(self, points: Array) -> NDArray[np.bool_]:
        d = np.asarray(points, dtype=np.float64) - np.asarray(self.origin)
        h = fv.matmul(d, np.asarray(self.normal))
        found = self.outline.inside(
            fv.matmul(d, np.asarray(self.first)), fv.matmul(d, np.asarray(self.second))
        )
        return np.asarray(found & (h >= self.low) & (h <= self.high))


@dataclass(frozen=True)
class Turned:
    """The points whose distance from the line through ``base`` along ``axis``, and height along it, lie in ``outline`` (a half outline: revolution.md)."""

    base: Vec
    axis: Vec
    outline: Outline2

    def contains(self, points: Array) -> NDArray[np.bool_]:
        d = np.asarray(points, dtype=np.float64) - np.asarray(self.base)
        w = np.asarray(self.axis)
        h = fv.matmul(d, w)
        rho = fv.norm(d - h[:, None] * w, axis=1)
        return self.outline.inside(rho, h)


#: A quadratic piece of a letter's contour: start, control, end (a straight one has its control midway), font units.
Quadratic = tuple[Point, Point, Point]


def _contour_pieces(contour: Sequence[tuple[int, int, int]]) -> list[Quadratic]:
    """A TrueType contour as quadratic pieces, read here from the font's own points (its quadratic B-spline).

    Between two control points in a row lies a point on the curve, midway;
    after that each point on the curve is joined to the next on the curve
    straight, or round the one control point between them. The walk starts
    at a point on the curve (a contour of control points alone has none
    given: it starts at the first midway point).
    """
    raw = [(float(x), float(y), bool(on)) for x, y, on in contour]
    points: list[tuple[float, float, bool]] = []
    for k, (x, y, on) in enumerate(raw):
        px, py, pon = raw[k - 1]
        if not on and not pon:
            points.append(((px + x) / 2, (py + y) / 2, True))
        points.append((x, y, on))
    if not points:
        return []
    first = next(k for k, p in enumerate(points) if p[2])
    points = points[first:] + points[:first] + [points[first]]
    found: list[Quadratic] = []
    k = 0
    while k < len(points) - 1:
        a, c = points[k], points[k + 1]
        if c[2]:
            found.append(
                ((a[0], a[1]), ((a[0] + c[0]) / 2, (a[1] + c[1]) / 2), (c[0], c[1]))
            )
            k += 1
        else:
            b = points[k + 2]
            found.append(((a[0], a[1]), (c[0], c[1]), (b[0], b[1])))
            k += 2
    return found


def line_contours(text: str) -> tuple[list[list[Quadratic]], float]:
    """A line's contours as runs of pieces, every letter set at the advances before it (font units, x from the first letter's start, y up from the baseline), and the line's length (text.md)."""
    from forge_spec.font import ADVANCES
    from forge_spec.glyphs import CONTOURS

    found: list[list[Quadratic]] = []
    pen = 0.0
    for letter in text:
        for contour in CONTOURS[letter]:
            run = [((a[0] + pen, a[1]), (c[0] + pen, c[1]), (b[0] + pen, b[1]))
                   for a, c, b in _contour_pieces(contour)]  # fmt: skip
            if run:
                found.append(run)
        pen += ADVANCES[letter]
    return found, pen


def line_pieces(text: str) -> tuple[list[Quadratic], float]:
    """A line's pieces, all its contours' in turn, and the line's length (see :func:`line_contours`)."""
    contours, length = line_contours(text)
    return [piece for run in contours for piece in run], length


def ink_box(text: str, height: float) -> tuple[Point, Point] | None:
    """The box round a line's ink, its capitals ``height`` tall (mm; x from its first letter's start, y up from its baseline); None for a line with none.

    Each piece's ends, and where a quadratic piece turns along x or y (its
    derivative's root), bound it.
    """
    from forge_spec.font import CAP_HEIGHT

    pieces, _ = line_pieces(text)
    if not pieces:
        return None
    xs: list[float] = []
    ys: list[float] = []
    for a, c, b in pieces:
        for k, out in ((0, xs), (1, ys)):
            out += [a[k], b[k]]
            bend = a[k] - 2 * c[k] + b[k]
            if bend != 0.0:
                t = (a[k] - c[k]) / bend
                if 0.0 < t < 1.0:
                    out.append(
                        fv.sq(1 - t) * a[k] + 2 * (1 - t) * t * c[k] + t * t * b[k]
                    )
    scale = height / CAP_HEIGHT
    return (min(xs) * scale, min(ys) * scale), (max(xs) * scale, max(ys) * scale)


@dataclass(frozen=True)
class Letters:
    """A line of letters (text.md) pushed along ``right`` x ``up`` from ``low`` to ``high``: the region of nonzero winding of every contour.

    ``text`` set in the pinned font, its capitals ``height`` tall, the
    line's box (its first letter's start to its last letter's advance, the
    baseline to a capital's top) centred on ``centre``, running along
    ``right`` with ``up`` its up. A point is in the letters when the
    contours wind round its place in the plane a number of times other than
    0: each piece split where it turns along the plane's up, so that a line
    through the point along ``right`` crosses each part at most once
    (counted where the point's height is from the part's lower end up to,
    not at, its upper one), +1 where the part runs up and passes beyond the
    point, -1 where it runs down.
    """

    centre: Vec
    right: Vec
    up: Vec
    text: str
    height: float
    low: float
    high: float

    @property
    def normal(self) -> Vec:
        r, u = self.right, self.up
        return (
            r[1] * u[2] - r[2] * u[1],
            r[2] * u[0] - r[0] * u[2],
            r[0] * u[1] - r[1] * u[0],
        )

    def _parts(self) -> Array:
        """Each piece's parts that run one way up or down: (parts, 6) rows of their three points, in font units."""
        pieces, _ = line_pieces(self.text)
        rows = []
        for a, c, b in pieces:
            bend = a[1] - 2 * c[1] + b[1]
            t = (a[1] - c[1]) / bend if bend != 0.0 else -1.0
            if 0.0 < t < 1.0:
                # Split at t (de Casteljau): two quadratics, each monotone in y.
                ac = (a[0] + t * (c[0] - a[0]), a[1] + t * (c[1] - a[1]))
                cb = (c[0] + t * (b[0] - c[0]), c[1] + t * (b[1] - c[1]))
                m = (ac[0] + t * (cb[0] - ac[0]), ac[1] + t * (cb[1] - ac[1]))
                rows += [(*a, *ac, *m), (*m, *cb, *b)]
            else:
                rows.append((*a, *c, *b))
        return np.array([r for r in rows if r[1] != r[5]], dtype=np.float64).reshape(
            -1, 6
        )

    def contains(self, points: Array) -> NDArray[np.bool_]:
        from forge_spec.font import CAP_HEIGHT

        p = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        d = p - np.asarray(self.centre)
        h = fv.matmul(d, np.asarray(self.normal))
        found: NDArray[np.bool_] = (h >= self.low) & (h <= self.high)
        rows = np.flatnonzero(found)
        if not len(rows):
            return found
        scale = self.height / CAP_HEIGHT
        _, length = line_pieces(self.text)
        x = (fv.matmul(d[rows], np.asarray(self.right))) / scale + length / 2
        y = (fv.matmul(d[rows], np.asarray(self.up))) / scale + CAP_HEIGHT / 2
        parts = self._parts()
        winding = np.zeros(len(rows), dtype=np.int64)
        y0, y2 = parts[:, 1], parts[:, 5]
        lo, hi = np.minimum(y0, y2), np.maximum(y0, y2)
        way = np.where(y2 > y0, 1, -1)
        for k in range(0, len(rows), 1024):
            px, py = x[k : k + 1024], y[k : k + 1024]
            row, part = np.nonzero((py[:, None] >= lo) & (py[:, None] < hi))
            if not len(row):
                continue
            q = parts[part]
            # y(t) = py on the part: (y0 - 2 y1 + y2) t^2 + 2 (y1 - y0) t + (y0 - py) = 0, one root in [0, 1].
            qa = q[:, 1] - 2 * q[:, 3] + q[:, 5]
            qb = 2 * (q[:, 3] - q[:, 1])
            qc = q[:, 1] - py[row]
            with np.errstate(divide="ignore", invalid="ignore"):
                root = np.sqrt(np.maximum(qb * qb - 4 * qa * qc, 0.0))
                quadratic = np.stack(
                    [(-qb + root) / (2 * qa), (-qb - root) / (2 * qa)], axis=1
                )
                linear = -qc / qb
            fits = (quadratic >= -1e-12) & (quadratic <= 1 + 1e-12)
            t = np.where(fits[:, 0], quadratic[:, 0], quadratic[:, 1])
            t = np.clip(
                np.where(np.abs(qa) <= 1e-12 * (np.abs(qb) + 1.0), linear, t), 0.0, 1.0
            )
            at_x = fv.sq(1 - t) * q[:, 0] + 2 * (1 - t) * t * q[:, 2] + t * t * q[:, 4]
            turn = np.where(at_x > px[row], way[part], 0)
            winding[k : k + 1024] += np.bincount(
                row, weights=turn, minlength=len(px)
            ).astype(np.int64)
        found[rows] = winding != 0
        return found


@dataclass(frozen=True)
class Threaded:
    """An outside thread's zone (thread.md): the ring of a rod along ``axis`` from ``base``, from ``start`` to ``end`` along it, between the basic profile's minor radius and ``radius`` (the major).

    Where a thread's helix starts round its axis is the build's to say, not
    the spec's: so the truth holds the rod's core there (within the minor
    radius) and nothing beyond its major radius, and doesn't say which side
    of the part a point of the ring is (:meth:`Truth.unsure`). Taken from the
    part, the ring leaves what the part must hold. ``pitch`` and ``hand``
    (1 right, -1 left) are the thread's, for a part made of the truth.
    """

    base: Vec
    axis: Vec
    radius: float
    pitch: float
    hand: int
    start: float
    end: float

    @property
    def minor(self) -> float:
        """The minor radius: in by 5/8 of the sharp 60 degree triangle's height."""
        return self.radius - 5 / 8 * math.sqrt(3) / 2 * self.pitch

    def contains(self, points: Array) -> NDArray[np.bool_]:
        d = np.asarray(points, dtype=np.float64).reshape(-1, 3) - np.asarray(self.base)
        w = np.asarray(self.axis)
        s = fv.matmul(d, w)
        rho = fv.norm(d - s[:, None] * w, axis=1)
        found: NDArray[np.bool_] = (
            (s >= self.start)
            & (s <= self.end)
            & (rho >= self.minor)
            & (rho <= self.radius)
        )
        return found


def _rounded_off(u: Array, v: Array, size: float, round_: bool) -> NDArray[np.bool_]:
    """Within ``size`` of an edge along both of its faces (``u`` and ``v``, from the edge into each), and on the edge's side of the round touching both ``size`` back (``round_``), or of the bevel's line between those places."""
    found = (u >= 0) & (u <= size) & (v >= 0) & (v <= size)
    if round_:
        return np.asarray(found & (fv.sq(size - u) + fv.sq(size - v) >= size * size))
    return np.asarray(found & (u + v <= size))


@dataclass(frozen=True)
class Corner:
    """What a rounding (or a bevel) of a straight edge between two faces at right angles takes from the corner there, or fills into it (fillet.md, chamfer.md).

    The edge runs from ``start`` ``length`` along ``along``; ``a`` and ``b``
    are the two faces' ways from the edge into them. The points from the
    edge to ``size`` along both, on the edge's side of the round touching
    both faces ``size`` back (``round_``) or of the bevel's line between
    those places. On an outside edge the material lies between ``a`` and
    ``b``, and this is what the rounding takes away; on an inside edge (a
    joint, a pocket's floor) the air does, and it is what the rounding fills.
    """

    start: Vec
    along: Vec
    length: float
    a: Vec
    b: Vec
    size: float
    round_: bool

    def __post_init__(self) -> None:
        if not (self.length > 0 and self.size > 0):
            raise ValueError(f"an edge {self.length} long rounded by {self.size}")

    def contains(self, points: Array) -> NDArray[np.bool_]:
        d = np.asarray(points, dtype=np.float64) - np.asarray(self.start)
        s = fv.matmul(d, np.asarray(self.along))
        u, v = fv.matmul(d, np.asarray(self.a)), fv.matmul(d, np.asarray(self.b))
        return np.asarray(
            (s >= 0) & (s <= self.length) & _rounded_off(u, v, self.size, self.round_)
        )


@dataclass(frozen=True)
class RingCorner:
    """The same round a circular edge (a rim): the edge ``radius`` from the line through ``centre`` along ``axis``, ``height`` along it; ``a`` and ``b`` the two faces' ways from the edge into them in a plane through the axis, each as (out from the axis, along it).

    All the way round, or from ``first`` (a way across the axis) through
    the angles ``turn`` (from, to; anticlockwise about the axis, radians):
    a rounded corner's quarter of a pocket's rim.
    """

    centre: Vec
    axis: Vec
    radius: float
    height: float
    a: tuple[float, float]
    b: tuple[float, float]
    size: float
    round_: bool
    first: Vec | None = None
    turn: tuple[float, float] | None = None

    def __post_init__(self) -> None:
        if not (self.radius >= 0 and self.size > 0):
            raise ValueError(f"a rim {self.radius} out rounded by {self.size}")

    def contains(self, points: Array) -> NDArray[np.bool_]:
        d = np.asarray(points, dtype=np.float64) - np.asarray(self.centre)
        w = np.asarray(self.axis)
        h = fv.matmul(d, w)
        across = d - h[:, None] * w
        du, dh = fv.norm(across, axis=1) - self.radius, h - self.height
        u = du * self.a[0] + dh * self.a[1]
        v = du * self.b[0] + dh * self.b[1]
        found = _rounded_off(u, v, self.size, self.round_)
        if self.turn is not None:
            assert self.first is not None
            e1 = np.asarray(self.first)
            e2 = np.cross(w, e1)
            angle = fv.arctan2(fv.matmul(across, e2), fv.matmul(across, e1))
            start, end = self.turn
            found &= np.mod(angle - start, 2 * math.pi) <= (end - start) + 1e-12
        return np.asarray(found)


@dataclass(frozen=True)
class Kept:
    """A prism's points whose height along ``normal`` from ``origin`` is from ``low`` to ``high``: an item leaning on
    its flat face (place.md, "Leaning on the face"), its prism run along its direction from far enough back that all
    of its outline is past the face's plane, kept on the face's open side (``low`` 0: what stands) or within its
    material (``high`` 0: a cut). A step's ``reach`` carries the two planes on, not the prism's own ends.

    A leaning item's rounding (edges.md, "A leaning item's edges") is kept so
    too, on its face's open side: a long edge's runs from where all of its
    section is past the face's plane, and what it takes stops at the plane,
    where the edge meets it; a far end's edge that dips to the plane stops
    there alike. A kept rounding's step's ``reach`` carries the rounding's
    own ends on (its planes are where they are: the face's, and one past it).
    """

    solid: Prism | Corner | RingCorner
    origin: Vec
    normal: Vec
    low: float
    high: float

    def __post_init__(self) -> None:
        if not self.high > self.low:
            raise ValueError(f"a prism kept from {self.low} to {self.high}")

    def contains(self, points: Array) -> NDArray[np.bool_]:
        p = np.asarray(points, dtype=np.float64)
        h = fv.matmul(p - np.asarray(self.origin), np.asarray(self.normal))
        return np.asarray(self.solid.contains(p) & (h >= self.low) & (h <= self.high))


Solid = Prism | Frustum | Pushed | Turned | Letters | Threaded | Corner | RingCorner | Kept
#: How much each solid's box is grown by before the points outside it are left out of its test (mm): more
#: than an outline's own allowance for a point on its edge.
_CULL = 1e-6


@dataclass(frozen=True)
class Step:
    """One step of making the part: ``solid`` added to it (``add``) or taken from it, for one copy of ``item``.

    ``reach``: how far the solid may be carried on past its low and its high
    end (a prism's, along its normal; a frustum's, before its base and past
    its far end) without changing the part.
    """

    item: str
    index: int
    add: bool
    solid: Solid
    reach: tuple[float, float] = (0.0, 0.0)


@dataclass(frozen=True)
class Truth:
    """A generated part as the definitions mean it: every item's copies, and the steps it is made in."""

    copies: Mapping[str, tuple[Copy, ...]]
    steps: tuple[Step, ...]
    #: Boxes (low and high corners) where the definitions leave the shape to the making: where roundings meet
    #: at a corner or end against another face, the round itself is bounded, not given (fillet.md).
    zones: tuple[tuple[Vec, Vec], ...] = ()

    @cached_property
    def _boxes(self) -> tuple[tuple[Array, Array], ...]:
        """Each step's solid's box, grown by a micron: a point outside it is outside the solid."""
        return tuple((lo - _CULL, hi + _CULL) for lo, hi in (_bounds(s.solid) for s in self.steps))  # fmt: skip

    def _near(self, k: int, p: Array) -> NDArray[np.intp]:
        """The points in step ``k``'s solid's box: only they can be in the solid."""
        lo, hi = self._boxes[k]
        return np.flatnonzero(np.all((p >= lo) & (p <= hi), axis=1))

    def inside(self, points: Sequence[Sequence[float]] | Array) -> NDArray[np.bool_]:
        """Whether each point is in the part (on its surface counts as in)."""
        p = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        found: NDArray[np.bool_] = np.zeros(len(p), dtype=bool)
        for k, step in enumerate(self.steps):
            near = self._near(k, p)
            if not near.size:
                continue
            within = step.solid.contains(p[near])
            found[near] = found[near] | within if step.add else found[near] & ~within
        return found

    def unsure(self, points: Sequence[Sequence[float]] | Array) -> NDArray[np.bool_]:
        """Whether the truth doesn't say which side of the part each point is: in a thread's zone, or a rounding's."""
        p = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        found: NDArray[np.bool_] = np.zeros(len(p), dtype=bool)
        for k, step in enumerate(self.steps):
            if isinstance(step.solid, Threaded):
                near = self._near(k, p)
                found[near] |= step.solid.contains(p[near])
        for lo, hi in self.zones:
            found |= np.all((p >= np.asarray(lo)) & (p <= np.asarray(hi)), axis=1)
        return found

    def box(self) -> tuple[Array, Array]:
        """A box round every solid added (the part lies within it)."""
        lo, hi = np.full(3, math.inf), np.full(3, -math.inf)
        for step in self.steps:
            if not step.add:
                continue
            a, b = _bounds(step.solid)
            lo, hi = np.minimum(lo, a), np.maximum(hi, b)
        return lo, hi


def bounds(solid: Solid) -> tuple[Array, Array]:
    """A box round a solid: its low and high corners."""
    return _bounds(solid)


def _bounds(solid: Solid) -> tuple[Array, Array]:
    if isinstance(solid, Kept):
        # The prism's box, and along the planes' normal where it is one of the frame's axes, between them.
        lo, hi = _bounds(solid.solid)
        across = solid.normal
        for k in range(3):
            if abs(across[k]) == 1.0 and all(across[j] == 0.0 for j in range(3) if j != k):
                at = [solid.origin[k] + across[k] * solid.low, solid.origin[k] + across[k] * solid.high]
                lo[k], hi[k] = max(lo[k], min(at)), min(hi[k], max(at))
        return lo, hi
    if isinstance(solid, Corner):
        o = np.asarray(solid.start)
        w, a, b = (np.asarray(v) for v in (solid.along, solid.a, solid.b))
        corners = [o + s * w + p * a + q * b for s in (0.0, solid.length) for p in (0.0, solid.size)
                   for q in (0.0, solid.size)]  # fmt: skip
        return np.min(corners, axis=0), np.max(corners, axis=0)
    if isinstance(solid, RingCorner):
        # Within the cylinder ``size`` past its radius, ``size`` either way of its height: the box round the
        # discs at its ends.
        c, w = np.asarray(solid.centre), np.asarray(solid.axis)
        across = (solid.radius + solid.size) * np.sqrt(np.maximum(1.0 - w * w, 0.0))
        ends = [
            c + (solid.height - solid.size) * w,
            c + (solid.height + solid.size) * w,
        ]
        return np.min(ends, axis=0) - across, np.max(ends, axis=0) + across
    if isinstance(solid, Threaded):
        b, w = np.asarray(solid.base), np.asarray(solid.axis)
        ends = [b + solid.start * w, b + solid.end * w]
        return np.min(ends, axis=0) - solid.radius, np.max(ends, axis=0) + solid.radius
    if isinstance(solid, Letters):
        from forge_spec.font import CAP_HEIGHT

        pieces, length = line_pieces(solid.text)
        scale = solid.height / CAP_HEIGHT
        c = np.asarray(solid.centre)
        way, up, n = (np.asarray(v) for v in (solid.right, solid.up, solid.normal))
        # Each piece's control points hold it: their corners, laid out.
        corners = [
            c
            + (q[0] * scale - length * scale / 2) * way
            + (q[1] * scale - solid.height / 2) * up
            + t * n
            for piece in pieces
            for q in piece
            for t in (solid.low, solid.high)
        ] or [c]
        return np.min(corners, axis=0), np.max(corners, axis=0)
    if isinstance(solid, Pushed):
        (l1, l2), (h1, h2) = solid.outline.box()
        o = np.asarray(solid.origin)
        e1, e2, n = (np.asarray(v) for v in (solid.first, solid.second, solid.normal))
        corners = [
            o + a * e1 + b * e2 + t * n
            for a in (l1, h1)
            for b in (l2, h2)
            for t in (solid.low, solid.high)
        ]
        return np.min(corners, axis=0), np.max(corners, axis=0)
    if isinstance(solid, Turned):
        (_, l2), (h1, h2) = solid.outline.box()
        b, w = np.asarray(solid.base), np.asarray(solid.axis)
        ends = [b + l2 * w, b + h2 * w]
        return np.min(ends, axis=0) - h1, np.max(ends, axis=0) + h1
    if isinstance(solid, Prism):
        c = np.asarray(solid.centre)
        e1, e2, n = (np.asarray(v) for v in (solid.first, solid.second, solid.normal))
        corners = [
            c + s1 * solid.half[0] * e1 + s2 * solid.half[1] * e2 + t * n
            for s1 in (-1, 1)
            for s2 in (-1, 1)
            for t in (solid.low, solid.high)
        ]
        return np.min(corners, axis=0), np.max(corners, axis=0)
    b, w = np.asarray(solid.base), np.asarray(solid.axis)
    r = max(solid.radii)
    ends = [b, b + solid.length * w]
    return np.min(ends, axis=0) - r, np.max(ends, axis=0) + r
