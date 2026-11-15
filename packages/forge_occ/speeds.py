"""How fast a face's surface moves with its parameters: proved bounds, piece by piece (for ``BrepView.coverage``).

A face's parameters (``u0`` to ``u1`` by ``v0`` to ``v1``) are cut into pieces along each
direction, and each piece has a bound on the surface's speed there:
``|∂S/∂u| ≤ lu[i]`` over the i-th u piece (for every v of the face), and
``|∂S/∂v| ≤ lv[j]`` over the j-th v piece (for every u). A grid spaced by
these bounds piece by piece has, in every one of its cells, the bounds of
the pieces the cell lies in.

- Planes, cylinders, cones, spheres and tori: exact, one piece.
- B-spline and Bézier surfaces: from the control net, span by span. On a
  span only p + 1 poles act; writing the surface as Σ wᵢⱼ Pᵢⱼ Bᵢⱼ / W, its
  u-derivative there is
  (p/W) Σ Nᵢ,ₚ₋₁ Mⱼ [wᵢⱼ (Pᵢ₊₁,ⱼ - Pᵢⱼ) + (wᵢ₊₁,ⱼ - wᵢⱼ)(Pᵢⱼ - S)] / (tᵢ₊ₚ₊₁ - tᵢ₊₁)
  over the span's poles, the basis functions non-negative and summing to
  one, W no less than the span's smallest weight and |P - S| no more than
  the span's poles' diameter D (S lies in their hull). So on the span
  |∂S/∂u| ≤ (p / w_min) (w_max · max |ΔP|/Δt + D · max |Δw|/Δt), which
  for equal weights is p · max |ΔP| / Δt. Spans the bound finds slow to
  cover are split (knots inserted, which changes nothing of the surface)
  until splitting stops paying: the bound tends to the true speed as spans
  shrink.
- Extrusions: the basis curve's speed (the same bound, for curves) along
  u, one along v. Revolutions: along u, the basis curve's reach from the
  axis (greatest at a pole, distance from a line being convex); along v,
  its speed.
- Anything else (an offset of a B-spline): the largest speed found on a
  fine grid, doubled. The one bound here that is measured, not proved.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from numpy.typing import NDArray
from OCP.BRep import BRep_Tool
from OCP.collections import Array1_double as TColStd_Array1OfReal
from OCP.collections import Array1_int as TColStd_Array1OfInteger
from OCP.Geom import (
    Geom_BezierCurve,
    Geom_BSplineCurve,
    Geom_Circle,
    Geom_Line,
    Geom_RectangularTrimmedSurface,
    Geom_SurfaceOfLinearExtrusion,
    Geom_SurfaceOfRevolution,
    Geom_TrimmedCurve,
)
from OCP.GeomAbs import (
    GeomAbs_BezierSurface,
    GeomAbs_BSplineSurface,
    GeomAbs_Cone,
    GeomAbs_Cylinder,
    GeomAbs_Plane,
    GeomAbs_Sphere,
    GeomAbs_SurfaceOfExtrusion,
    GeomAbs_SurfaceOfRevolution,
    GeomAbs_Torus,
)
from OCP.GeomConvert import GeomConvert
from OCP.gp import gp_Pnt, gp_Vec

__all__ = ["Pieces", "nodes", "speeds"]

Array = NDArray[np.float64]

#: Rounds of splitting slow spans at most.
_ROUNDS = 12
#: A span is split while covering it would take more cells than this.
_SPLIT = 4.0
#: Splitting stops when a round saves less than this share of the cells.
_PAYS = 0.1
#: Poles a spline may grow to by splitting, at most.
_MOST_POLES = 250_000
#: Samples a side, measuring the speed of a surface no bound is proved for.
_MEASURED = 129


@dataclass(frozen=True)
class Pieces:
    """A face's parameters cut into pieces, with a bound on the surface's speed on each."""

    u: Array  # breaks, increasing, the face's u0 first and u1 last
    lu: Array  # |∂S/∂u| on each u piece, for every v
    v: Array
    lv: Array
    proved: bool = True


def nodes(breaks: Array, bounds: Array, step: float) -> Array:
    """Parameters from the first break to the last, each piece divided so its bound times a division is at most ``step``."""
    out = [float(breaks[0])]
    for a, b, bound in zip(breaks[:-1], breaks[1:], bounds, strict=True):
        count = max(1, math.ceil(float(bound) * (b - a) / step))
        out.extend(float(x) for x in np.linspace(a, b, count + 1)[1:])
    return np.asarray(out)


def _one(lo: float, hi: float, bound: float) -> tuple[Array, Array]:
    return np.array([lo, hi]), np.array([bound])


def speeds(
    face: Any, surface: Any, box: tuple[float, float, float, float], step: float
) -> Pieces:
    """Bounds on the speed of the face's surface over its parameters ``box``, for a grid of ``step``."""
    u0, u1, v0, v1 = box
    kind = surface.GetType()
    if kind == GeomAbs_Plane:
        return Pieces(*_one(u0, u1, 1.0), *_one(v0, v1, 1.0))
    if kind == GeomAbs_Cylinder:
        return Pieces(*_one(u0, u1, surface.Cylinder().Radius()), *_one(v0, v1, 1.0))
    if kind == GeomAbs_Cone:
        cone = surface.Cone()
        r, s = cone.RefRadius(), math.sin(cone.SemiAngle())
        return Pieces(
            *_one(u0, u1, max(abs(r + v0 * s), abs(r + v1 * s))), *_one(v0, v1, 1.0)
        )
    if kind == GeomAbs_Sphere:
        r = surface.Sphere().Radius()
        return Pieces(*_one(u0, u1, r), *_one(v0, v1, r))
    if kind == GeomAbs_Torus:
        torus = surface.Torus()
        return Pieces(
            *_one(u0, u1, torus.MajorRadius() + torus.MinorRadius()),
            *_one(v0, v1, torus.MinorRadius()),
        )
    if kind == GeomAbs_BSplineSurface:
        return _surface_pieces(surface.BSpline(), box, step)
    if kind == GeomAbs_BezierSurface:
        return _surface_pieces(
            GeomConvert.SurfaceToBSplineSurface_s(surface.Bezier()), box, step
        )
    geometry = BRep_Tool.Surface_s(face)
    while isinstance(geometry, Geom_RectangularTrimmedSurface):
        geometry = geometry.BasisSurface()
    if kind == GeomAbs_SurfaceOfExtrusion and isinstance(
        geometry, Geom_SurfaceOfLinearExtrusion
    ):
        along = _curve_pieces(geometry.BasisCurve(), (u0, u1), step, None)
        if along is not None:
            return Pieces(along[0], along[1], *_one(v0, v1, 1.0))
    if kind == GeomAbs_SurfaceOfRevolution and isinstance(
        geometry, Geom_SurfaceOfRevolution
    ):
        axis = geometry.Axis()
        along = _curve_pieces(
            geometry.BasisCurve(),
            (v0, v1),
            step,
            (_xyz(axis.Location()), _xyz(axis.Direction())),
        )
        if along is not None:
            return Pieces(*_one(u0, u1, along[2]), along[0], along[1])
    return _measured(surface, box)


# --- B-spline surfaces -------------------------------------------------------------


def _not_periodic(spline: Any) -> Any:
    piece = spline.Copy()
    if piece.IsUPeriodic():
        piece.SetUNotPeriodic()
    if piece.IsVPeriodic():
        piece.SetVNotPeriodic()
    return piece


def _flat(values: list[float], mults: list[int]) -> Array:
    return np.repeat(np.asarray(values, dtype=np.float64), mults)


def _surface_net(spline: Any) -> tuple[Array, Array, Array, Array, int, int]:
    nu, nv = spline.NbUPoles(), spline.NbVPoles()
    poles = np.empty((nu, nv, 3))
    weights = np.ones((nu, nv))
    rational = spline.IsURational() or spline.IsVRational()
    for i in range(nu):
        for j in range(nv):
            p = spline.Pole(i + 1, j + 1)
            poles[i, j] = (p.X(), p.Y(), p.Z())
            if rational:
                weights[i, j] = spline.Weight(i + 1, j + 1)
    uk = _flat([spline.UKnot(i) for i in range(1, spline.NbUKnots() + 1)],
               [spline.UMultiplicity(i) for i in range(1, spline.NbUKnots() + 1)])  # fmt: skip
    vk = _flat([spline.VKnot(i) for i in range(1, spline.NbVKnots() + 1)],
               [spline.VMultiplicity(i) for i in range(1, spline.NbVKnots() + 1)])  # fmt: skip
    return poles, weights, uk, vk, spline.UDegree(), spline.VDegree()


def _diameters(poles: Array, window: tuple[int, int]) -> Array:
    """The diameter of the bounding box of each window of poles."""
    spread = np.zeros(np.asarray(poles.shape[:2]) - np.asarray(window) + 1)
    for c in range(3):
        views = sliding_window_view(poles[:, :, c], window)
        spread += (views.max(axis=(-2, -1)) - views.min(axis=(-2, -1))) ** 2
    return np.sqrt(spread)


def _surface_bounds(spline: Any) -> tuple[Array, Array, Array, Array]:
    """Each span's interval along u and v, and bounds on |∂S/∂u| and |∂S/∂v| on each pair of spans."""
    poles, weights, uk, vk, p, q = _surface_net(spline)
    nu, nv = weights.shape
    # The spans: k from p to nu - 1 in u (knots uk[k] to uk[k + 1]), l from q to nv - 1 in v.
    u_spans = np.stack([uk[p:nu], uk[p + 1 : nu + 1]], axis=1)
    v_spans = np.stack([vk[q:nv], vk[q + 1 : nv + 1]], axis=1)
    w_lo = sliding_window_view(weights, (p + 1, q + 1)).min(axis=(-2, -1))
    w_hi = sliding_window_view(weights, (p + 1, q + 1)).max(axis=(-2, -1))
    reach = _diameters(poles, (p + 1, q + 1))

    def bound(
        direction: int, degree: int, knots: Array, window: tuple[int, int]
    ) -> Array:
        if degree == 0:
            return np.zeros_like(w_lo)
        dp = np.linalg.norm(np.diff(poles, axis=direction), axis=2)
        dw = np.abs(np.diff(weights, axis=direction))
        count = dp.shape[direction]
        spans = knots[np.arange(count) + degree + 1] - knots[np.arange(count) + 1]
        over = np.where(spans > 0.0, 1.0 / np.where(spans > 0.0, spans, 1.0), 0.0)
        over = over[:, None] if direction == 0 else over[None, :]
        moved = sliding_window_view(dp * over, window).max(axis=(-2, -1))
        swung = sliding_window_view(dw * over, window).max(axis=(-2, -1))
        return np.asarray(degree * (w_hi * moved + reach * swung) / w_lo)

    lu = bound(0, p, uk, (p, q + 1))
    lv = bound(1, q, vk, (p + 1, q))
    return u_spans, v_spans, lu, lv


def _clip(spans: Array, lo: float, hi: float) -> tuple[Array, NDArray[np.intp]]:
    """The spans meeting [lo, hi] (and of some length), clipped to it, and which they were."""
    keep = (spans[:, 1] > spans[:, 0]) & (spans[:, 1] > lo) & (spans[:, 0] < hi)
    clipped = np.clip(spans[keep], lo, hi)
    return clipped, np.flatnonzero(keep)


def _breaks(clipped: Array) -> Array:
    return np.concatenate([clipped[:, 0], clipped[-1:, 1]])


def _insert(spline: Any, direction: int, at: Array) -> None:
    if not len(at):
        return
    knots = TColStd_Array1OfReal(1, len(at))
    mults = TColStd_Array1OfInteger(1, len(at))
    for i, k in enumerate(at):
        knots.SetValue(i + 1, float(k))
        mults.SetValue(i + 1, 1)
    if direction == 0:
        spline.InsertUKnots(knots, mults, 0.0, True)
    else:
        spline.InsertVKnots(knots, mults, 0.0, True)


def _surface_pieces(
    spline: Any, box: tuple[float, float, float, float], step: float
) -> Pieces:
    """The surface's pieces over ``box``, its slow spans split while that pays.

    A rational surface's bound shrinks with its spans in both directions (the
    poles' spread and the weights' both shrink), so the two are split
    together, and judged together: by the grid the bounds would make.
    """
    u0, u1, v0, v1 = box
    piece = _not_periodic(spline)
    best: tuple[float, Pieces] | None = None
    for _ in range(_ROUNDS + 1):
        u_spans, v_spans, lu, lv = _surface_bounds(piece)
        cu, ku = _clip(u_spans, u0, u1)
        cv, kv = _clip(v_spans, v0, v1)
        if not len(ku) or not len(kv):
            raise RuntimeError(f"a face's parameters {box} lie outside its surface's")
        # Over the face only: each u span's bound over the face's v spans, and the reverse.
        bu = lu[np.ix_(ku, kv)].max(axis=1)
        bv = lv[np.ix_(ku, kv)].max(axis=0)
        need_u = bu * (cu[:, 1] - cu[:, 0]) / step
        need_v = bv * (cv[:, 1] - cv[:, 0]) / step
        grid = float((need_u.sum() + len(cu)) * (need_v.sum() + len(cv)))
        before = best[0] if best is not None else math.inf
        if grid < before:
            best = (grid, Pieces(_breaks(cu), bu, _breaks(cv), bv))
        if grid > (1.0 - _PAYS) * before:
            break
        split_u = (cu[:, 0] + cu[:, 1])[need_u > _SPLIT] / 2.0
        split_v = (cv[:, 0] + cv[:, 1])[need_v > _SPLIT] / 2.0
        grown = (piece.NbUPoles() + len(split_u)) * (piece.NbVPoles() + len(split_v))
        if (not len(split_u) and not len(split_v)) or grown > _MOST_POLES:
            break
        _insert(piece, 0, split_u)
        _insert(piece, 1, split_v)
    assert best is not None
    return best[1]


# --- curves (the basis curves of extrusions and revolutions) -------------------------


def _curve_spline(curve: Any) -> Any | None:
    """The curve as a B-spline with the same parameters (Bézier and B-spline curves), not periodic; None for any other."""
    while isinstance(curve, Geom_TrimmedCurve):
        curve = curve.BasisCurve()
    if isinstance(curve, Geom_BezierCurve):
        return GeomConvert.CurveToBSplineCurve_s(curve)
    if isinstance(curve, Geom_BSplineCurve):
        spline = curve.Copy()
        if spline.IsPeriodic():
            spline.SetNotPeriodic()
        return spline
    return None


def _reach(points: Array, line: tuple[Array, Array] | None) -> Array:
    if line is None:
        return np.zeros(len(points))
    origin, direction = line
    rel = points - origin
    return np.asarray(
        np.linalg.norm(rel - np.outer(rel @ direction, direction), axis=1)
    )


def _curve_pieces(curve: Any, range_: tuple[float, float], step: float,
                  line: tuple[Array, Array] | None) -> tuple[Array, Array, float] | None:  # fmt: skip
    """A swept surface's basis curve over ``range_``: its pieces, its speed on each, and its greatest reach from ``line``.

    Lines and circles exactly (a line's reach is greatest at an end, a
    circle's no more than its centre's plus its radius); Bézier and B-spline
    curves span by span; None for any other curve.
    """
    lo, hi = range_
    basis = curve
    while isinstance(basis, Geom_TrimmedCurve):
        basis = basis.BasisCurve()
    if isinstance(basis, Geom_Line):
        ends = np.array([_xyz(basis.Value(lo)), _xyz(basis.Value(hi))])
        return np.array([lo, hi]), np.array([1.0]), float(_reach(ends, line).max())
    if isinstance(basis, Geom_Circle):
        circle = basis.Circ()
        centre = _xyz(circle.Location())[None, :]
        return (
            np.array([lo, hi]),
            np.array([circle.Radius()]),
            float(_reach(centre, line)[0] + circle.Radius()),
        )
    spline = _curve_spline(basis)
    if spline is None:
        return None
    best: tuple[float, tuple[Array, Array, float]] | None = None
    for _ in range(_ROUNDS + 1):
        spans, speed, reach = _curve_bounds(spline, line)
        clipped, kept = _clip(spans, lo, hi)
        if not len(kept):
            raise RuntimeError(f"a face's parameters {range_} lie outside its curve's")
        need = speed[kept] * (clipped[:, 1] - clipped[:, 0]) / step
        total = float(need.sum())
        before = best[0] if best is not None else math.inf
        if total < before:
            best = (total, (_breaks(clipped), speed[kept], float(reach[kept].max())))
        if total > (1.0 - _PAYS) * before:
            break
        split = (clipped[:, 0] + clipped[:, 1])[need > _SPLIT] / 2.0
        if not len(split) or spline.NbPoles() + len(split) > _MOST_POLES:
            break
        knots = TColStd_Array1OfReal(1, len(split))
        mults = TColStd_Array1OfInteger(1, len(split))
        for i, k in enumerate(split):
            knots.SetValue(i + 1, float(k))
            mults.SetValue(i + 1, 1)
        spline.InsertKnots(knots, mults, 0.0, True)
    assert best is not None
    return best[1]


def _curve_bounds(
    spline: Any, line: tuple[Array, Array] | None
) -> tuple[Array, Array, Array]:
    """Each span's interval, a bound on the curve's speed on it, and its reach from ``line`` there."""
    n, p = spline.NbPoles(), spline.Degree()
    poles = np.array([_xyz(spline.Pole(i)) for i in range(1, n + 1)])
    weights = np.array([spline.Weight(i) for i in range(1, n + 1)])
    knots = _flat([spline.Knot(i) for i in range(1, spline.NbKnots() + 1)],
                  [spline.Multiplicity(i) for i in range(1, spline.NbKnots() + 1)])  # fmt: skip
    spans = np.stack([knots[p:n], knots[p + 1 : n + 1]], axis=1)
    w_lo = sliding_window_view(weights, p + 1).min(axis=-1)
    w_hi = sliding_window_view(weights, p + 1).max(axis=-1)
    width = np.zeros(n - p)
    for c in range(3):
        views = sliding_window_view(poles[:, c], p + 1)
        width += (views.max(axis=-1) - views.min(axis=-1)) ** 2
    width = np.sqrt(width)
    if p == 0:
        speed = np.zeros(n - p)
    else:
        dp = np.linalg.norm(np.diff(poles, axis=0), axis=1)
        dw = np.abs(np.diff(weights))
        lengths = knots[np.arange(n - 1) + p + 1] - knots[np.arange(n - 1) + 1]
        over = np.where(lengths > 0.0, 1.0 / np.where(lengths > 0.0, lengths, 1.0), 0.0)
        moved = sliding_window_view(dp * over, p).max(axis=-1)
        swung = sliding_window_view(dw * over, p).max(axis=-1)
        speed = p * (w_hi * moved + width * swung) / w_lo
    reach = sliding_window_view(_reach(poles, line), p + 1).max(axis=-1)
    return spans, speed, reach


# --- measured ------------------------------------------------------------------------


def _measured(surface: Any, box: tuple[float, float, float, float]) -> Pieces:
    """The largest speeds found on a fine grid, doubled (for a surface no bound is proved for)."""
    u0, u1, v0, v1 = box
    p, du, dv = gp_Pnt(), gp_Vec(), gp_Vec()
    lu = lv = 0.0
    for u in np.linspace(u0, u1, _MEASURED):
        for v in np.linspace(v0, v1, _MEASURED):
            surface.D1(float(u), float(v), p, du, dv)
            lu, lv = max(lu, du.Magnitude()), max(lv, dv.Magnitude())
    return Pieces(*_one(u0, u1, 2.0 * lu), *_one(v0, v1, 2.0 * lv), proved=False)


def _xyz(p: Any) -> Array:
    return np.array([p.X(), p.Y(), p.Z()], dtype=np.float64)
