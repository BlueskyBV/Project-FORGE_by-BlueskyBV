"""Forge's elementary functions on NumPy arrays: :mod:`forge_numeric.scalar`, step for step.

Each function takes any array-like of float64 (or a scalar) and returns an
array of its shape, every element computed by the same IEEE 754 operations,
in the same order, as the scalar function in :mod:`.scalar` computes it
(only NumPy's elementwise arithmetic, ``sqrt``, comparisons and exact bit
and exponent operations, so no BLAS, SIMD library or C ``libm``). The two are
held to each other bit for bit by the tests. As NumPy's ufuncs, they return
NaN or infinity outside the domain rather than raising.

``hypot`` is CPython's own algorithm, correctly rounded but in rare cases,
every operation rounded on its own (:func:`.scalar.hypot`).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, cast

import numpy as np
from numpy.typing import NDArray

from . import _native, linear
from . import scalar as sc
from .scalar import cube, sq  # (numbers or arrays alike)

Array = NDArray[np.float64]

__all__ = [
    "Draws",
    "arccos",
    "arcsin",
    "arctan",
    "arctan2",
    "cbrt",
    "cond_symmetric",
    "cos",
    "cube",
    "det",
    "dot",
    "eigh",
    "exp",
    "hypot",
    "interp",
    "inv",
    "log",
    "matmul",
    "norm",
    "normal",
    "real_roots",
    "roots",
    "sin",
    "sincos",
    "solve",
    "sq",
    "sum_last",
    "tan",
    "unit",
]


def _in(x: Any) -> Array:
    return np.array(x, dtype=np.float64, copy=True, ndmin=0)


def _u64(x: Array) -> NDArray[np.uint64]:
    return np.ascontiguousarray(x).view(np.uint64)


def _f64(b: NDArray[np.uint64]) -> Array:
    return np.ascontiguousarray(b, dtype=np.uint64).view(np.float64)


def _exponent(x: Array) -> NDArray[np.int64]:
    return ((_u64(x) >> np.uint64(52)) & np.uint64(0x7FF)).astype(np.int64)


def _hx(x: Array) -> NDArray[np.int64]:
    """|high word|: the high 32 bits without the sign."""
    return ((_u64(x) >> np.uint64(32)) & np.uint64(0x7FFFFFFF)).astype(np.int64)


def _with_low_zero(x: Array) -> Array:
    return _f64(_u64(x) & np.uint64(0xFFFFFFFF00000000))


# ----------------------------------------------------------------------
# sin and cos
# ----------------------------------------------------------------------
def _k_sin(x: Array, y: Array, iy: int) -> Array:
    z = x * x
    w = z * z
    r = sc.S2 + z * (sc.S3 + z * sc.S4) + z * w * (sc.S5 + z * sc.S6)
    v = z * x
    if iy == 0:
        return x + v * (sc.S1 + z * r)
    return x - ((z * (0.5 * y - v * r) - y) - v * sc.S1)


def _k_cos(x: Array, y: Array) -> Array:
    z = x * x
    w = z * z
    r = z * (sc.C1 + z * (sc.C2 + z * sc.C3)) + w * w * (
        sc.C4 + z * (sc.C5 + z * sc.C6)
    )
    hz = 0.5 * z
    w = 1.0 - hz
    return w + (((1.0 - w) - hz) + (z * r - x * y))


# The scalar twins as NumPy's ufuncs behave: NaN or infinity where ``math`` raises.
def _asin(v: float) -> float:
    return math.nan if abs(v) > 1.0 else sc.asin(v)


def _acos(v: float) -> float:
    return math.nan if abs(v) > 1.0 else sc.acos(v)


def _exp(v: float) -> float:
    return math.inf if v > sc.O_THRESHOLD else sc.exp(v)


def _log(v: float) -> float:
    if v == 0.0:
        return -math.inf
    return math.nan if v < 0.0 else sc.log(v)


#: Below this many elements a function runs element by element (its scalar twin is cheaper than its set-up).
SMALL = 24


def _scalar(f: Any, x: Array) -> Array:
    flat = x.ravel()
    return cast(
        Array,
        np.array([f(v) for v in flat.tolist()], dtype=np.float64).reshape(x.shape),
    )


def _sincos_both(flat: Array) -> tuple[Array, Array]:
    """(sin, cos) of finite elements below :data:`.scalar.MEDIUM`, without masking: every branch computed, each element's taken."""
    a = np.abs(flat)
    fn = (flat * sc.INVPIO2 + sc._RNINT) - sc._RNINT
    r = flat - fn * sc.PIO2_1
    w = fn * sc.PIO2_1T
    head = r - w
    j = _exponent(flat)
    second = (j - _exponent(head)) > 16
    if second.any():
        t = r
        w2 = fn * sc.PIO2_2
        r2 = t - w2
        w2 = fn * sc.PIO2_2T - ((t - r2) - w2)
        h2 = r2 - w2
        third = second & ((j - _exponent(h2)) > 49)
        if third.any():
            w3 = fn * sc.PIO2_3
            r3 = r2 - w3
            w3 = fn * sc.PIO2_3T - ((r2 - r3) - w3)
            h3 = r3 - w3
            r2 = np.where(third, r3, r2)
            w2 = np.where(third, w3, w2)
            h2 = np.where(third, h3, h2)
        r = np.where(second, r2, r)
        w = np.where(second, w2, w)
        head = np.where(second, h2, head)
    tail = (r - head) - w
    n = fn.astype(np.int64)
    s = _k_sin(head, tail, 1)
    c = _k_cos(head, tail)
    odd = (n & 1).astype(bool)
    s, c = np.where(odd, c, s), np.where(odd, -s, c)
    flip = (n & 2).astype(bool)
    s, c = np.where(flip, -s, s), np.where(flip, -c, c)
    small = a < sc.PIO4
    if small.any():
        zero = np.zeros_like(flat)
        s = np.where(
            small, np.where(a < 1.4901161193847656e-08, flat, _k_sin(flat, zero, 0)), s
        )
        c = np.where(small, np.where(a < sc._COS_ONE, 1.0, _k_cos(flat, zero)), c)
    return s, c


def _np_sincos(x: Any) -> tuple[Array, Array]:
    x = _in(x)
    if x.size < SMALL:
        pairs = [sc._sincos(v) for v in x.ravel().tolist()]
        s = np.array([p[0] for p in pairs], dtype=np.float64).reshape(x.shape)
        c = np.array([p[1] for p in pairs], dtype=np.float64).reshape(x.shape)
        return s, c
    flat = x.ravel()
    with np.errstate(invalid="ignore"):
        odd = ~(
            np.abs(flat) < sc.MEDIUM
        )  # too large for the three-part reduction, infinite or NaN
        if not odd.any():
            s, c = _sincos_both(flat)
        else:
            ok = ~odd
            s = np.empty_like(flat)
            c = np.empty_like(flat)
            s[ok], c[ok] = _sincos_both(flat[ok])
            for k in np.flatnonzero(odd):
                s[k], c[k] = sc._sincos(float(flat[k]))
    return s.reshape(x.shape), c.reshape(x.shape)


# ----------------------------------------------------------------------
# atan and atan2
# ----------------------------------------------------------------------
_ATANHI = np.array(sc.ATANHI)
_ATANLO = np.array(sc.ATANLO)


def _np_arctan(x: Any) -> Array:
    x = _in(x)
    if x.size < SMALL:
        return _scalar(sc.atan, x)
    flat = x.ravel()
    a = np.abs(flat)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        k = np.select(
            [a < 0.4375, a < 0.6875, a < 1.1875, a < 2.4375],
            [-1, 0, 1, 2],
            3,
        )
        t = np.select(
            [k == -1, k == 0, k == 1, k == 2],
            [
                flat,
                (2.0 * a - 1.0) / (2.0 + a),
                (a - 1.0) / (a + 1.0),
                (a - 1.5) / (1.0 + 1.5 * a),
            ],
            -1.0 / a,
        )
        z = t * t
        w = z * z
        at = sc.AT
        s1 = z * (
            at[0] + w * (at[2] + w * (at[4] + w * (at[6] + w * (at[8] + w * at[10]))))
        )
        s2 = w * (at[1] + w * (at[3] + w * (at[5] + w * (at[7] + w * at[9]))))
        kk = np.maximum(k, 0)
        zz = _ATANHI[kk] - ((t * (s1 + s2) - _ATANLO[kk]) - t)
        out = np.where(k < 0, t - t * (s1 + s2), np.where(flat < 0, -zz, zz))
        out = np.where(a < 7.450580596923828e-09, flat, out)
        big = a >= 7.378697629483820646e19
        out = np.where(
            big,
            np.where(
                flat < 0, -(sc.ATANHI[3] + sc.ATANLO[3]), sc.ATANHI[3] + sc.ATANLO[3]
            ),
            out,
        )
        out = np.where(np.isnan(flat), flat + flat, out)
    return cast(Array, out.reshape(x.shape))


def _np_arctan2(y: Any, x: Any) -> Array:
    y, x = np.broadcast_arrays(_in(y), _in(x))
    shape = x.shape
    if x.size < SMALL:
        return np.array(
            [
                sc.atan2(a, b)
                for a, b in zip(y.ravel().tolist(), x.ravel().tolist(), strict=True)
            ],
            dtype=np.float64,
        ).reshape(shape)
    y = y.ravel().copy()
    x = x.ravel().copy()
    out = np.empty_like(x)
    m = np.signbit(y).astype(np.int64) | (2 * np.signbit(x).astype(np.int64))
    nan = np.isnan(x) | np.isnan(y)
    one = (x == 1.0) & ~nan
    yz = (y == 0.0) & ~nan & ~one
    xz = (x == 0.0) & ~nan & ~one & ~yz
    xinf = np.isinf(x) & ~nan & ~yz
    yinf = np.isinf(y) & ~nan & ~one & ~xinf & ~xz
    general = ~(nan | one | yz | xz | xinf | yinf)
    out[nan] = x[nan] + y[nan]
    out[one] = _np_arctan(y[one])
    out[yz] = np.select([m[yz] < 2, m[yz] == 2], [y[yz], sc.PI], -sc.PI)
    out[xz] = np.where(y[xz] < 0, -sc.PIO2, sc.PIO2)
    both = xinf & np.isinf(y)
    q = np.array([sc.PIO4_, -sc.PIO4_, 3.0 * sc.PIO4_, -3.0 * sc.PIO4_])
    out[both] = q[m[both]]
    xonly = xinf & ~np.isinf(y)
    out[xonly] = np.array([0.0, -0.0, sc.PI, -sc.PI])[m[xonly]]
    out[yinf] = np.where(y[yinf] < 0, -sc.PIO2, sc.PIO2)
    if general.any():
        yg, xg, mg = y[general], x[general], m[general].copy()
        k = np.frexp(yg)[1].astype(np.int64) - np.frexp(xg)[1].astype(np.int64)
        steep = k > 60
        flat = (xg < 0) & (k < -60) & ~steep
        with np.errstate(
            divide="ignore", invalid="ignore", over="ignore", under="ignore"
        ):
            z = _np_arctan(np.abs(yg / xg))
        z = np.where(steep, sc.PIO2 + 0.5 * sc.PI_LO, np.where(flat, 0.0, z))
        mg = np.where(steep, mg & 1, mg)
        out[general] = np.select(
            [mg == 0, mg == 1, mg == 2],
            [z, -z, sc.PI - (z - sc.PI_LO)],
            (z - sc.PI_LO) - sc.PI,
        )
    return cast(Array, out.reshape(shape))


# ----------------------------------------------------------------------
# asin and acos
# ----------------------------------------------------------------------
def _r(z: Array) -> Array:
    p = z * (
        sc.PS0 + z * (sc.PS1 + z * (sc.PS2 + z * (sc.PS3 + z * (sc.PS4 + z * sc.PS5))))
    )
    q = 1.0 + z * (sc.QS1 + z * (sc.QS2 + z * (sc.QS3 + z * sc.QS4)))
    return p / q


def _np_arcsin(x: Any) -> Array:
    x = _in(x)
    if x.size < SMALL:
        return _scalar(_asin, x)
    flat = x.ravel()
    out = np.full_like(flat, np.nan)
    a = np.abs(flat)
    with np.errstate(invalid="ignore"):
        one = a == 1.0
        out[one] = flat[one] * sc.PIO2_HI + flat[one] * sc.PIO2_LO
        tiny = a < 1.4901161193847656e-08
        out[tiny] = flat[tiny]
        low = (a < 0.5) & ~tiny
        xl = flat[low]
        out[low] = xl + xl * _r(xl * xl)
        high = (a >= 0.5) & (a < 1.0)
        if high.any():
            ah = a[high]
            w = 1.0 - ah
            t = w * 0.5
            s = np.sqrt(t)
            near = ah >= sc._ASIN_NEAR_ONE
            res = np.empty_like(ah)
            sn, tn = s[near], t[near]
            res[near] = sc.PIO2_HI - (2.0 * (sn + sn * _r(tn)) - sc.PIO2_LO)
            far = ~near
            sf, tf = s[far], t[far]
            wf = _with_low_zero(sf)
            c = (tf - wf * wf) / (sf + wf)
            r = _r(tf)
            p = 2.0 * sf * r - (sc.PIO2_LO - 2.0 * c)
            q = sc.PIO4_HI - 2.0 * wf
            res[far] = sc.PIO4_HI - (p - q)
            out[high] = np.where(flat[high] > 0, res, -res)
        nan = np.isnan(flat)
        out[nan] = flat[nan] + flat[nan]
    return cast(Array, out.reshape(x.shape))


def _np_arccos(x: Any) -> Array:
    x = _in(x)
    if x.size < SMALL:
        return _scalar(_acos, x)
    flat = x.ravel()
    out = np.full_like(flat, np.nan)
    a = np.abs(flat)
    with np.errstate(invalid="ignore"):
        one = a == 1.0
        out[one] = np.where(flat[one] > 0, 0.0, sc.PI + 2.0 * sc.PIO2_LO)
        tiny = a < sc._ACOS_TINY
        out[tiny] = sc.PIO2_HI + sc.PIO2_LO
        low = (a < 0.5) & ~tiny
        xl = flat[low]
        out[low] = sc.PIO2_HI - (xl - (sc.PIO2_LO - xl * _r(xl * xl)))
        neg = (a >= 0.5) & (a < 1.0) & (flat < 0)
        xn = flat[neg]
        z = (1.0 + xn) * 0.5
        s = np.sqrt(z)
        w = _r(z) * s - sc.PIO2_LO
        out[neg] = sc.PI - 2.0 * (s + w)
        pos = (a >= 0.5) & (a < 1.0) & (flat > 0)
        xp = flat[pos]
        z = (1.0 - xp) * 0.5
        s = np.sqrt(z)
        df = _with_low_zero(s)
        c = (z - df * df) / (s + df)
        w = _r(z) * s + c
        out[pos] = 2.0 * (df + w)
        nan = np.isnan(flat)
        out[nan] = flat[nan] + flat[nan]
    return cast(Array, out.reshape(x.shape))


# ----------------------------------------------------------------------
# exp and log
# ----------------------------------------------------------------------
def _np_exp(x: Any) -> Array:
    x = _in(x)
    if x.size < SMALL:
        return _scalar(_exp, x)
    flat = x.ravel()
    out = np.empty_like(flat)
    a = np.abs(flat)
    with np.errstate(invalid="ignore", over="ignore"):
        nan = np.isnan(flat)
        over = flat > sc.O_THRESHOLD
        under = flat < sc.U_THRESHOLD
        out[nan] = flat[nan] + flat[nan]
        out[over] = np.inf
        out[under] = 0.0
        ok = ~(nan | over | under)
        tiny = ok & (a < 3.725290298461914e-09)
        out[tiny] = 1.0 + flat[tiny]
        reduce = ok & (a >= sc._EXP_HALF_LN2)
        plain = ok & ~tiny & ~reduce
        xp = flat[plain]
        t = xp * xp
        c = xp - t * (sc.P1 + t * (sc.P2 + t * (sc.P3 + t * (sc.P4 + t * sc.P5))))
        out[plain] = 1.0 - ((xp * c) / (c - 2.0) - xp)
        if reduce.any():
            xr = flat[reduce]
            ar = a[reduce]
            near = ar < sc._EXP_3HALF_LN2
            pos = xr > 0
            k = np.where(
                near,
                np.where(pos, 1, -1),
                np.trunc(sc.INVLN2 * xr + np.where(pos, 0.5, -0.5)),
            ).astype(np.int64)
            t = k.astype(np.float64)
            hi = np.where(
                near, np.where(pos, xr - sc.LN2HI, xr + sc.LN2HI), xr - t * sc.LN2HI
            )
            lo = np.where(near, np.where(pos, sc.LN2LO, -sc.LN2LO), t * sc.LN2LO)
            xr = hi - lo
            t = xr * xr
            c = xr - t * (sc.P1 + t * (sc.P2 + t * (sc.P3 + t * (sc.P4 + t * sc.P5))))
            y = 1.0 - ((lo - (xr * c) / (2.0 - c)) - hi)
            out[reduce] = np.ldexp(y, k.astype(np.int32))
    return cast(Array, out.reshape(x.shape))


def _np_log(x: Any) -> Array:
    x = _in(x)
    if x.size < SMALL:
        return _scalar(_log, x)
    flat = x.ravel()
    out = np.empty_like(flat)
    with np.errstate(divide="ignore", invalid="ignore"):
        nan = np.isnan(flat)
        zero = flat == 0.0
        neg = flat < 0.0
        inf = np.isinf(flat) & (flat > 0)
        out[nan] = flat[nan] + flat[nan]
        out[zero] = -np.inf
        out[neg] = np.nan
        out[inf] = np.inf
        ok = ~(nan | zero | neg | inf)
        xo = flat[ok]
        mant, e = np.frexp(xo)
        hx = ((_u64(mant) >> np.uint64(32)) & np.uint64(0x000FFFFF)).astype(np.int64)
        i = (hx + 0x95F64) & 0x100000
        up = i >> 20
        k = e.astype(np.int64) - 1 + up
        f = np.ldexp(mant, (1 - up).astype(np.int32)) - 1.0
        dk = k.astype(np.float64)
        res = np.empty_like(xo)
        near = (0x000FFFFF & (2 + hx)) < 3
        # -2^-20 <= f < 2^-20
        fz = near & (f == 0.0)
        res[fz] = np.where(k[fz] == 0, 0.0, dk[fz] * sc.LN2HI + dk[fz] * sc.LN2LO)
        fn_ = near & ~fz
        fv, dkv, kv = f[fn_], dk[fn_], k[fn_]
        rr = fv * fv * (0.5 - 0.33333333333333333 * fv)
        res[fn_] = np.where(
            kv == 0, fv - rr, dkv * sc.LN2HI - ((rr - dkv * sc.LN2LO) - fv)
        )
        far = ~near
        fv, dkv, kv, hv = f[far], dk[far], k[far], hx[far]
        s = fv / (2.0 + fv)
        z = s * s
        ii = hv - 0x6147A
        w = z * z
        j = 0x6B851 - hv
        t1 = w * (sc.LG2 + w * (sc.LG4 + w * sc.LG6))
        t2 = z * (sc.LG1 + w * (sc.LG3 + w * (sc.LG5 + w * sc.LG7)))
        ii = ii | j
        rr = t2 + t1
        hfsq = 0.5 * fv * fv
        a1 = fv - (hfsq - s * (hfsq + rr))
        a2 = dkv * sc.LN2HI - ((hfsq - (s * (hfsq + rr) + dkv * sc.LN2LO)) - fv)
        b1 = fv - s * (fv - rr)
        b2 = dkv * sc.LN2HI - ((s * (fv - rr) - dkv * sc.LN2LO) - fv)
        res[far] = np.where(
            ii > 0, np.where(kv == 0, a1, a2), np.where(kv == 0, b1, b2)
        )
        out[ok] = res
    return cast(Array, out.reshape(x.shape))


# ----------------------------------------------------------------------
# cbrt and hypot
# ----------------------------------------------------------------------
def _np_cbrt(x: Any) -> Array:
    x = _in(x)
    if x.size < SMALL:
        return _scalar(sc.cbrt, x)
    flat = x.ravel()
    out = flat.copy()  # zeros, infinities and NaN are themselves (x + x)
    with np.errstate(invalid="ignore"):
        bad = ~np.isfinite(flat)
        out[bad] = flat[bad] + flat[bad]
        ok = np.isfinite(flat) & (flat != 0.0)
    if not ok.any():
        return cast(Array, out.reshape(x.shape))
    xo = flat[ok]
    b = _u64(xo)
    sign = (b >> np.uint64(32)) & np.uint64(0x80000000)
    hx = (b >> np.uint64(32)) & np.uint64(0x7FFFFFFF)
    sub = hx < np.uint64(0x00100000)
    with np.errstate(over="ignore"):
        scaled = _u64(xo * 18014398509481984.0)
    hs = (scaled >> np.uint64(32)) & np.uint64(0x7FFFFFFF)
    word = np.where(
        sub,
        hs // np.uint64(3) + np.uint64(sc.B2),
        hx // np.uint64(3) + np.uint64(sc.B1),
    )
    t = _f64((sign | word) << np.uint64(32))
    r = (t * t) * (t / xo)
    t = t * (
        (sc.CP0 + r * (sc.CP1 + r * sc.CP2)) + ((r * r) * r) * (sc.CP3 + r * sc.CP4)
    )
    t = _f64((_u64(t) + np.uint64(0x80000000)) & np.uint64(0xFFFFFFFFC0000000))
    s = t * t
    r = xo / s
    w = t + t
    r = (r - t) / (w + r)
    out[ok] = t + t * r
    return cast(Array, out.reshape(x.shape))


def _np_two_square(x: Array) -> tuple[Array, Array]:
    """:func:`.scalar._two_square`, elementwise."""
    hi = x * x
    t = sc._SPLIT * x
    xh = t - (t - x)
    xl = x - xh
    return hi, ((xh * xh - hi) + 2.0 * xh * xl) + xl * xl


def _np_hypot(x: Any, y: Any) -> Array:
    """:func:`.scalar.hypot` of two coordinates, elementwise, operation for operation."""
    x, y = np.broadcast_arrays(_in(x), _in(y))
    shape = x.shape
    x, y = x.ravel(), y.ravel()
    with np.errstate(all="ignore"):
        big = np.maximum(np.abs(x), np.abs(y))
        inf = np.isinf(x) | np.isinf(y)
        nan = (np.isnan(x) | np.isnan(y)) & ~inf
        zero = big == 0.0
        sub = (big < sc._TINY) & ~zero  # every coordinate subnormal: made normal first
        x = np.where(sub, x / sc._TINY, x)
        y = np.where(sub, y / sc._TINY, y)
        big = np.where(sub, big / sc._TINY, big)
        e = np.frexp(np.where(np.isfinite(big) & ~zero, big, 1.0))[1]
        scale = np.ldexp(np.ones_like(big), -e)
        hx, lx = _np_two_square(x * scale)
        hy, ly = _np_two_square(y * scale)
        total = 1.0 + hx
        frac2 = 0.0 + ((1.0 - total) + hx)
        csum = total
        frac1 = 0.0 + lx
        total = csum + hy
        frac2 = frac2 + ((csum - total) + hy)
        csum = total
        frac1 = frac1 + ly
        h = np.sqrt(csum - 1.0 + (frac1 + frac2))
        hh, lh = _np_two_square(h)
        total = csum - hh
        frac2 = frac2 + ((csum - total) - hh)
        csum = total
        frac1 = frac1 - lh
        r = csum - 1.0 + (frac1 + frac2)
        h = h + r / (2.0 * h)
        out = h / scale
        out = np.where(sub, sc._TINY * out, out)
        out = np.where(zero, big, out)
        out = np.where(nan, np.nan, out)
        out = np.where(inf, np.inf, out)
    return cast(Array, out.reshape(shape))


# ----------------------------------------------------------------------
# The functions: the compiled twin where this machine has it, else NumPy (the same bits)
# ----------------------------------------------------------------------
#: The compiled library in use, or None (NumPy throughout). Tests set it to None to hold the two to each other.
_use: Any = _native.LIB


def _flat(x: Any) -> tuple[Array, tuple[int, ...]]:
    a = np.asarray(x, dtype=np.float64)
    return np.ascontiguousarray(a.ravel()), a.shape


def _out(a: Array) -> Array:
    """``a``, or its one element as a NumPy float where it has no axes (as a ufunc gives for a number)."""
    out: Array = a[()]
    return out


def _number(x: Any) -> bool:
    return type(x) is float or type(x) is np.float64


def sincos(x: Any) -> tuple[Array, Array]:
    """(sin x, cos x) elementwise, sharing one argument reduction."""
    if _number(
        x
    ):  # a number: its scalar twin (the same bits), without an array's set-up
        s0, c0 = sc._sincos(float(x))
        return cast(Array, np.float64(s0)), cast(Array, np.float64(c0))
    if _use is None:
        s, c = _np_sincos(x)
        return _out(s), _out(c)
    flat, shape = _flat(x)
    s, c, deferred = _native.sincos(flat)
    if deferred:
        for k in np.flatnonzero(~(np.abs(flat) < sc.MEDIUM) & np.isfinite(flat)):
            s[k], c[k] = sc._sincos(float(flat[k]))
    return _out(s.reshape(shape)), _out(c.reshape(shape))


def sin(x: Any) -> Array:
    return sincos(x)[0]


def cos(x: Any) -> Array:
    return sincos(x)[1]


def tan(x: Any) -> Array:
    s, c = sincos(x)
    with np.errstate(divide="ignore", invalid="ignore"):
        return s / c


#: Each function's scalar twin with an array's answers outside its domain (NaN or infinity, not an error).
_IEEE: dict[str, Callable[[float], float]] = {
    "atan": sc.atan,
    "asin": _asin,
    "acos": _acos,
    "exp": _exp,
    "log": _log,
    "cbrt": sc.cbrt,
}


def _unary(name: str, twin: Callable[[Any], Array], x: Any) -> Array:
    if _number(x):
        return cast(Array, np.float64(_IEEE[name](float(x))))
    if _use is None:
        return _out(twin(x))
    flat, shape = _flat(x)
    return _out(_native.unary(name, flat).reshape(shape))


def arctan(x: Any) -> Array:
    return _unary("atan", _np_arctan, x)


def arcsin(x: Any) -> Array:
    return _unary("asin", _np_arcsin, x)


def arccos(x: Any) -> Array:
    return _unary("acos", _np_arccos, x)


def exp(x: Any) -> Array:
    return _unary("exp", _np_exp, x)


def log(x: Any) -> Array:
    return _unary("log", _np_log, x)


def cbrt(x: Any) -> Array:
    return _unary("cbrt", _np_cbrt, x)


def arctan2(y: Any, x: Any) -> Array:
    if _number(y) and _number(x):
        return cast(Array, np.float64(sc.atan2(float(y), float(x))))
    if _use is None:
        return _out(_np_arctan2(y, x))
    y, x = _pair(y, x)
    shape = x.shape
    return _out(
        _native.atan2(
            np.ascontiguousarray(y.ravel()), np.ascontiguousarray(x.ravel())
        ).reshape(shape)
    )


def hypot(x: Any, y: Any) -> Array:
    """sqrt(x*x + y*y), correctly rounded but in rare cases: :func:`.scalar.hypot` (CPython's algorithm, every operation rounded on its own)."""
    if _number(x) and _number(y):
        return cast(Array, np.float64(_hypot1(float(x), float(y))))
    if _use is None:
        return _out(_np_hypot(x, y))
    x, y = _pair(x, y)
    shape = x.shape
    if x.size <= _FEW:
        found = [
            _hypot1(a, b)
            for a, b in zip(x.ravel().tolist(), y.ravel().tolist(), strict=True)
        ]
        return _out(np.array(found, dtype=np.float64).reshape(shape))
    xf, yf = np.ascontiguousarray(x.ravel()), np.ascontiguousarray(y.ravel())
    out, _ = _native.hypot(xf, yf)
    return _out(out.reshape(shape))


#: Up to this many elements, hypot runs element by element in Python floats (cheaper than the library's call).
_FEW = 8


def _hypot1(x: float, y: float) -> float:
    """:func:`_np_hypot` of one pair, in Python floats: the same operations, so the same bits."""
    return sc.hypot(x, y)


def _pair(a: Any, b: Any) -> tuple[Array, Array]:
    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    if a.shape != b.shape:
        a, b = np.broadcast_arrays(a, b)
    return a, b


# ----------------------------------------------------------------------
# Built on the above
# ----------------------------------------------------------------------
def interp(x: Any, xp: Any, fp: Any) -> Array:
    """``numpy.interp`` (``xp`` increasing; ``fp[0]`` and ``fp[-1]`` outside), by its own formula, one operation at a time.

    NumPy's C computes ``slope * (x - xp[j]) + fp[j]`` in one expression,
    which a compiler may fuse into one rounding (Clang does on ARM); here
    each operation rounds, as NumPy's does where it isn't fused.
    """
    x = np.asarray(x, dtype=np.float64)
    xp = np.asarray(xp, dtype=np.float64)
    fp = np.asarray(fp, dtype=np.float64)
    if xp.ndim != 1 or fp.shape != xp.shape or len(xp) == 0:
        raise ValueError("interp: xp and fp must be 1-D, of one length, not empty")
    n = len(xp)
    flat = x.ravel()
    out = np.empty_like(flat)
    if n == 1:
        out[:] = fp[0]
    else:
        j = np.searchsorted(xp, flat, side="right") - 1
        j = np.where(flat > xp[-1], n, j)
        inner = (j >= 0) & (j < n - 1)
        jj = np.clip(j, 0, n - 2)
        x0, x1, f0, f1 = xp[jj], xp[jj + 1], fp[jj], fp[jj + 1]
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            slope = (f1 - f0) / (x1 - x0)
            value = slope * (flat - x0) + f0
            retry = (
                slope * (flat - x1) + f1
            )  # NumPy's second try where the first is NaN
        value = np.where(
            np.isnan(value), np.where(np.isnan(retry) & (f0 == f1), f0, retry), value
        )
        value = np.where(x0 == flat, f0, value)
        out[:] = np.where(inner, value, np.where(j < 0, fp[0], fp[-1]))
        out = np.where(
            np.isnan(flat), flat, out
        )  # (with one point, NumPy gives fp[0] for NaN too)
    return _out(out.reshape(x.shape))


class Draws:
    """NumPy's PCG64 random draws, the same numbers on every machine: ``numpy.random.default_rng(seed)``'s place.

    NumPy's ``uniform`` and ``normal`` compute ``low + range * u`` and the
    like in C, which Clang and Microsoft's ARM compiler fuse into one
    rounding: another last bit on a Mac or an ARM PC. Here ``uniform`` is
    ``low + (high - low) * u`` in NumPy's elementwise arithmetic (the bits
    GCC's unfused build gives), from the same draws in the same order;
    ``normal`` is :func:`normal`'s; ``random``, ``integers``,
    ``permutation`` and ``choice`` are NumPy's own (exact: integers, and
    ``u`` a whole number times 2^-53).
    """

    def __init__(self, seed: Any = None) -> None:
        self.generator = np.random.default_rng(seed)

    def random(self, size: Any = None) -> Array:
        drawn: Array = self.generator.random(size)
        return drawn

    def uniform(self, low: Any = 0.0, high: Any = 1.0, size: Any = None) -> Array:
        low, high = (
            np.asarray(low, dtype=np.float64),
            np.asarray(high, dtype=np.float64),
        )
        if size is None:
            size = np.broadcast_shapes(low.shape, high.shape)
        return _out(low + (high - low) * self.generator.random(size))

    def normal(self, loc: float = 0.0, scale: float = 1.0, size: Any = None) -> Array:
        return normal(self.generator, loc, scale, size)

    def integers(self, *args: Any, **kwargs: Any) -> Any:
        return self.generator.integers(*args, **kwargs)

    def permutation(self, x: Any) -> Any:
        return self.generator.permutation(x)

    def choice(self, *args: Any, **kwargs: Any) -> Any:
        return self.generator.choice(*args, **kwargs)


def normal(
    rng: Any,
    loc: float = 0.0,
    scale: float = 1.0,
    size: int | tuple[int, ...] | None = None,
) -> Array:
    """Normal draws from ``rng``'s uniform ones (Box and Muller's transform): ``rng.normal``'s place (``rng`` a NumPy generator or :class:`Draws`).

    NumPy's own normal draws take ``exp`` and ``log`` from the C library on
    their rarer path, so a seed may draw other numbers on another machine.
    Two uniform draws make one normal one.
    """
    shape: tuple[int, ...] = (
        () if size is None else (size,) if isinstance(size, int) else tuple(size)
    )
    count = int(np.prod(shape, dtype=np.int64)) if shape else 1
    u = rng.random(2 * count)
    radius = np.sqrt(-2.0 * log(1.0 - u[:count]))
    z = radius * cos((2.0 * math.pi) * u[count:])
    return _out((loc + scale * z).reshape(shape))


def roots(coeffs: Any) -> NDArray[np.complex128]:
    """A polynomial's roots, complex, in no particular order: ``numpy.roots`` (highest degree first), by Aberth and Ehrlich's iteration.

    ``numpy.roots`` takes the eigenvalues of the companion matrix from LAPACK;
    here every root is refined at once, in real arithmetic in a fixed order,
    from points on a circle that holds them all, until no step moves any by
    more than a few units in its last place (or 200 steps). Leading zero
    coefficients are dropped and trailing ones are roots at 0, as there.
    """
    c = np.atleast_1d(np.asarray(coeffs))
    if c.ndim != 1:
        raise ValueError("roots: the coefficients must be one row")
    re = np.asarray(c.real, dtype=np.float64)
    im = (
        np.asarray(c.imag, dtype=np.float64)
        if np.iscomplexobj(c)
        else np.zeros_like(re)
    )
    nonzero = np.flatnonzero((re != 0.0) | (im != 0.0))
    if len(nonzero) == 0:
        return np.zeros(0, dtype=np.complex128)
    re, im = re[nonzero[0] : nonzero[-1] + 1], im[nonzero[0] : nonzero[-1] + 1]
    zeros = len(c) - 1 - int(nonzero[-1])
    n = len(re) - 1
    if n == 0:
        return np.zeros(zeros, dtype=np.complex128)
    # Monic: each coefficient over the first (complex division, one operation at a time).
    d = re[0] * re[0] + im[0] * im[0]
    ar = (re * re[0] + im * im[0]) / d
    ai = (im * re[0] - re * im[0]) / d
    ar[0], ai[0] = 1.0, 0.0
    # A circle holding every root (Fujiwara's bound), and n points on it.
    mags = hypot(ar[1:], ai[1:])
    mags[-1] = 0.5 * mags[-1]
    k = np.arange(1, n + 1, dtype=np.float64)
    powers = np.where(mags > 0.0, exp(log(np.where(mags > 0.0, mags, 1.0)) / k), 0.0)
    radius = 2.0 * float(np.max(powers))  # 2 max |a_k|^(1/k), the last halved
    if radius == 0.0:
        return np.zeros(n + zeros, dtype=np.complex128)
    s, co = sincos((2.0 * math.pi) * np.arange(n, dtype=np.float64) / n + 0.4)
    zr, zi = radius * co, radius * s
    still = np.ones(n, dtype=bool)
    off = ~np.eye(n, dtype=bool)
    with np.errstate(all="ignore"):
        for _ in range(200):
            # p(z) and p'(z) by Horner's rule.
            pr, pi_ = np.full(n, ar[0]), np.full(n, ai[0])
            qr, qi = np.zeros(n), np.zeros(n)
            for j in range(1, n + 1):
                qr, qi = qr * zr - qi * zi + pr, qr * zi + qi * zr + pi_
                pr, pi_ = pr * zr - pi_ * zi + ar[j], pr * zi + pi_ * zr + ai[j]
            # Newton's step p / p'.
            qq = qr * qr + qi * qi
            nr = (pr * qr + pi_ * qi) / qq
            ni = (pi_ * qr - pr * qi) / qq
            # The pull of the other roots: the sum over k != j of 1 / (z_j - z_k).
            dr = zr[:, None] - zr[None, :]
            di = zi[:, None] - zi[None, :]
            dd = np.where(off, dr * dr + di * di, 1.0)
            sr = sum_last(np.where(off, dr / dd, 0.0))
            si = sum_last(np.where(off, -di / dd, 0.0))
            # Aberth's step: N / (1 - N S).
            br = 1.0 - (nr * sr - ni * si)
            bi = -(nr * si + ni * sr)
            bb = br * br + bi * bi
            wr = (nr * br + ni * bi) / bb
            wi = (ni * br - nr * bi) / bb
            ok = np.isfinite(wr) & np.isfinite(wi) & still
            wr, wi = np.where(ok, wr, 0.0), np.where(ok, wi, 0.0)
            zr, zi = zr - wr, zi - wi
            small = hypot(wr, wi) <= 4.0 * 2.0**-52 * hypot(zr, zi)
            still &= ~(small | ((pr == 0.0) & (pi_ == 0.0)))
            if not still.any():
                break
    out = np.zeros(n + zeros, dtype=np.complex128)
    out.real[:n], out.imag[:n] = zr, zi
    return out


@contextmanager
def numpy_twin() -> Iterator[None]:
    """NumPy computes everything while this is held (the compiled twin set aside): the tests hold the two to each other."""
    global _use
    saved = _use, linear._use
    _use = linear._use = None
    try:
        yield
    finally:
        _use, linear._use = saved


def _self_test() -> str:
    """The compiled twin against NumPy's on fixed inputs: "" if they agree bit for bit, else what differs."""
    rng = np.random.default_rng(37)
    xs = np.concatenate([
        np.ldexp(rng.uniform(-1.0, 1.0, 512), rng.integers(-60, 60, 512).astype(np.int32)),
        [0.0, -0.0, 1.0, -1.0, 0.5, np.inf, -np.inf, np.nan, 5e-324, 1e300, sc.MEDIUM, sc.PIO4],
    ])  # fmt: skip
    unit = np.clip(xs, -1.0, 1.0)
    pairs: list[tuple[str, Callable[[tuple[Any, ...]], Array], tuple[Any, Any]]] = [
        ("sincos", lambda f: np.concatenate(f[0](xs)), (sincos, _np_sincos)),
        ("arctan", lambda f: f[0](xs), (arctan, _np_arctan)),
        ("arcsin", lambda f: f[0](unit), (arcsin, _np_arcsin)),
        ("arccos", lambda f: f[0](unit), (arccos, _np_arccos)),
        ("exp", lambda f: f[0](np.clip(xs, -800, 800)), (exp, _np_exp)),
        ("log", lambda f: f[0](np.abs(xs)), (log, _np_log)),
        ("cbrt", lambda f: f[0](xs), (cbrt, _np_cbrt)),
        ("arctan2", lambda f: f[0](xs, xs[::-1]), (arctan2, _np_arctan2)),
        ("hypot", lambda f: f[0](xs, xs[::-1]), (hypot, _np_hypot)),
    ]
    with np.errstate(all="ignore"):
        for name, run, (native_f, numpy_f) in pairs:
            a, b = run((native_f,)), run((numpy_f,))
            if not np.array_equal(a.view(np.uint64), b.view(np.uint64)):
                return name
    m = xs[:384].reshape(-1, 3)
    m = np.where(np.isfinite(m), m, 1.0)
    products: list[tuple[str, Callable[..., Any], tuple[Array, Array]]] = [
        ("matmul", linear.matmul, (m, np.abs(m[:3].T))),
    ]
    for name, f, args in products:
        with np.errstate(all="ignore"):
            native = f(*args)
            saved, linear._use = linear._use, None
            try:
                numpy = f(*args)
            finally:
                linear._use = saved
        if not np.array_equal(native.view(np.uint64), numpy.view(np.uint64)):
            return name
    return ""


if _use is not None:
    _bad = _self_test()
    if _bad:
        import warnings

        warnings.warn(
            f"forge_numeric's compiled library differs from NumPy's twin ({_bad}): using NumPy",
            stacklevel=1,
        )
        _use = linear._use = None
        _native.WHY_NOT = f"it differed from the NumPy twin on {_bad} at load"


from .linear import (  # noqa: E402  (re-exported: the array side's products and linear algebra)
    cond_symmetric,
    det,
    dot,
    eigh,
    inv,
    matmul,
    norm,
    real_roots,
    solve,
    sum_last,
    unit,
)
