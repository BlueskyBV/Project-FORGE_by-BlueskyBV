"""Which points of a face's parameter plane lie on the face: many at once (docs/V2-stage4.md 13.2).

OpenCascade's own classifier (``IntTools_FClass2d``, ``BRepTopAdaptor_FClass2d`` before OpenCascade 8) answers one point
at a time, about 8 µs each from Python: a coverage of a part at the checks'
radius asks it for half a million grid points. Here a face's boundary is
read once (:func:`read`), edge by edge in the face's parameters (each edge's
curve on the face), and every point is classified by the parity of the
boundary's crossings above it (a ray in +v), in NumPy:

- the boundary is cut into pieces each monotone in u: a straight piece as
  it is, a circular arc at its points of least and greatest u, any other
  curve (an intersection curve, a B-spline) followed by a fine polygon;
- a piece crosses the ray from ``(u, v)`` when ``u`` lies in ``[least,
  greatest)`` of its ends' u, above ``v``: half open, so a ray through a
  vertex or touching a circle counts as it must, and every closed chain is
  crossed an even number of times;
- each edge's end is joined to the nearest start of an edge (a gap between
  two edges' curves, a few nanometres, closed by a short straight piece), so
  the chains are closed exactly.

Exact pieces (straight, circular) answer exactly: a point within :data:`ON`
of one is on the boundary, so on the face (OpenCascade's classifier says ON).
Where the boundary is followed or a gap closed, a point within a band round
it (four times the polygon's largest measured distance from the curve, or
the gap) is **unsure**: outside the band the polygon and the curve leave a
point on the same side. A grid (:func:`on_grid`, a coverage's) asks
OpenCascade's classifier at its unsure points, and at every point of a face
whose boundary can't be read so (no curve on the face for an edge, a circle
whose parameters aren't the usual); scattered points
(:meth:`Boundary.points`, a view's feet) are left unsure there for their
asker to settle, as :func:`in_face` does.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

import numpy as np
from forge_numeric import scalar as fs
from forge_numeric import vector as fv
from numpy.typing import NDArray
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepTools import BRepTools
from OCP.Geom2dAdaptor import Geom2dAdaptor_Curve
from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Line
from OCP.gp import gp_Pnt2d
from OCP.IntTools import IntTools_FClass2d
from OCP.TopAbs import TopAbs_EDGE, TopAbs_IN, TopAbs_OUT, TopAbs_REVERSED
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS

__all__ = ["FINE", "ON", "Boundary", "in_face", "on_grid", "read"]

Array = NDArray[np.float64]
Mask = NDArray[np.bool_]
Height = Callable[[NDArray[np.int64], Array], Array]

#: A point this close to a straight or circular piece is on the boundary (in the face's parameters).
ON = 1e-9
#: How many straight pieces at least follow a curve that is neither straight nor circular.
_FOLLOW = 64
#: How many at most.
_FOLLOW_MOST = 4096
#: The band round a followed curve left unsure, as a multiple of the polygon's measured error.
_BAND = 4.0
#: How narrow a followed curve's band is made (up to :data:`_FOLLOW_MOST` pieces), relative to the face's
#: parameter box: what falls in it is OpenCascade's to settle, slowly by the curve (a millisecond a point by a
#: thread's helical edge, against 0.06 elsewhere). At a ten-thousandth, the 49 mm boss of generated part 171
#: left 50,489 of its spec's points unsure; at a millionth, 2,410, its boundary read in 0.9 s, not 0.2.
_NARROW = 1e-6
#: How narrow the bands are made when a point is left in one (relative to the face's parameter box): a curve
#: followed by up to :data:`_FOLLOW_MOST` pieces then leaves unsure only what lies within a micrometre or so of it
#: (generated part 1057: a point 7e-6 mm inside a letter's top by a Bezier edge, in a band of 7.5e-5 mm at
#: :data:`_NARROW`, and OpenCascade's classifier calling it ON, settled on the face).
FINE = 1e-8
#: A gap between edges longer than this (relative to the face's parameter box) and the boundary isn't read.
_GAP = 1e-6


class _UnreadError(Exception):
    """A boundary this module doesn't read."""


@dataclass
class _Pieces:
    """A boundary's pieces as they are read."""

    a: list[Array] = field(default_factory=list)
    b: list[Array] = field(default_factory=list)
    band: list[float] = field(default_factory=list)
    centre: list[Array] = field(default_factory=list)
    radius: list[float] = field(default_factory=list)
    arc_a: list[Array] = field(default_factory=list)
    arc_b: list[Array] = field(default_factory=list)
    half: list[float] = field(default_factory=list)

    def line(self, a: Array, b: Array, band: float = 0.0) -> None:
        self.a.append(a)
        self.b.append(b)
        self.band.append(band)


def _rows(found: list[Array]) -> Array:
    return np.array(found, dtype=np.float64).reshape(-1, 2)


@dataclass(frozen=True, eq=False)
class Boundary:
    """A face's boundary in its parameters, as pieces each monotone in u.

    Straight pieces from ``a`` to ``b``, each with the band round it left
    unsure (0 for an exact one); circular arcs from ``arc_a`` to ``arc_b``
    about ``centre``, on the ``half`` of their circle above its centre (+1)
    or below (-1). ``box`` is the face's parameter box; ``periods`` the
    surface's periods in u and v (None where it has none).
    """

    box: tuple[float, float, float, float]
    periods: tuple[float | None, float | None]
    a: Array
    b: Array
    band: Array
    centre: Array
    radius: Array
    arc_a: Array
    arc_b: Array
    half: Array

    # --- heights where each piece crosses a line of constant u ---------------------
    def _line_height(self, k: NDArray[np.int64], u: Array) -> Array:
        a, b = self.a[k], self.b[k]
        du = b[:, 0] - a[:, 0]
        found: Array = a[:, 1] + (u - a[:, 0]) * (b[:, 1] - a[:, 1]) / np.where(
            du != 0, du, 1.0
        )
        return found

    def _arc_height(self, k: NDArray[np.int64], u: Array) -> Array:
        c, r = self.centre[k], self.radius[k]
        found: Array = c[:, 1] + self.half[k] * np.sqrt(
            np.maximum(r * r - fv.sq(u - c[:, 0]), 0.0)
        )
        return found

    def _arc_box(self, k: int, reach: float) -> tuple[float, float, float, float]:
        a, b, c = self.arc_a[k], self.arc_b[k], self.centre[k]
        ulo, uhi = min(a[0], b[0]), max(a[0], b[0])
        vlo, vhi = min(a[1], b[1]), max(a[1], b[1])
        if ulo < c[0] < uhi:  # the arc passes its circle's top or bottom
            top = c[1] + self.half[k] * self.radius[k]
            vlo, vhi = min(vlo, top), max(vhi, top)
        return ulo - reach, uhi + reach, vlo - reach, vhi + reach

    def _on_arc(self, k: int, u: Array, v: Array) -> Mask:
        a, b, c = self.arc_a[k], self.arc_b[k], self.centre[k]
        ulo, uhi = min(a[0], b[0]), max(a[0], b[0])
        d = fv.hypot(u - c[0], v - c[1])
        along = (
            (np.abs(d - self.radius[k]) <= ON)
            & (u >= ulo)
            & (u <= uhi)
            & (self.half[k] * (v - c[1]) >= -ON)
        )
        ends = (fv.hypot(u - a[0], v - a[1]) <= ON) | (
            fv.hypot(u - b[0], v - b[1]) <= ON
        )
        found: Mask = along | ends
        return found

    # --- a grid --------------------------------------------------------------------------
    def grid(self, us: Array, vs: Array) -> tuple[Mask, Mask]:
        """Each grid point (us[i], vs[j]): on the face (inside it, or within :data:`ON` of an exact piece), and unsure; (len(us), len(vs)) each.

        ``us`` and ``vs`` ascend. A point past the parameter box is off the face.
        """
        # A crossing above a point adds one to it: kept as differences along each column, summed up it.
        above = np.zeros((len(us), len(vs) + 1), dtype=np.int64)
        on = np.zeros((len(us), len(vs)), dtype=bool)
        unsure = np.zeros_like(on)
        for ua, ub, height in self._crossers():
            piece, column = _pairs(us, ua, ub)
            below = np.searchsorted(vs, height(piece, us[column]), "left")
            np.add.at(above, (column, np.zeros_like(column)), 1)
            np.add.at(above, (column, below), -1)
        for k in range(len(self.a)):
            reach = self.band[k] if self.band[k] > 0 else ON
            a, b = self.a[k], self.b[k]
            rows = _span(min(a[0], b[0]) - reach, max(a[0], b[0]) + reach, us)
            cols = _span(min(a[1], b[1]) - reach, max(a[1], b[1]) + reach, vs)
            if rows.start < rows.stop and cols.start < cols.stop:
                near = _distance(us[rows][:, None], vs[cols][None, :], a, b) <= reach
                (unsure if self.band[k] > 0 else on)[rows, cols] |= near
        for k in range(len(self.centre)):
            u0, u1, v0, v1 = self._arc_box(k, ON)
            rows, cols = _span(u0, u1, us), _span(v0, v1, vs)
            if rows.start < rows.stop and cols.start < cols.stop:
                on[rows, cols] |= self._on_arc(k, us[rows][:, None], vs[cols][None, :])
        found: Mask = ((np.cumsum(above[:, :-1], axis=1) % 2) == 1) | on
        return found, unsure & ~on

    # --- points anywhere -----------------------------------------------------------------
    def points(self, u: Array, v: Array) -> tuple[Mask, Mask]:
        """Each point (u[i], v[i]): on the face (inside it, or within :data:`ON` of an exact piece), and unsure.

        A point past the parameter box along a periodic direction is moved
        by a period into it first (as OpenCascade's classifier moves it).
        """
        u = np.array(u, dtype=np.float64).reshape(-1)
        v = np.array(v, dtype=np.float64).reshape(-1)
        u0, u1, v0, v1 = self.box
        for x, (lo, hi), period in (
            (u, (u0, u1), self.periods[0]),
            (v, (v0, v1), self.periods[1]),
        ):
            if period:
                past = (x < lo - ON) | (x > hi + ON)
                x[past] = lo + np.mod(x[past] - lo, period)
        on = np.zeros(len(u), dtype=bool)
        unsure = np.zeros(len(u), dtype=bool)
        rows = np.flatnonzero(
            (u >= u0 - ON) & (u <= u1 + ON) & (v >= v0 - ON) & (v <= v1 + ON)
        )
        if not len(rows):
            return on, unsure
        order = rows[np.argsort(u[rows], kind="stable")]
        su, sv = u[order], v[order]
        above = np.zeros(len(order), dtype=np.int64)
        for ua, ub, height in self._crossers():
            piece, point = _pairs(su, ua, ub)
            higher = height(piece, su[point]) > sv[point]
            above += np.bincount(point[higher], minlength=len(order))
        found_on = np.zeros(len(order), dtype=bool)
        found_unsure = np.zeros(len(order), dtype=bool)
        for k in range(len(self.a)):
            reach = self.band[k] if self.band[k] > 0 else ON
            a, b = self.a[k], self.b[k]
            span = _span(min(a[0], b[0]) - reach, max(a[0], b[0]) + reach, su)
            pu, pv = su[span], sv[span]
            near = (pv >= min(a[1], b[1]) - reach) & (pv <= max(a[1], b[1]) + reach)
            near &= _distance(pu, pv, a, b) <= reach
            (found_unsure if self.band[k] > 0 else found_on)[span] |= near
        for k in range(len(self.centre)):
            lo_u, hi_u, lo_v, hi_v = self._arc_box(k, ON)
            span = _span(lo_u, hi_u, su)
            pu, pv = su[span], sv[span]
            found_on[span] |= (pv >= lo_v) & (pv <= hi_v) & self._on_arc(k, pu, pv)
        on[order] = (above % 2 == 1) | found_on
        unsure[order] = found_unsure & ~found_on
        return on, unsure

    def _crossers(self) -> list[tuple[Array, Array, Height]]:
        return [
            (self.a[:, 0], self.b[:, 0], self._line_height),
            (self.arc_a[:, 0], self.arc_b[:, 0], self._arc_height),
        ]


def _pairs(
    sorted_u: Array, ua: Array, ub: Array
) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
    """Every piece with every place (an index into ``sorted_u``) whose u lies in [least, greatest) of its ends' u."""
    first = np.searchsorted(sorted_u, np.minimum(ua, ub), "left")
    count = np.searchsorted(sorted_u, np.maximum(ua, ub), "left") - first
    total = int(count.sum())
    piece = np.repeat(np.arange(len(ua)), count)
    place = first[piece] + (
        np.arange(total) - np.repeat(np.cumsum(count) - count, count)
    )
    return piece.astype(np.int64), place.astype(np.int64)


def _span(lo: float, hi: float, ascending: Array) -> slice:
    """The indices of an ascending array whose values lie within [lo, hi]."""
    return slice(
        int(np.searchsorted(ascending, lo, "left")),
        int(np.searchsorted(ascending, hi, "right")),
    )


def _distance(u: Array, v: Array, a: Array, b: Array) -> Array:
    """Each point's distance to the segment a-b (``u`` and ``v`` broadcast together)."""
    d = b - a
    length2 = float(fv.matmul(d, d))
    pu, pv = u - a[0], v - a[1]
    t = np.clip((pu * d[0] + pv * d[1]) / length2, 0.0, 1.0) if length2 > 0 else 0.0
    found: Array = fv.hypot(pu - t * d[0], pv - t * d[1])
    return found


# --- reading a boundary ------------------------------------------------------------------


def _point(curve: Any, t: float) -> Array:
    p = curve.Value(t)
    return np.array([p.X(), p.Y()])


def _circle(found: _Pieces, curve: Any, t0: float, t1: float) -> None:
    """A circular arc from parameter t0 to t1, cut at its points of least and greatest u."""
    circle = curve.Circle()
    c = circle.Location()
    centre = np.array([c.X(), c.Y()])
    radius = float(circle.Radius())
    x, y = circle.XAxis().Direction(), circle.YAxis().Direction()
    # u(t) = cu + R (cos t · Xu + sin t · Yu) is least or greatest where tan t = Yu / Xu.
    first = fs.atan2(y.X(), x.X())
    lo, hi = min(t0, t1), max(t0, t1)
    k = math.ceil((lo - first) / math.pi)
    cuts = []
    while first + k * math.pi < hi:
        t = first + k * math.pi
        if t > lo:
            cuts.append(t)
        k += 1
    params = [t0, *(cuts if t1 > t0 else cuts[::-1]), t1]
    points = [_point(curve, t) for t in params]
    for t, p in zip(params[1:-1], points[1:-1], strict=True):
        if abs(abs(p[0] - centre[0]) - radius) > 1e-9 * max(1.0, radius):
            raise _UnreadError(f"a circle's parameters aren't the usual at {t}")
    for (ta, tb), (pa, pb) in zip(pairwise(params), pairwise(points), strict=True):
        middle = _point(curve, (ta + tb) / 2)
        found.centre.append(centre)
        found.radius.append(radius)
        found.arc_a.append(pa)
        found.arc_b.append(pb)
        found.half.append(1.0 if middle[1] >= centre[1] else -1.0)


def _follow(
    found: _Pieces, curve: Any, t0: float, t1: float, scale: float, narrow: float
) -> None:
    """Any other curve: a polygon fine enough that its band is narrow beside the face (``narrow``, :data:`_NARROW` at first), each piece with the band."""
    n = _FOLLOW
    while True:
        ts = np.linspace(t0, t1, n + 1)
        points = np.array([_point(curve, float(t)) for t in ts])
        error = 0.0
        for share in (0.25, 0.5, 0.75):
            between = np.array(
                [_point(curve, float(t)) for t in ts[:-1] + share * (ts[1:] - ts[:-1])]
            )
            chord = points[:-1] + share * (points[1:] - points[:-1])
            error = max(error, float(np.max(fv.norm(between - chord, axis=1))))
        band = _BAND * error + ON
        if band <= narrow * scale or n >= _FOLLOW_MOST:
            break
        n *= 2
    for pa, pb in pairwise(points):
        found.line(pa, pb, band)


def _close(
    found: _Pieces, starts: list[Array], ends: list[Array], scale: float
) -> None:
    """Join each edge's end to the nearest free start: the chains closed exactly, each gap a banded piece."""
    if not starts:
        return
    s, e = np.array(starts), np.array(ends)
    gaps = fv.norm(e[:, None, :] - s[None, :, :], axis=2)
    end_free = np.ones(len(e), dtype=bool)
    start_free = np.ones(len(s), dtype=bool)
    for flat in np.argsort(gaps, axis=None):
        i, j = divmod(int(flat), len(s))
        if end_free[i] and start_free[j]:
            end_free[i] = start_free[j] = False
            gap = float(gaps[i, j])
            if gap > _GAP * scale:
                raise _UnreadError(f"a gap of {gap} between two edges on the face")
            if gap > 0.0:
                found.line(e[i], s[j], _BAND * gap + ON)


def read(face: Any, narrow: float = _NARROW) -> Boundary | None:
    """The face's boundary in its parameters; None where it can't be read so.

    ``narrow``: how narrow each followed curve's band is made, relative to the
    face's parameter box (:data:`_NARROW`; :data:`FINE` to settle a point
    left in a band, as a view's feet are).
    """
    found = _Pieces()
    starts: list[Array] = []
    ends: list[Array] = []
    u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
    scale = max(1.0, fs.hypot(u1 - u0, v1 - v0))
    try:
        explorer = TopExp_Explorer(face, TopAbs_EDGE)
        while explorer.More():
            edge = TopoDS.Edge(explorer.Current())
            explorer.Next()
            pcurve = BRep_Tool.CurveOnSurface_s(edge, face, 0.0, 0.0)
            if pcurve is None:
                raise _UnreadError("an edge has no curve on the face")
            t0, t1 = BRep_Tool.Range_s(edge, face)
            if edge.Orientation() == TopAbs_REVERSED:
                t0, t1 = t1, t0
            curve = Geom2dAdaptor_Curve(pcurve)
            kind = curve.GetType()
            a, b = _point(curve, t0), _point(curve, t1)
            starts.append(a)
            ends.append(b)
            if kind == GeomAbs_Line:
                found.line(a, b)
            elif kind == GeomAbs_Circle:
                _circle(found, curve, t0, t1)
            else:
                _follow(found, curve, t0, t1, scale, narrow)
        _close(found, starts, ends, scale)
    except _UnreadError:
        return None
    surface = BRepAdaptor_Surface(face, False)
    periods = (
        float(surface.UPeriod()) if surface.IsUPeriodic() else None,
        float(surface.VPeriod()) if surface.IsVPeriodic() else None,
    )
    return Boundary(
        (u0, u1, v0, v1), periods, _rows(found.a), _rows(found.b),
        np.array(found.band, dtype=np.float64), _rows(found.centre),
        np.array(found.radius, dtype=np.float64), _rows(found.arc_a), _rows(found.arc_b),
        np.array(found.half, dtype=np.float64),
    )  # fmt: skip


# --- a coverage's grid -------------------------------------------------------------------


def on_grid(face: Any, us: Array, vs: Array, *, strict: bool = False) -> Mask:
    """Whether each grid point (us[i], vs[j]) lies on the face, as a (len(us), len(vs)) array.

    On it: inside it, or on its boundary, where OpenCascade's classifier says
    IN or ON (asked where the answer here is unsure). ``us`` and ``vs``
    ascend. A point past the face's parameter box is off it (OpenCascade's
    classifier would move one by a period onto a periodic face first: a
    coverage asks only within the box).

    ``strict``: where OpenCascade is asked, its ON counts as off the face.
    Its ON reaches as far as its own polygons of the boundary's curves are
    from them (a micrometre past a curve a boolean made, at a seam's end), so
    a point it calls ON may lie past the face's neighbour: a coverage, whose
    edges are sampled on their own, asks so.
    """
    us, vs = np.asarray(us, dtype=np.float64), np.asarray(vs, dtype=np.float64)
    if np.any(np.diff(us) < 0) or np.any(np.diff(vs) < 0):
        raise ValueError("a grid's parameters must ascend")
    if not len(us) or not len(vs):
        return np.zeros((len(us), len(vs)), dtype=bool)
    boundary = read(face)
    if boundary is None:
        everywhere = np.ones((len(us), len(vs)), dtype=bool)
        return _by_opencascade(face, us, vs, everywhere, strict)
    found, unsure = boundary.grid(us, vs)
    if unsure.any():
        found[unsure] = _by_opencascade(face, us, vs, unsure, strict)[unsure]
    return found


def in_face(classifier: Any, u: Array, v: Array) -> Mask:
    """Whether each scattered point (u[i], v[i]) is inside the face, by OpenCascade's ``classifier`` (an
    ``IntTools_FClass2d`` of it, made with tolerance :data:`ON`): its IN alone, as a strict grid's (its ON
    may lie past the face's neighbour, :func:`on_grid`). It moves a point past a periodic face's parameter box by
    a period first.
    """
    out = np.zeros(len(u), dtype=bool)
    pairs = zip(np.asarray(u).tolist(), np.asarray(v).tolist(), strict=True)
    for k, (a, b) in enumerate(pairs):
        out[k] = classifier.Perform(gp_Pnt2d(a, b)) == TopAbs_IN
    return out


def _by_opencascade(
    face: Any, us: Array, vs: Array, which: Mask, strict: bool = False
) -> Mask:
    """OpenCascade's own answer at the grid points asked (False elsewhere): IN or ON, or IN alone (``strict``)."""
    classifier = IntTools_FClass2d(face, ON)
    out = np.zeros(which.shape, dtype=bool)
    for i, j in zip(*np.nonzero(which), strict=True):
        state = classifier.Perform(gp_Pnt2d(float(us[i]), float(vs[j])))
        out[i, j] = state == TopAbs_IN if strict else state != TopAbs_OUT
    return out
