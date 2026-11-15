"""Letters as the judge reasons with them (docs/definitions/text.md; docs/V2-stage4.md, 7.1).

A line of text is set in the pinned font: each letter its glyph's contours
(:mod:`forge_spec.glyphs`, the font file's own curves), scaled so the letter H
is ``height`` tall, set one after another by advance width with no kerning
(:mod:`forge_spec.font`). A contour is a closed run of points on its curve
and quadratic B-spline control points: two points on the curve in a row are
joined straight; one control point between two makes a quadratic arc; two
control points in a row have the curve's point midway between them. The
letters are the region of **nonzero winding** of every contour, TrueType's
own rule: overlapping parts of one letter, and touching letters, are one
region.

Here, the line in its own plane, x along it from its first letter's start
and y up from its baseline:

- :func:`ink_box`: the least box round its ink (each straight piece's ends,
  and each arc's ends and turning points along either axis);
- :class:`Ink`: its pieces, the winding number of a point (each piece split
  where it turns along y, so each part is crossed at most once by a line
  along x, counted on the half-open rule: a part from y0 up to y1 counts at
  y0 <= y < y1), and a point's distance to the ink's edge (the least over
  the pieces: a straight piece's foot, or a quadratic arc's nearest point,
  the root of a cubic, each root bracketed between the cubic's turning
  points and found by halving).

This is the judge's own code: the solver and the build have theirs (rule R2).

>>> ink = Ink.of("I", 1493.0)  # an I as tall as the font draws it
>>> ink.box == ink_box("I", 1493.0)
True
>>> import numpy as np
>>> x, y = np.array([ink.box[0][0] + 10.0, -50.0]), np.array([700.0, 700.0])
>>> ink.inside(x, y).tolist(), ink.distance(x, y).round(6).tolist()
([True, False], [10.0, 238.0])
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from functools import cache, cached_property, partial
from itertools import pairwise

import numpy as np
from forge_spec.font import ADVANCES, CAP_HEIGHT
from forge_spec.glyphs import CONTOURS
from numpy.typing import NDArray

from .shapes import _MEET, ON, FlatPatch, Locals, Patch, Prism, Shape2D, _locals

__all__ = ["Edge", "Ink", "LetterPrism", "Letters2D", "ink_box", "line_length"]

Array = NDArray[np.float64]
Point = tuple[float, float]
#: A quadratic piece (start, control, end); a straight piece has its control midway.
Quad = tuple[Point, Point, Point]


def _quads(contour: Sequence[tuple[int, int, int]]) -> list[Quad]:
    """A contour's pieces in turn, closed, each a quadratic (a straight one with its control point midway)."""
    n = len(contour)
    if n == 0:
        return []
    on = [bool(p[2]) for p in contour]
    xy = [(float(p[0]), float(p[1])) for p in contour]

    def mid(p: Point, q: Point) -> Point:
        return ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)

    # The points on the curve in turn, each with the control point before it (None: straight).
    if any(on):
        k0 = on.index(True)
        order = [(xy[(k0 + j) % n], on[(k0 + j) % n]) for j in range(1, n + 1)]
        start = xy[k0]
    else:
        start = mid(xy[-1], xy[0])
        order = [(p, False) for p in xy] + [(start, True)]
    found: list[Quad] = []
    here, control = start, None
    for p, is_on in order:
        if is_on:
            found.append((here, control if control is not None else mid(here, p), p))
            here, control = p, None
        elif control is None:
            control = p
        else:
            m = mid(control, p)
            found.append((here, control, m))
            here, control = m, p
    if (
        control is not None
    ):  # the run ended on a control point: round it back to the start
        found.append((here, control, start))
    return [q for q in found if q[0] != q[2] or q[1] != q[0]]


@cache
def _glyph(letter: str) -> tuple[Quad, ...]:
    return tuple(q for contour in CONTOURS[letter] for q in _quads(contour))


def _at(q: Quad, t: float) -> Point:
    (x0, y0), (x1, y1), (x2, y2) = q
    u = 1.0 - t
    return (
        u * u * x0 + 2 * u * t * x1 + t * t * x2,
        u * u * y0 + 2 * u * t * y1 + t * t * y2,
    )


def _turns(q: Quad, k: int) -> list[float]:
    """Where a piece turns along axis ``k`` (0 < t < 1)."""
    a, c, b = q[0][k], q[1][k], q[2][k]
    bend = a - 2 * c + b
    if bend == 0.0:
        return []
    t = (a - c) / bend
    return [t] if 0.0 < t < 1.0 else []


def line_length(text: str, height: float) -> float:
    """How long the line's box is: its letters' advances added up, its capitals ``height`` tall."""
    return sum(ADVANCES[ch] for ch in text) * height / CAP_HEIGHT


def _laid(text: str, height: float) -> list[Quad]:
    """Every piece of every letter, scaled and set along the line."""
    scale = height / CAP_HEIGHT
    found: list[Quad] = []
    advance = 0
    for letter in text:
        for q in _glyph(letter):
            found.append(tuple(((x + advance) * scale, y * scale) for x, y in q))  # type: ignore[arg-type]
        advance += ADVANCES[letter]
    return found


def _box(pieces: Iterable[Quad]) -> tuple[Point, Point] | None:
    points = [
        p
        for q in pieces
        for p in (q[0], q[2], *(_at(q, t) for k in (0, 1) for t in _turns(q, k)))
    ]
    if not points:
        return None
    return (min(p[0] for p in points), min(p[1] for p in points)), (
        max(p[0] for p in points),
        max(p[1] for p in points),
    )


def ink_box(text: str, height: float) -> tuple[Point, Point] | None:
    """The least box round a line's ink, its capitals ``height`` tall; None when it has none (spaces alone)."""
    return _box(_laid(text, height))


# ----------------------------------------------------------------------
# Pieces: splitting, meeting
# ----------------------------------------------------------------------
def _sub(q: Quad, t0: float, t1: float) -> Quad:
    """The stretch of a piece from ``t0`` to ``t1``, itself a quadratic (its control where the end tangents meet)."""
    a, b = _at(q, t0), _at(q, t1)
    (x0, y0), (x1, y1), (x2, y2) = q
    # The control point: B(t0) + (t1 - t0)/2 * B'(t0), B'(t) = 2 ((1 - t)(P1 - P0) + t (P2 - P1)).
    h = t1 - t0
    dx = (1 - t0) * (x1 - x0) + t0 * (x2 - x1)
    dy = (1 - t0) * (y1 - y0) + t0 * (y2 - y1)
    return a, (a[0] + h * dx, a[1] + h * dy), b


def _straight(q: Quad) -> bool:
    """Whether a piece is straight: its control point on its chord."""
    (x0, y0), (x1, y1), (x2, y2) = q
    chord = (x2 - x0) ** 2 + (y2 - y0) ** 2
    return abs((x1 - x0) * (y2 - y0) - (y1 - y0) * (x2 - x0)) <= 1e-12 * chord


def _hull(q: Quad) -> tuple[float, float, float, float]:
    xs, ys = (q[0][0], q[1][0], q[2][0]), (q[0][1], q[1][1], q[2][1])
    return min(xs), min(ys), max(xs), max(ys)


def _meet(p: Quad, q: Quad, size: float) -> list[tuple[float, float]]:
    """Where two pieces meet, as (t on ``p``, t on ``q``), each place once.

    Two straight pieces meet where their lines do, or, lying along one line,
    where each one's ends lie in the other. Otherwise the pieces are halved
    while their hulls overlap, down to ``size``; the places found are then
    polished by Newton's method on B_p(s) = B_q(t), and those that come
    together are one.
    """
    if _straight(p) and _straight(q):
        return _meet_straight(p, q, size)
    found: list[tuple[float, float]] = []
    stack = [(p, 0.0, 1.0, q, 0.0, 1.0)]
    while stack:
        a, a0, a1, b, b0, b1 = stack.pop()
        ha, hb = _hull(a), _hull(b)
        if (
            ha[0] > hb[2] + size
            or hb[0] > ha[2] + size
            or ha[1] > hb[3] + size
            or hb[1] > ha[3] + size
        ):
            continue
        wa, wb = max(ha[2] - ha[0], ha[3] - ha[1]), max(hb[2] - hb[0], hb[3] - hb[1])
        if max(wa, wb) <= size:
            found.append(((a0 + a1) / 2, (b0 + b1) / 2))
            if len(found) > 4096:
                raise ValueError("two pieces of the letters run along each other")
            continue
        if wa >= wb:
            m = (a0 + a1) / 2
            stack += [
                (_sub(p, a0, m), a0, m, b, b0, b1),
                (_sub(p, m, a1), m, a1, b, b0, b1),
            ]
        else:
            m = (b0 + b1) / 2
            stack += [
                (a, a0, a1, _sub(q, b0, m), b0, m),
                (a, a0, a1, _sub(q, m, b1), m, b1),
            ]
    polished = [_polish(p, q, s, t) for s, t in found]
    kept: list[tuple[float, float]] = []
    for s, t in sorted(polished):
        if not any(abs(s - s2) <= 1e-7 and abs(t - t2) <= 1e-7 for s2, t2 in kept):
            kept.append((s, t))
    return kept


def _polish(p: Quad, q: Quad, s: float, t: float) -> tuple[float, float]:
    """Newton's method on B_p(s) - B_q(t) = 0 from (s, t), kept where it doesn't settle."""
    s0, t0 = s, t
    for _ in range(20):
        (px, py), (qx, qy) = _at(p, s), _at(q, t)
        fx, fy = px - qx, py - qy
        dps, dqt = _velocity(p, s), _velocity(q, t)
        det = dps[0] * -dqt[1] - (-dqt[0]) * dps[1]
        if det == 0.0:
            break
        ds = (fx * -dqt[1] - (-dqt[0]) * fy) / det
        dt = (dps[0] * fy - dps[1] * fx) / det
        s, t = s - ds, t - dt
        if abs(ds) < 1e-15 and abs(dt) < 1e-15:
            break
    if (
        not (0.0 <= s <= 1.0 and 0.0 <= t <= 1.0)
        or abs(s - s0) > 1e-3
        or abs(t - t0) > 1e-3
    ):
        return s0, t0
    return s, t


def _velocity(q: Quad, t: float) -> Point:
    (x0, y0), (x1, y1), (x2, y2) = q
    return 2 * ((1 - t) * (x1 - x0) + t * (x2 - x1)), 2 * (
        (1 - t) * (y1 - y0) + t * (y2 - y1)
    )


def _meet_straight(p: Quad, q: Quad, size: float) -> list[tuple[float, float]]:
    (ax, ay), _, (bx, by) = p
    (cx, cy), _, (dx, dy) = q
    ux, uy, vx, vy = bx - ax, by - ay, dx - cx, dy - cy
    det = ux * vy - uy * vx
    lu, lv = math.hypot(ux, uy), math.hypot(vx, vy)
    if abs(det) > 1e-12 * lu * lv:
        s = ((cx - ax) * vy - (cy - ay) * vx) / det
        t = ((cx - ax) * uy - (cy - ay) * ux) / det
        return [(s, t)] if -1e-12 <= s <= 1 + 1e-12 and -1e-12 <= t <= 1 + 1e-12 else []
    # Parallel: along one line, each one's ends where they lie in the other.
    if abs((cx - ax) * uy - (cy - ay) * ux) > size * lu:
        return []
    found = []
    for k, (x, y) in enumerate(((cx, cy), (dx, dy))):
        s = ((x - ax) * ux + (y - ay) * uy) / (lu * lu)
        if 0.0 < s < 1.0:
            found.append((s, float(k)))
    for k, (x, y) in enumerate(((ax, ay), (bx, by))):
        t = ((x - cx) * vx + (y - cy) * vy) / (lv * lv)
        if 0.0 < t < 1.0:
            found.append((float(k), t))
    return found


# ----------------------------------------------------------------------
# The ink
# ----------------------------------------------------------------------
#: How far off a stretch of edge the winding number is read on either side, to tell which side the letters are on (mm).
_SIDE = 1e-7
#: Points asked about at a time (each against every piece or stretch at once).
_CHUNK = 2048
#: (point, stretch) pairs looked at a time, through the edge's grid.
_PAIRS = 1 << 20
#: The edge's grid has about this many cells for each stretch, and no more than :data:`_CELLS` of them.
_PER_STRETCH = 4.0
_CELLS = 1 << 14


@dataclass(frozen=True, eq=False)
class _Grid:
    """Cells over the edge, each listing the stretches that may be nearest to a point in it, or within its half-diagonal of it.

    A point ``p`` in a cell is no farther from the edge than from the cell's
    centre plus the centre's distance to the edge, ``D`` (the triangle
    inequality), so no farther than ``D + r``, ``r`` the cell's half-diagonal:
    its nearest stretch's box comes within ``D + r`` of the cell. Each cell
    lists every stretch whose box comes within ``D + 2 r`` of it: those, and
    every stretch within ``r`` of any point in it.
    """

    lo: Array
    step: Array
    shape: tuple[int, int]
    #: Each cell's centre (cells, 2) and its distance to the edge (cells,).
    centres: Array
    reach: Array
    #: Half a cell's diagonal: the farthest a point within it is asked about (:meth:`Ink.facets`).
    half: float
    #: The stretches listed for each cell: ``items[start[c]:start[c + 1]]``.
    start: NDArray[np.intp]
    items: NDArray[np.intp]

    def cell(self, x: Array, y: Array) -> NDArray[np.intp]:
        """The cell each point is in (row-major), or -1 for a point outside the grid."""
        i = np.floor((x - self.lo[0]) / self.step[0])
        j = np.floor((y - self.lo[1]) / self.step[1])
        nx, ny = self.shape
        within = (i >= 0) & (i < nx) & (j >= 0) & (j < ny)
        found: NDArray[np.intp] = np.where(
            within,
            np.where(within, j, 0).astype(np.intp) * nx
            + np.where(within, i, 0).astype(np.intp),
            -1,
        )
        return found

    def pairs(
        self, cells: NDArray[np.intp]
    ) -> tuple[NDArray[np.intp], NDArray[np.intp]]:
        """Each point (in a cell) against each stretch its cell lists: (point, stretch) pairs."""
        count = self.start[cells + 1] - self.start[cells]
        row = np.repeat(np.arange(len(cells)), count)
        offset = np.arange(len(row)) - np.repeat(np.cumsum(count) - count, count)
        return row, self.items[np.repeat(self.start[cells], count) + offset]


@dataclass(frozen=True, eq=False)
class Edge:
    """A stretch of the letters' edge: a quadratic, the letters on its ``side`` (1: to the left of the way it runs; -1: to the right)."""

    q: Quad
    side: int


@dataclass(frozen=True, eq=False)
class Ink:
    """A line's letters in a plane: their pieces, the region of nonzero winding, and its edge.

    The pieces of the contours, wherever they meet another, are split there;
    each stretch whose two sides differ (the letters on one, none on the
    other) is the edge's, its letters' side read from the winding number
    just off it. A stretch with letters on both sides (inside an overlap, or
    where two letters touch along a line) is no edge at all.
    """

    pieces: tuple[Quad, ...]
    edges: tuple[Edge, ...]
    box: tuple[Point, Point] | None

    @staticmethod
    def of(
        text: str, height: float, *, right: float = 1.0, at: Point = (0.0, 0.0)
    ) -> Ink:
        """A line of ``text``, its capitals ``height`` tall, its first letter's start and baseline at ``at``, running along ``right`` times the first axis."""

        def moved(p: Point) -> Point:
            return at[0] + right * p[0], at[1] + p[1]

        pieces = [(moved(a), moved(c), moved(b)) for a, c, b in _laid(text, height)]
        return Ink.of_pieces(pieces, height)

    @staticmethod
    def of_pieces(pieces: Sequence[Quad], size: float) -> Ink:
        """The ink of these pieces, ``size`` the scale its places are found to (a part in 10^9 of it)."""
        tol = 1e-9 * max(size, 1.0)
        splits: list[list[float]] = [[] for _ in pieces]
        hulls = [_hull(q) for q in pieces]
        order = sorted(range(len(pieces)), key=lambda k: hulls[k][0])
        for n, i in enumerate(order):
            for j in order[n + 1 :]:
                if hulls[j][0] > hulls[i][2] + tol:
                    break
                if hulls[j][1] > hulls[i][3] + tol or hulls[i][1] > hulls[j][3] + tol:
                    continue
                for s, t in _meet(pieces[i], pieces[j], tol):
                    splits[i].append(s)
                    splits[j].append(t)
        stretches: list[Quad] = []
        for q, ts in zip(pieces, splits, strict=True):
            cuts = [0.0, *sorted(t for t in ts if 1e-6 < t < 1 - 1e-6), 1.0]
            for t0, t1 in pairwise(cuts):
                if t1 - t0 > 1e-12:
                    stretches.append(_sub(q, t0, t1) if (t0, t1) != (0.0, 1.0) else q)
        ink = Ink(tuple(pieces), (), _box(pieces))
        edges: list[Edge] = []
        if stretches:
            mids = [_at(q, 0.5) for q in stretches]
            normals = [_left(q, 0.5) for q in stretches]
            x = np.array([m[0] for m in mids])
            y = np.array([m[1] for m in mids])
            nx = np.array([n[0] for n in normals])
            ny = np.array([n[1] for n in normals])
            left = ink.winding(x + _SIDE * nx, y + _SIDE * ny) != 0
            right_ = ink.winding(x - _SIDE * nx, y - _SIDE * ny) != 0
            for q, l_, r_ in zip(
                stretches, left.tolist(), right_.tolist(), strict=True
            ):
                if l_ != r_:
                    edges.append(Edge(q, 1 if l_ else -1))
        return Ink(tuple(pieces), tuple(edges), ink.box)

    # --- the pieces and the edge as arrays ---------------------------------------
    @cached_property
    def _parts(self) -> tuple[Array, Array, Array]:
        """Each piece split where it turns along y, so that it runs one way along y (or is flat): its points, (M, 3, 2)."""
        found: list[Quad] = []
        for q in self.pieces:
            ts = _turns(q, 1)
            found += [q] if not ts else [_sub(q, 0.0, ts[0]), _sub(q, ts[0], 1.0)]
        rows = np.array(
            [[c for p in q for c in p] for q in found if q[0][1] != q[2][1]],
            dtype=float,
        ).reshape(-1, 6)
        return rows[:, 0:2], rows[:, 2:4], rows[:, 4:6]

    @cached_property
    def _edges(self) -> tuple[Array, Array, Array, Array, Array, Array]:
        """The edge's stretches as arrays: their three points (E, 2) each, the letters' side (E,), and each one's box (E, 4)."""
        q = np.array(
            [[c for p in e.q for c in p] for e in self.edges], dtype=float
        ).reshape(-1, 6)
        side = np.array([e.side for e in self.edges], dtype=float)
        xs, ys = q[:, 0::2], q[:, 1::2]
        hull = np.stack(
            [xs.min(axis=1), ys.min(axis=1), xs.max(axis=1), ys.max(axis=1)], axis=1
        )
        return (
            q[:, 0:2],
            q[:, 2:4],
            q[:, 4:6],
            side,
            hull,
            0.25 * q[:, 0:2] + 0.5 * q[:, 2:4] + 0.25 * q[:, 4:6],
        )

    @cached_property
    def _grid(self) -> _Grid:
        """The edge's grid (:class:`_Grid`): over its stretches' boxes, its cells about as many as the stretches."""
        p0, _, _, _, hull, _ = self._edges
        lo = np.array([hull[:, 0].min(), hull[:, 1].min()])
        hi = np.array([hull[:, 2].max(), hull[:, 3].max()])
        span = np.maximum(hi - lo, 1e-9 * max(1.0, float(np.max(hi - lo))))
        cells = min(max(1, round(_PER_STRETCH * len(p0))), _CELLS)
        side = math.sqrt(float(span[0] * span[1]) / cells)
        shape = (
            max(1, min(cells, math.ceil(float(span[0]) / side))),
            max(1, min(cells, math.ceil(float(span[1]) / side))),
        )
        step = span / np.array(shape, dtype=float)
        i, j = np.meshgrid(np.arange(shape[0]), np.arange(shape[1]))
        centres = np.stack(
            [lo[0] + (i.ravel() + 0.5) * step[0], lo[1] + (j.ravel() + 0.5) * step[1]],
            axis=1,
        )
        reach = np.concatenate(
            [
                self._nearest_of(
                    centres[k : k + _CHUNK, 0],
                    centres[k : k + _CHUNK, 1],
                    self._pairs_ends,
                )[0]
                for k in range(0, len(centres), _CHUNK)
            ]
        )
        half = 0.5 * float(np.hypot(step[0], step[1]))
        slack = 1e-9 * max(1.0, float(np.max(span)))
        starts, items = [0], []
        for k in range(0, len(centres), _CHUNK):
            cx, cy = centres[k : k + _CHUNK, 0], centres[k : k + _CHUNK, 1]
            gx = np.maximum(
                np.abs(0.5 * (hull[None, :, 0] + hull[None, :, 2]) - cx[:, None])
                - 0.5 * (hull[None, :, 2] - hull[None, :, 0] + step[0]),
                0.0,
            )
            gy = np.maximum(
                np.abs(0.5 * (hull[None, :, 1] + hull[None, :, 3]) - cy[:, None])
                - 0.5 * (hull[None, :, 3] - hull[None, :, 1] + step[1]),
                0.0,
            )
            listed = (
                np.hypot(gx, gy)
                <= (reach[k : k + _CHUNK, None] + 2 * half) * (1 + 1e-9) + slack
            )
            row, edge = np.nonzero(listed)
            counts = np.bincount(row, minlength=len(cx))
            starts += (starts[-1] + np.cumsum(counts)).tolist()
            items.append(edge)
        return _Grid(
            lo,
            step,
            shape,
            centres,
            reach,
            half,
            np.asarray(starts, dtype=np.intp),
            np.concatenate(items).astype(np.intp),
        )

    # --- inside -----------------------------------------------------------
    def winding(self, x: Array, y: Array) -> NDArray[np.int64]:
        """Each point's winding number: how many times the pieces go round it, anticlockwise counted up.

        Each part (running one way along y) is crossed by the line along x
        through a point at most once: counted when the point's y is from the
        part's lower end up to (not at) its upper one, and the part there lies
        beyond the point along x; +1 for a part running up, -1 down.
        """
        x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
        found = np.zeros(x.shape, dtype=np.int64)
        p0, p1, p2 = self._parts
        if not len(p0) or not x.size:
            return found
        up = p2[:, 1] > p0[:, 1]
        lo, hi = np.minimum(p0[:, 1], p2[:, 1]), np.maximum(p0[:, 1], p2[:, 1])
        a = p0[:, 1] - 2 * p1[:, 1] + p2[:, 1]
        b = 2 * (p1[:, 1] - p0[:, 1])
        flat = np.abs(a) <= 1e-12 * (np.abs(b) + np.abs(p0[:, 1]) + 1.0)
        for k in range(0, x.size, _CHUNK):
            px, py = x.flat[k : k + _CHUNK], y.flat[k : k + _CHUNK]
            row, part = np.nonzero((py[:, None] >= lo) & (py[:, None] < hi))
            if not len(row):
                continue
            c = p0[part, 1] - py[row]
            aa, bb = a[part], b[part]
            with np.errstate(divide="ignore", invalid="ignore"):
                disc = np.sqrt(np.maximum(bb * bb - 4 * aa * c, 0.0))
                q_ = -0.5 * (
                    bb + np.where(bb >= 0, disc, -disc)
                )  # its digits kept (no cancellation)
                r1, r2 = q_ / aa, np.where(q_ != 0.0, c / q_, 0.0)
                curved = np.where((r1 >= -1e-12) & (r1 <= 1 + 1e-12), r1, r2)
                t = np.where(flat[part], -c / bb, curved)
            t = np.clip(t, 0.0, 1.0)
            u = 1.0 - t
            at_x = u * u * p0[part, 0] + 2 * u * t * p1[part, 0] + t * t * p2[part, 0]
            crossed = at_x > px[row]
            turn = np.where(up[part], 1, -1) * crossed
            found.flat[k : k + _CHUNK] += np.bincount(
                row, weights=turn, minlength=len(px)
            ).astype(np.int64)
        return found

    def inside(self, x: Array, y: Array) -> NDArray[np.bool_]:
        """Whether each point is in the letters: its winding number isn't 0."""
        found: NDArray[np.bool_] = self.winding(x, y) != 0
        return found

    # --- the edge -----------------------------------------------------------
    def _within(
        self,
        x: Array,
        y: Array,
        row: NDArray[np.intp],
        edge: NDArray[np.intp],
        reach: Array,
    ) -> tuple[NDArray[np.intp], NDArray[np.intp]]:
        """The pairs (point ``row``, stretch ``edge``) whose stretch's box comes within ``reach`` (each point's) of the point."""
        hull = self._edges[4][edge]
        px, py = x[row], y[row]
        gx = np.maximum(np.maximum(hull[:, 0] - px, px - hull[:, 2]), 0.0)
        gy = np.maximum(np.maximum(hull[:, 1] - py, py - hull[:, 3]), 0.0)
        keep = np.hypot(gx, gy) <= reach[row]
        return row[keep], edge[keep]

    def _pairs_within(
        self, x: Array, y: Array, limit: Array
    ) -> tuple[NDArray[np.intp], NDArray[np.intp]]:
        """(point, stretch) pairs whose stretch's box comes within each point's ``limit`` of it, against every stretch."""
        hull = self._edges[4]
        gx = np.maximum(
            np.maximum(hull[None, :, 0] - x[:, None], x[:, None] - hull[None, :, 2]),
            0.0,
        )
        gy = np.maximum(
            np.maximum(hull[None, :, 1] - y[:, None], y[:, None] - hull[None, :, 3]),
            0.0,
        )
        row, edge = np.nonzero(np.hypot(gx, gy) <= limit[:, None])
        return row.astype(np.intp), edge.astype(np.intp)

    def _pairs_ends(
        self, x: Array, y: Array
    ) -> tuple[NDArray[np.intp], NDArray[np.intp]]:
        """(point, stretch) pairs among which each point's nearest stretch is: those whose box comes within the nearest end or middle of any stretch (the grid's own centres are measured so)."""
        p0, _, p2, _, _, middle = self._edges
        ends = np.concatenate([p0, p2, middle])
        bound = np.min(
            np.hypot(x[:, None] - ends[None, :, 0], y[:, None] - ends[None, :, 1]),
            axis=1,
        )
        return self._pairs_within(x, y, bound * (1 + 1e-12) + 1e-12)

    def _pairs_far(
        self, x: Array, y: Array
    ) -> tuple[NDArray[np.intp], NDArray[np.intp]]:
        """(point, stretch) pairs among which each point's nearest stretch is, for points outside the grid: those whose box comes within the point's distance from the nearest cell's centre plus the centre's distance to the edge."""
        grid = self._grid
        nx, ny = grid.shape
        i = np.clip(np.floor((x - grid.lo[0]) / grid.step[0]), 0, nx - 1).astype(
            np.intp
        )
        j = np.clip(np.floor((y - grid.lo[1]) / grid.step[1]), 0, ny - 1).astype(
            np.intp
        )
        cells = j * nx + i
        centre = grid.centres[cells]
        bound = np.hypot(x - centre[:, 0], y - centre[:, 1]) + grid.reach[cells]
        return self._pairs_within(x, y, bound * (1 + 1e-12) + 1e-12)

    def _pairs_grid(
        self, x: Array, y: Array, cells: NDArray[np.intp]
    ) -> tuple[NDArray[np.intp], NDArray[np.intp]]:
        """(point, stretch) pairs among which each point's nearest stretch is, the points in the grid's ``cells``: those listed for its cell, within the point's distance from the cell's centre plus the centre's distance to the edge."""
        grid = self._grid
        row, edge = grid.pairs(cells)
        centre = grid.centres[cells]
        bound = np.hypot(x - centre[:, 0], y - centre[:, 1]) + grid.reach[cells]
        return self._within(x, y, row, edge, bound * (1 + 1e-12) + 1e-12)

    def _nearest_of(
        self,
        x: Array,
        y: Array,
        pairs: Callable[[Array, Array], tuple[NDArray[np.intp], NDArray[np.intp]]],
    ) -> tuple[Array, Array, Array, Array, Array]:
        """Each point's distance to the edge, its nearest point and the outward normal there, the nearest among each point's ``pairs``."""
        best = np.full(x.shape, math.inf)
        qa, qb, na, nb = (np.zeros(x.shape) for _ in range(4))
        p0, p1, p2, side, _, _ = self._edges
        row, edge = pairs(x, y)
        if not len(row):
            return best, qa, qb, na, nb
        d, t = _to_quads(p0[edge], p1[edge], p2[edge], x[row], y[row])
        order = np.lexsort((d, row))
        row, edge, d, t = row[order], edge[order], d[order], t[order]
        first = np.ones(len(row), dtype=bool)
        first[1:] = row[1:] != row[:-1]
        row, edge, d, t = row[first], edge[first], d[first], t[first]
        best[row] = d
        u = 1.0 - t
        qa[row] = u * u * p0[edge, 0] + 2 * u * t * p1[edge, 0] + t * t * p2[edge, 0]
        qb[row] = u * u * p0[edge, 1] + 2 * u * t * p1[edge, 1] + t * t * p2[edge, 1]
        lx, ly = _left_of(p0[edge], p1[edge], p2[edge], t)
        na[row], nb[row] = -side[edge] * lx, -side[edge] * ly
        return best, qa, qb, na, nb

    def _batches(
        self, x: Array, y: Array
    ) -> Iterator[tuple[NDArray[np.intp], NDArray[np.intp] | None]]:
        """The points in batches, each with its points' cells in the grid (no more than :data:`_PAIRS` pairs in a batch), or None for a batch outside it."""
        grid = self._grid
        cells = grid.cell(x, y)
        outside = np.flatnonzero(cells < 0)
        for k in range(0, len(outside), _CHUNK):
            yield outside[k : k + _CHUNK], None
        within = np.flatnonzero(cells >= 0)
        total = np.cumsum(grid.start[cells[within] + 1] - grid.start[cells[within]])
        k = 0
        while k < len(within):
            done = int(total[k - 1]) if k else 0
            end = max(int(np.searchsorted(total, done + _PAIRS, side="right")), k + 1)
            yield within[k:end], cells[within[k:end]]
            k = end

    def nearest(self, x: Array, y: Array) -> tuple[Array, Array, Array, Array, Array]:
        """Each point's distance to the edge, its nearest point there, and the outward normal there.

        The nearest of the stretches whose boxes come near enough: for a
        point in the edge's grid (:class:`_Grid`), within its distance from
        its cell's centre plus the centre's distance to the edge, among the
        stretches its cell lists; elsewhere, within the nearest end or
        middle of any stretch.
        """
        x, y = np.asarray(x, dtype=float).ravel(), np.asarray(y, dtype=float).ravel()
        found = [np.full(x.shape, math.inf), *(np.zeros(x.shape) for _ in range(4))]
        if not self.edges:
            return found[0], found[1], found[2], found[3], found[4]
        for rows, cells in self._batches(x, y):
            if cells is None:
                part = self._nearest_of(x[rows], y[rows], self._pairs_far)
            else:
                part = self._nearest_of(
                    x[rows], y[rows], partial(self._pairs_grid, cells=cells)
                )
            for whole, piece in zip(found, part, strict=True):
                whole[rows] = piece
        return found[0], found[1], found[2], found[3], found[4]

    def distance(self, x: Array, y: Array) -> Array:
        """Each point's distance to the edge."""
        return self.nearest(x, y)[0]

    def signed_distance(self, x: Array, y: Array) -> Array:
        d = self.distance(x, y)
        found: Array = np.where(self.inside(x, y), -d, d)
        return found

    def _pairs_near(
        self, x: Array, y: Array, eps: float
    ) -> tuple[NDArray[np.intp], NDArray[np.intp]]:
        """(point, stretch) pairs whose stretch's box comes within ``eps`` of the point: through the grid's lists where ``eps`` is no more than its half-diagonal, else against every stretch."""
        grid = self._grid
        cells = (
            grid.cell(x, y) if eps <= grid.half else np.full(len(x), -1, dtype=np.intp)
        )
        rows: list[NDArray[np.intp]] = []
        edges: list[NDArray[np.intp]] = []
        reach = np.full(len(x), eps)
        for part in (np.flatnonzero(cells >= 0), np.flatnonzero(cells < 0)):
            for k in range(0, len(part), _CHUNK):
                at = part[k : k + _CHUNK]
                if cells[at[0]] >= 0:
                    row, edge = grid.pairs(cells[at])
                    row, edge = self._within(x[at], y[at], row, edge, reach[at])
                else:
                    row, edge = self._pairs_within(x[at], y[at], reach[at])
                rows.append(at[row])
                edges.append(edge)
        if not rows:
            return np.zeros(0, dtype=np.intp), np.zeros(0, dtype=np.intp)
        return np.concatenate(rows), np.concatenate(edges)

    def facets(
        self, x: Array, y: Array, eps: float
    ) -> tuple[Array, NDArray[np.bool_], NDArray[np.bool_]]:
        """The edge near each point, to first order: up to two outward normals (n, 2, 2; NaN where unused), whether it is an inside corner (the letters there the union of the two sides' half-planes), and whether it is more than that (three ways or more: unsure).

        Normals within a part in 10^9 of each other are one. At a corner, the
        letters' side is read just off it along the way between its two
        normals: the letters there mean an inside corner.
        """
        x, y = np.asarray(x, dtype=float).ravel(), np.asarray(y, dtype=float).ravel()
        n = len(x)
        found = np.full((n, 2, 2), np.nan)
        crowded = np.zeros(n, dtype=bool)
        inner = np.zeros(n, dtype=bool)
        if not self.edges or not n:
            return found, inner, crowded
        p0, p1, p2, side, _, _ = self._edges
        row, edge = self._pairs_near(x, y, eps)
        d, t = _to_quads(p0[edge], p1[edge], p2[edge], x[row], y[row])
        on = d <= eps
        row, edge, t = row[on], edge[on], t[on]
        lx, ly = _left_of(p0[edge], p1[edge], p2[edge], t)
        mx, my = -side[edge] * lx, -side[edge] * ly
        count = np.zeros(n, dtype=np.int64)
        for r, ax, ay in zip(row.tolist(), mx.tolist(), my.tolist(), strict=True):
            k = int(count[r])
            if any(
                found[r, j, 0] * ax + found[r, j, 1] * ay > 1 - 1e-9
                for j in range(min(k, 2))
            ):
                continue
            if k >= 2:
                crowded[r] = True
                continue
            found[r, k] = (ax, ay)
            count[r] = k + 1
        corner = (count == 2) & ~crowded
        if np.any(corner):
            rows = np.flatnonzero(corner)
            way = found[rows, 0] - found[rows, 1]
            way /= np.linalg.norm(way, axis=1)[:, None]
            inner[rows] = self.inside(
                x[rows] + 1e3 * _SIDE * way[:, 0], y[rows] + 1e3 * _SIDE * way[:, 1]
            )
        return found, inner, crowded

    def meets(self, a: Array, b: Array, da: Array, db: Array) -> Array:
        """Where each line ``(a, b) + t (da, db)`` meets the edge: (n, k) places along it, NaN where a line has fewer.

        Each stretch's curve, carried on past its ends, meets the line at up
        to two places (a quadratic's roots in the curve's parameter ``s``);
        a place is the edge's when it is on the stretch (``s`` from 0 to 1, to
        a part in 10^9) and the line's point there is within half
        :data:`~forge_checks.shapes._MEET` of the curve's (a root found
        wrong, its ``s`` vast where the curve is nearly straight, puts them
        far apart). A line passing from inside the letters to outside or back
        does so on some stretch, there; one that only touches the edge may or
        may not have the place. Each line's places are packed to the front,
        the columns as many as the most any line has.

        Only the stretches whose box, grown by :data:`~forge_checks.shapes._MEET`,
        the line passes through are solved for: the box's reach across the
        line (its half sizes against the line's unit normal) is at least the
        line's distance from its centre. A line that doesn't move in the plane
        meets none.
        """
        a, b, da, db = (np.asarray(v, dtype=float).ravel() for v in (a, b, da, db))
        p0, p1, p2, _, hull, _ = self._edges
        if not len(p0):
            return np.zeros((len(a), 0))
        speed = np.hypot(da, db)
        moving = np.flatnonzero(speed > 0.0)
        cx, cy = 0.5 * (hull[:, 0] + hull[:, 2]), 0.5 * (hull[:, 1] + hull[:, 3])
        hx, hy = (
            0.5 * (hull[:, 2] - hull[:, 0]) + _MEET,
            0.5 * (hull[:, 3] - hull[:, 1]) + _MEET,
        )
        slack = 1e-12 * (1.0 + float(np.max(np.abs(hull))))
        rows: list[NDArray[np.intp]] = []
        places: list[Array] = []
        for k in range(0, len(moving), _CHUNK):
            line = moving[k : k + _CHUNK]
            nx, ny = -db[line] / speed[line], da[line] / speed[line]
            off = nx[:, None] * (cx - a[line, None]) + ny[:, None] * (
                cy - b[line, None]
            )
            reach = np.abs(nx)[:, None] * hx + np.abs(ny)[:, None] * hy + slack
            row, edge = np.nonzero(np.abs(off) <= reach)
            if not len(row):
                continue
            la, lb, lda, ldb = a[line][row], b[line][row], da[line][row], db[line][row]
            q0, q1, q2 = p0[edge], p1[edge], p2[edge]
            # cross(B(s) - (a, b), (da, db)) = 0: a quadratic in s; then t along the line.
            ax2, ay2 = (
                q0[:, 0] - 2 * q1[:, 0] + q2[:, 0],
                q0[:, 1] - 2 * q1[:, 1] + q2[:, 1],
            )
            bx2, by2 = 2 * (q1[:, 0] - q0[:, 0]), 2 * (q1[:, 1] - q0[:, 1])
            ka = ax2 * ldb - ay2 * lda
            kb = bx2 * ldb - by2 * lda
            kc = (q0[:, 0] - la) * ldb - (q0[:, 1] - lb) * lda
            for root in _roots2(ka, kb, kc):
                px = (ax2 * root + bx2) * root + q0[:, 0]
                py = (ay2 * root + by2) * root + q0[:, 1]
                t = ((px - la) * lda + (py - lb) * ldb) / (lda * lda + ldb * ldb)
                apart = np.hypot(la + t * lda - px, lb + t * ldb - py)
                near = (
                    np.isfinite(t)
                    & (root >= -1e-9)
                    & (root <= 1.0 + 1e-9)
                    & (apart <= _MEET / 2)
                )
                rows.append(line[row[near]])
                places.append(t[near])
        row = np.concatenate(rows) if rows else np.zeros(0, dtype=np.intp)
        t = np.concatenate(places) if places else np.zeros(0)
        order = np.argsort(row, kind="stable")
        row, t = row[order], t[order]
        count = np.bincount(row, minlength=len(a))
        packed = np.full((len(a), int(count.max(initial=0))), np.nan)
        rank = np.arange(len(row)) - np.repeat(np.cumsum(count) - count, count)
        packed[row, rank] = t
        return packed

    def implicit(self, a: Array, b: Array) -> tuple[list[Array], list[int]]:
        """Each stretch's curve carried on past its ends, as a polynomial of the point: a line's, or the parabola's (λ1² - 4 λ0 λ2 in the control triangle's barycentric coordinates)."""
        values: list[Array] = []
        degrees: list[int] = []
        for edge in self.edges:
            (x0, y0), (x1, y1), (x2, y2) = edge.q
            if _straight(edge.q):
                values.append((y2 - y0) * (a - x0) - (x2 - x0) * (b - y0))
                degrees.append(1)
                continue
            area = (x1 - x0) * (y2 - y0) - (y1 - y0) * (x2 - x0)
            l0 = ((x1 - a) * (y2 - b) - (y1 - b) * (x2 - a)) / area
            l1 = ((x2 - a) * (y0 - b) - (y2 - b) * (x0 - a)) / area
            l2 = ((x0 - a) * (y1 - b) - (y0 - b) * (x1 - a)) / area
            values.append(l1 * l1 - 4 * l0 * l2)
            degrees.append(2)
        return values, degrees


def _left(q: Quad, t: float) -> Point:
    vx, vy = _velocity(q, t)
    if (
        vx == 0.0 and vy == 0.0
    ):  # a piece whose control sits on an end: its way there is to the other end
        vx, vy = q[2][0] - q[0][0], q[2][1] - q[0][1]
    length = math.hypot(vx, vy)
    return -vy / length, vx / length


def _left_of(p0: Array, p1: Array, p2: Array, t: Array) -> tuple[Array, Array]:
    """The unit normal to the left of the way each piece (rows of points) runs, at its ``t``."""
    vx = (1 - t) * (p1[:, 0] - p0[:, 0]) + t * (p2[:, 0] - p1[:, 0])
    vy = (1 - t) * (p1[:, 1] - p0[:, 1]) + t * (p2[:, 1] - p1[:, 1])
    still = (vx == 0.0) & (
        vy == 0.0
    )  # a piece whose control sits on an end: its way there is to the other end
    vx = np.where(still, p2[:, 0] - p0[:, 0], vx)
    vy = np.where(still, p2[:, 1] - p0[:, 1], vy)
    length = np.hypot(vx, vy)
    return -vy / length, vx / length


def _left_many(q: Quad, t: Array) -> tuple[Array, Array]:
    """The unit normal to the left of the way one piece runs, at each ``t``."""
    n = np.shape(t)[0]
    rows = [np.broadcast_to(np.asarray(p, dtype=float), (n, 2)) for p in q]
    return _left_of(rows[0], rows[1], rows[2], np.asarray(t, dtype=float))


def _roots2(qa: Array, qb: Array, qc: Array) -> tuple[Array, Array]:
    """The real roots of ``qa s² + qb s + qc``, elementwise: two arrays, NaN where none (one where it is straight)."""
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        disc = qb * qb - 4 * qa * qc
        root = np.sqrt(np.where(disc >= 0, disc, np.nan))
        q_ = -0.5 * (qb + np.where(qb >= 0, root, -root))
        flat = qa == 0
        r1 = np.where(flat, -qc / qb, q_ / qa)
        r2 = np.where(flat, np.nan, qc / q_)
    return (
        np.where(np.isfinite(r1), r1, np.nan),
        np.where(np.isfinite(r2), r2, np.nan),
    )


def _to_quad(q: Quad, px: Array, py: Array) -> tuple[Array, Array]:
    """Each point's distance to one quadratic piece, and where on it the nearest point is (:func:`_to_quads`)."""
    n = np.shape(px)[0]
    rows = [np.broadcast_to(np.asarray(p, dtype=float), (n, 2)) for p in q]
    return _to_quads(
        rows[0],
        rows[1],
        rows[2],
        np.asarray(px, dtype=float),
        np.asarray(py, dtype=float),
    )


def _to_quads(
    p0: Array, p1: Array, p2: Array, px: Array, py: Array
) -> tuple[Array, Array]:
    """Each point's distance to its quadratic piece (rows of points), exactly, and where on it the nearest point is.

    With B(t) = P0 + 2 b t + a t² (a = P0 - 2 P1 + P2, b = P1 - P0), the
    nearest point is at an end or where (B(t) - p) . B'(t) = 0: the cubic
    (a.a) t³ + 3 (a.b) t² + (2 b.b + a.d) t + b.d (d = P0 - p). Its real
    roots come in closed form (Cardano's, or the trigonometric form where
    all three are real), each polished by Newton's method; the nearest of
    them in [0, 1] and the ends is the point.
    """
    x0, y0, x1, y1, x2, y2 = p0[:, 0], p0[:, 1], p1[:, 0], p1[:, 1], p2[:, 0], p2[:, 1]
    ax, ay = x0 - 2 * x1 + x2, y0 - 2 * y1 + y2
    bx, by = x1 - x0, y1 - y0
    dx, dy = x0 - px, y0 - py
    c3 = ax * ax + ay * ay
    c2 = 3 * (ax * bx + ay * by)
    c1 = 2 * (bx * bx + by * by) + ax * dx + ay * dy
    c0 = bx * dx + by * dy

    def dist(t: Array) -> Array:
        u = 1.0 - t
        qx = u * u * x0 + 2 * u * t * x1 + t * t * x2
        qy = u * u * y0 + 2 * u * t * y1 + t * t * y2
        found: Array = np.hypot(qx - px, qy - py)
        return found

    zero, one = np.zeros(np.shape(px)), np.ones(np.shape(px))
    straight = (
        c3 == 0.0
    )  # straight and evenly paced (c2 is 0 too): the root of c1 t + c0
    safe = np.where(straight, 1.0, c3)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        a_, b_, c_ = c2 / safe, c1 / safe, c0 / safe
        p = b_ - a_ * a_ / 3
        q_ = 2 * a_**3 / 27 - a_ * b_ / 3 + c_
        disc = (q_ / 2) ** 2 + (p / 3) ** 3
        shift = -a_ / 3
        root = np.sqrt(np.maximum(disc, 0.0))
        one_real = np.cbrt(-q_ / 2 + root) + np.cbrt(-q_ / 2 - root) + shift
        m = 2 * np.sqrt(np.maximum(-p / 3, 0.0))
        angle = (
            np.arccos(np.clip(np.where(p < 0, 3 * q_ / (p * m), 0.0), -1.0, 1.0)) / 3
        )
        line = np.where(c1 != 0.0, -c0 / np.where(c1 != 0.0, c1, 1.0), 0.0)
    roots = [
        np.where(
            straight,
            line,
            np.where(
                disc > 0, one_real, m * np.cos(angle - 2 * math.pi * k / 3) + shift
            ),
        )
        for k in range(3)
    ]
    d0, d1 = dist(zero), dist(one)
    found_d = np.minimum(d0, d1)
    found_t = np.where(d1 < d0, one, zero)
    for t in roots:
        t = np.clip(np.nan_to_num(t), 0.0, 1.0)
        for _ in range(2):  # Newton's method on the cubic, kept within [0, 1]
            g = ((c3 * t + c2) * t + c1) * t + c0
            dg = (3 * c3 * t + 2 * c2) * t + c1
            with np.errstate(divide="ignore", invalid="ignore"):
                t = np.clip(
                    np.where(dg != 0.0, t - g / np.where(dg != 0.0, dg, 1.0), t),
                    0.0,
                    1.0,
                )
        d = dist(t)
        better = d < found_d
        found_d = np.where(better, d, found_d)
        found_t = np.where(better, t, found_t)
    return found_d, found_t


# ----------------------------------------------------------------------
# As the oracle's solids
# ----------------------------------------------------------------------
@dataclass(frozen=True, eq=False)
class Letters2D(Shape2D):
    """A line's letters as an outline in a prism's plane: the region of nonzero winding, its edge the ink's (not convex)."""

    ink: Ink
    #: The letters' finest detail (the gap under an accent, a letter's eye): about a tenth of a capital.
    finest: float
    lo: tuple[float, float] = field(init=False)
    hi: tuple[float, float] = field(init=False)

    def __post_init__(self) -> None:
        if self.ink.box is None:
            raise ValueError("letters with no ink have no outline")
        object.__setattr__(self, "lo", self.ink.box[0])
        object.__setattr__(self, "hi", self.ink.box[1])

    def inside(self, a: Array, b: Array) -> NDArray[np.bool_]:
        return self.ink.inside(a, b)

    def pieces(self) -> list[tuple[str, tuple[float, ...]]]:
        raise NotImplementedError("letters' edge is quadratic arcs: ask the ink")

    def edge(self, a: Array, b: Array) -> tuple[Array, Array, Array, Array, Array]:
        return self.ink.nearest(a, b)

    def distance(self, a: Array, b: Array) -> Array:
        return self.ink.distance(a, b)

    def sd(self, a: Array, b: Array) -> Array:
        return self.ink.signed_distance(a, b)

    def facet_normals(self, a: Array, b: Array, eps: float) -> Array:
        return self.ink.facets(a, b, eps)[0]

    def meets(self, a: Array, b: Array, da: Array, db: Array) -> Array:
        return self.ink.meets(a, b, da, db)


@dataclass(frozen=True)
class LetterPrism(Prism):
    """A line's letters pushed along the frame's third axis from ``t0`` to ``t1``: engraved, or embossed.

    As any prism, but its outline isn't convex: near an inside corner of the
    letters' edge the solid is the union of its two walls' half-spaces
    (taken together, :class:`~forge_checks.shapes.Local` ``groups``), and
    where such a corner meets the floor or the top, that union met with the
    floor's or top's half-space. Only where three ways of the edge meet is no
    first-order model given (unsure).
    """

    def crossings(self, origins: Array, directions: Array) -> Array:
        """Where each line meets the letters' surface (as :meth:`~forge_checks.shapes.Solid.crossings` says), settled without a distance for each place on a wall.

        A wall's place (:meth:`Ink.meets`) is on the edge already, so it is
        on the surface where it is between the floor and the top (or within
        :data:`~forge_checks.shapes._MEET` past them, as a signed distance
        would say); a floor's or top's place, where the letters (or the
        edge, within that) are there.
        """
        assert isinstance(self.shape, Letters2D)
        found = self._candidates(origins, directions)
        if not found.size:
            return found
        a, b, c = self.frame.local(origins)
        da, db, dc = (
            directions @ np.asarray(x)
            for x in (self.frame.u, self.frame.v, self.frame.w)
        )
        walls = found[:, 2:]
        height = c[:, None] + walls * dc[:, None]
        walls[~((height >= self.t0 - _MEET) & (height <= self.t1 + _MEET))] = np.nan
        for k in (0, 1):  # the floor's and the top's places
            line = np.flatnonzero(np.isfinite(found[:, k]))
            pa, pb = (
                a[line] + found[line, k] * da[line],
                b[line] + found[line, k] * db[line],
            )
            ink = self.shape.ink
            off = ~ink.inside(pa, pb)
            off[off] = ink.distance(pa[off], pb[off]) > _MEET
            found[line[off], k] = np.nan
        return found

    def _candidates(self, origins: Array, directions: Array) -> Array:
        """As any prism's, but a cap's place off the letters' box (grown by :data:`~forge_checks.shapes._MEET`) is left out: it is farther than that from the letters, so on no surface of them."""
        assert isinstance(self.shape, Letters2D)
        found = super()._candidates(origins, directions)
        a, b, _ = self.frame.local(origins)
        da, db = (directions @ np.asarray(x) for x in (self.frame.u, self.frame.v))
        (x0, y0), (x1, y1) = self.shape.lo, self.shape.hi
        for k in (0, 1):  # the floor's and the top's places
            pa, pb = a + found[:, k] * da, b + found[:, k] * db
            off = (
                (pa < x0 - _MEET)
                | (pa > x1 + _MEET)
                | (pb < y0 - _MEET)
                | (pb > y1 + _MEET)
            )
            found[off, k] = np.nan
        return found

    def _implicit(self, points: Array) -> tuple[Array, tuple[int, ...]]:
        assert isinstance(self.shape, Letters2D)
        a, b, c = self.frame.local(points)
        values, degrees = self.shape.ink.implicit(a, b)
        return np.stack([c - self.t0, c - self.t1, *values], axis=1), (1, 1, *degrees)

    def locals(self, points: Array, eps: float = ON) -> Locals:
        assert isinstance(self.shape, Letters2D)
        a, b, c, d2, dz = self._parts(points)
        inside = np.minimum(np.maximum(d2, dz), 0.0)
        sd = inside + np.hypot(np.maximum(d2, 0.0), np.maximum(dz, 0.0))
        side, inner, crowded = self.shape.ink.facets(a, b, eps)
        along = (c >= self.t0 - eps) & (c <= self.t1 + eps)
        side[~along] = np.nan
        inner &= along
        crowded &= along
        u, v, w = (np.asarray(x) for x in (self.frame.u, self.frame.v, self.frame.w))
        normals = np.full((len(points), 4, 3), np.nan)
        normals[:, :2] = side[:, :, 0:1] * u + side[:, :, 1:2] * v
        rim = d2 <= eps
        normals[rim & (np.abs(c - self.t0) <= eps), 2] = -w
        normals[rim & (np.abs(c - self.t1) <= eps), 3] = w
        # Each facet its own group, but an inside corner's two walls: one group, either holds.
        groups = np.tile(np.arange(4, dtype=np.int64), (len(points), 1))
        groups[inner, 1] = 0
        found = _locals(np.asarray(sd), eps, normals, crowded)
        return Locals(found.where, found.normals, False, groups)

    def own_patches(self) -> list[Patch]:
        """Each stretch of the letters' edge pushed from ``t0`` to ``t1`` (a wall), and the outline at each end (a floor, a top)."""
        assert isinstance(self.shape, Letters2D)
        f = self.frame
        o, u, v, w = (np.asarray(x, dtype=float) for x in (f.origin, f.u, f.v, f.w))
        found: list[Patch] = [
            WallPatch(self, edge, self.t0, self.t1) for edge in self.shape.ink.edges
        ]
        for t, sign in ((self.t0, -1.0), (self.t1, 1.0)):
            found.append(
                FlatPatch(
                    self, _vec(o + t * w), _vec(u), _vec(v), _vec(sign * w), self.shape
                )
            )
        return found


def _vec(a: Array) -> tuple[float, float, float]:
    return float(a[0]), float(a[1]), float(a[2])


@dataclass(frozen=True)
class WallPatch(Patch):
    """A stretch of the letters' edge pushed along the prism's third axis from ``t0`` to ``t1``.

    Its first parameter runs along the stretch at the pace of its fastest
    point (``u = t * speed``), so a step of it moves a point no farther than
    the step; its second, along the prism.
    """

    owner: LetterPrism
    edge: Edge
    t0: float
    t1: float
    size: tuple[float, float] = field(init=False)
    speed: float = field(init=False)
    bounds: tuple[tuple[float, float, float], tuple[float, float, float]] = field(
        init=False
    )

    def __post_init__(self) -> None:
        (x0, y0), (x1, y1), (x2, y2) = self.edge.q
        speed = 2 * max(math.hypot(x1 - x0, y1 - y0), math.hypot(x2 - x1, y2 - y1))
        object.__setattr__(self, "speed", max(speed, 1e-12))
        object.__setattr__(self, "size", (self.speed, self.t1 - self.t0))
        h0, k0, h1, k1 = _hull(self.edge.q)
        corners = self._world(
            np.array([h0, h1, h0, h1] * 2),
            np.array([k0, k0, k1, k1] * 2),
            np.array([self.t0] * 4 + [self.t1] * 4),
        )
        object.__setattr__(
            self, "bounds", (_vec(corners.min(axis=0)), _vec(corners.max(axis=0)))
        )

    def _world(self, a: Array, b: Array, c: Array) -> Array:
        return self.owner.frame.world(a, b, c)

    def box(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        return self.bounds

    def at(self, u: Array, v: Array) -> tuple[Array, Array, NDArray[np.bool_]]:
        t = np.clip(u / self.speed, 0.0, 1.0)
        q = self.edge.q
        s = 1.0 - t
        a = s * s * q[0][0] + 2 * s * t * q[1][0] + t * t * q[2][0]
        b = s * s * q[0][1] + 2 * s * t * q[1][1] + t * t * q[2][1]
        lx, ly = _left_many(q, t)
        na, nb = -self.edge.side * lx, -self.edge.side * ly
        points = self._world(a, b, self.t0 + v)
        normals = self.owner.frame.turn(na, nb, np.zeros_like(na))
        return points, normals, np.ones(len(u), dtype=bool)

    def foot(self, x: Array) -> Array:
        f = self.owner.frame
        d = np.asarray(x, dtype=float) - np.asarray(f.origin)
        a, b, c = (
            float(d @ np.asarray(f.u)),
            float(d @ np.asarray(f.v)),
            float(d @ np.asarray(f.w)),
        )
        t = _nearest_t(self.edge.q, a, b)
        (x0, y0), (x1, y1), (x2, y2) = self.edge.q
        s = 1.0 - t
        qa, qb = (
            s * s * x0 + 2 * s * t * x1 + t * t * x2,
            s * s * y0 + 2 * s * t * y1 + t * t * y2,
        )
        qc = min(max(c, self.t0), self.t1)
        return (
            np.asarray(f.origin)
            + qa * np.asarray(f.u)
            + qb * np.asarray(f.v)
            + qc * np.asarray(f.w)
        )


def _nearest_t(q: Quad, px: float, py: float) -> float:
    """Where on one piece the point of it nearest (px, py) is: :func:`_to_quad` for one point, in plain arithmetic."""
    (x0, y0), (x1, y1), (x2, y2) = q
    ax, ay = x0 - 2 * x1 + x2, y0 - 2 * y1 + y2
    bx, by = x1 - x0, y1 - y0
    dx, dy = x0 - px, y0 - py
    c3 = ax * ax + ay * ay
    c2 = 3 * (ax * bx + ay * by)
    c1 = 2 * (bx * bx + by * by) + ax * dx + ay * dy
    c0 = bx * dx + by * dy

    def dist2(t: float) -> float:
        u = 1.0 - t
        qx = u * u * x0 + 2 * u * t * x1 + t * t * x2 - px
        qy = u * u * y0 + 2 * u * t * y1 + t * t * y2 - py
        return qx * qx + qy * qy

    if c3 == 0.0:
        roots = [-c0 / c1] if c1 != 0.0 else []
    else:
        a_, b_, c_ = c2 / c3, c1 / c3, c0 / c3
        p = b_ - a_ * a_ / 3
        q_ = 2 * a_**3 / 27 - a_ * b_ / 3 + c_
        disc = (q_ / 2) ** 2 + (p / 3) ** 3
        shift = -a_ / 3
        if disc > 0:
            root = math.sqrt(disc)
            roots = [math.copysign(abs(-q_ / 2 + root) ** (1 / 3), -q_ / 2 + root)
                     + math.copysign(abs(-q_ / 2 - root) ** (1 / 3), -q_ / 2 - root) + shift]  # fmt: skip
        else:
            m = 2 * math.sqrt(max(-p / 3, 0.0))
            angle = (
                math.acos(max(-1.0, min(1.0, 3 * q_ / (p * m)))) / 3 if p < 0 else 0.0
            )
            roots = [
                m * math.cos(angle - 2 * math.pi * k / 3) + shift for k in range(3)
            ]
    best_t, best = (1.0, dist2(1.0)) if dist2(1.0) < dist2(0.0) else (0.0, dist2(0.0))
    for t in roots:
        t = min(max(t, 0.0), 1.0)
        for _ in range(2):
            g = ((c3 * t + c2) * t + c1) * t + c0
            dg = (3 * c3 * t + 2 * c2) * t + c1
            if dg != 0.0:
                t = min(max(t - g / dg, 0.0), 1.0)
        d = dist2(t)
        if d < best:
            best_t, best = t, d
    return best_t
