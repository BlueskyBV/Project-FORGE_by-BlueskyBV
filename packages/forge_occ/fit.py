"""Cubic B-splines through points, at the parameters the points were taken at (for mapping curves and surfaces exactly enough).

A curve or surface carried through a map that OpenCascade has no exact form
for (V1's bend wrap, docs/V2-stage3.md, 7.3) is sampled at its own
parameters, each point mapped, and a cubic B-spline interpolated through the
mapped points **at the same parameters**: so a face's trimming curves, given
in its parameters, keep their meaning on the new surface, and an edge's curve
and its curves on its faces stay parameterised alike. The fit's error is
measured between the samples and refined until it is under the tolerance
asked, or refused.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from OCP.collections import Array1_double as TColStd_Array1OfReal
from OCP.collections import Array1_gp_Pnt as TColgp_Array1OfPnt
from OCP.collections import Array1_int as TColStd_Array1OfInteger
from OCP.collections import Array2_gp_Pnt as TColgp_Array2OfPnt
from OCP.Geom import Geom_BSplineCurve, Geom_BSplineSurface
from OCP.gp import gp_Pnt

from .errors import OperationError

__all__ = ["Fit", "fit_curve", "fit_surface"]

Array = NDArray[np.float64]
DEGREE = 3
#: The most samples a direction is refined to.
MOST = 257


def _knots(t: Array) -> Array:
    """Clamped cubic knots for interpolation at parameters ``t`` (de Boor's averaging)."""
    n = len(t)
    inner = [float(np.mean(t[i + 1 : i + DEGREE + 1])) for i in range(n - DEGREE - 1)]
    return np.array(
        [t[0]] * (DEGREE + 1) + inner + [t[-1]] * (DEGREE + 1), dtype=np.float64
    )


def _basis(knots: Array, t: Array) -> Array:
    """The collocation matrix: every cubic basis function at every parameter (Cox-de Boor)."""
    n = len(knots) - DEGREE - 1
    out = np.zeros((len(t), n))
    for row, x in enumerate(t):
        # The span holding x (the last span for x at the end).
        span = int(np.searchsorted(knots, x, side="right") - 1)
        span = min(max(span, DEGREE), n - 1)
        values = np.zeros(DEGREE + 1)
        values[0] = 1.0
        left = np.zeros(DEGREE + 1)
        right = np.zeros(DEGREE + 1)
        for j in range(1, DEGREE + 1):
            left[j] = x - knots[span + 1 - j]
            right[j] = knots[span + j] - x
            saved = 0.0
            for r in range(j):
                denominator = right[r + 1] + left[j - r]
                temp = values[r] / denominator if denominator else 0.0
                values[r] = saved + right[r + 1] * temp
                saved = left[j - r] * temp
            values[j] = saved
        out[row, span - DEGREE : span + 1] = values
    return out


def _distinct(knots: Array) -> tuple[list[float], list[int]]:
    values: list[float] = []
    mults: list[int] = []
    for k in knots:
        if values and abs(k - values[-1]) <= 1e-14 * max(1.0, abs(k)):
            mults[-1] += 1
        else:
            values.append(float(k))
            mults.append(1)
    return values, mults


@dataclass(frozen=True)
class Fit:
    geometry: object
    error: float


def _grid(lo: float, hi: float, n: int) -> Array:
    return np.linspace(lo, hi, n, dtype=np.float64)


def fit_curve(
    curve: Callable[[float], Array], lo: float, hi: float, tolerance: float
) -> Fit:
    """A cubic B-spline through ``curve`` on [lo, hi], parameterised as it is, within ``tolerance``."""
    n = 9
    while True:
        t = _grid(lo, hi, n)
        points = np.array([curve(float(x)) for x in t])
        knots = _knots(t)
        poles = np.linalg.solve(_basis(knots, t), points)
        mid = (t[:-1] + t[1:]) / 2.0
        fitted = _basis(knots, mid) @ poles
        truth = np.array([curve(float(x)) for x in mid])
        error = float(np.max(np.linalg.norm(fitted - truth, axis=1)))
        if error <= tolerance:
            break
        if n >= MOST:
            raise OperationError("a mapped curve could not be fitted closely enough", error=error,
                                 needed=tolerance)  # fmt: skip
        n = 2 * n - 1
    values, mults = _distinct(knots)
    return Fit(_bspline_curve(poles, values, mults), error)


def _bspline_curve(
    poles: Array, values: list[float], mults: list[int]
) -> Geom_BSplineCurve:
    array = TColgp_Array1OfPnt(1, len(poles))
    for i, p in enumerate(poles):
        array.SetValue(i + 1, gp_Pnt(*map(float, p)))
    knots = TColStd_Array1OfReal(1, len(values))
    multiplicities = TColStd_Array1OfInteger(1, len(mults))
    for i, (k, m) in enumerate(zip(values, mults, strict=True)):
        knots.SetValue(i + 1, k)
        multiplicities.SetValue(i + 1, m)
    return Geom_BSplineCurve(array, knots, multiplicities, DEGREE)


def fit_surface(
    surface: Callable[[Array, Array], Array], u: tuple[float, float], v: tuple[float, float],
    tolerance: float,
) -> Fit:  # fmt: skip
    """A bicubic B-spline through ``surface`` over its u and v ranges, parameterised as it is, within ``tolerance``.

    ``surface`` takes arrays of u and of v (one point each) and gives the points.
    """
    nu, nv = 9, 9
    while True:
        tu, tv = _grid(*u, nu), _grid(*v, nv)
        uu, vv = np.meshgrid(tu, tv, indexing="ij")
        points = surface(uu.ravel(), vv.ravel()).reshape(nu, nv, 3)
        ku, kv = _knots(tu), _knots(tv)
        bu, bv = _basis(ku, tu), _basis(kv, tv)
        # P = Bu⁻¹ Q Bv⁻ᵀ, coordinate by coordinate.
        poles = np.empty_like(points)
        for c in range(3):
            poles[:, :, c] = np.linalg.solve(
                bv, np.linalg.solve(bu, points[:, :, c]).T
            ).T
        mu, mv = (tu[:-1] + tu[1:]) / 2.0, (tv[:-1] + tv[1:]) / 2.0
        worst_u, worst_v = 0.0, 0.0
        for tests_u, tests_v, which in ((mu, tv, "u"), (tu, mv, "v"), (mu, mv, "both")):
            au, av = _basis(ku, tests_u), _basis(kv, tests_v)
            fitted = np.stack([au @ poles[:, :, c] @ av.T for c in range(3)], axis=-1)
            gu, gv = np.meshgrid(tests_u, tests_v, indexing="ij")
            truth = surface(gu.ravel(), gv.ravel()).reshape(
                len(tests_u), len(tests_v), 3
            )
            error = float(np.max(np.linalg.norm(fitted - truth, axis=2)))
            if which in ("u", "both"):
                worst_u = max(worst_u, error)
            if which in ("v", "both"):
                worst_v = max(worst_v, error)
        worst = max(worst_u, worst_v)
        if worst <= tolerance:
            break
        if nu >= MOST and nv >= MOST:
            raise OperationError("a mapped surface could not be fitted closely enough", error=worst,
                                 needed=tolerance)  # fmt: skip
        if worst_u > tolerance and nu < MOST:
            nu = 2 * nu - 1
        if worst_v > tolerance and nv < MOST:
            nv = 2 * nv - 1
    poles_array = TColgp_Array2OfPnt(1, poles.shape[0], 1, poles.shape[1])
    for i in range(poles.shape[0]):
        for j in range(poles.shape[1]):
            poles_array.SetValue(i + 1, j + 1, gp_Pnt(*map(float, poles[i, j])))
    (u_values, u_mults), (v_values, v_mults) = _distinct(ku), _distinct(kv)

    def arrays(
        values: list[float], mults: list[int]
    ) -> tuple[TColStd_Array1OfReal, TColStd_Array1OfInteger]:
        k = TColStd_Array1OfReal(1, len(values))
        m = TColStd_Array1OfInteger(1, len(mults))
        for i, (a, b) in enumerate(zip(values, mults, strict=True)):
            k.SetValue(i + 1, a)
            m.SetValue(i + 1, b)
        return k, m

    uk, um = arrays(u_values, u_mults)
    vk, vm = arrays(v_values, v_mults)
    return Fit(Geom_BSplineSurface(poles_array, uk, vk, um, vm, DEGREE, DEGREE), worst)
