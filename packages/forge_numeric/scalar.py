"""Forge's elementary functions on Python floats: the same bits on every machine.

Each function is computed from IEEE 754 operations whose results the
standard fixes exactly (``+ - * /`` and ``sqrt``, correctly rounded; and
exact ones: comparisons, negation, ``abs``, ``frexp``/``ldexp``, reading and
setting a float's bits), in an order this code fixes. The platform's C
library (whose ``sin`` or ``atan2`` may differ by a last bit from machine to
machine) is never called. :mod:`forge_numeric.vector` computes the same
functions on NumPy arrays, step for step, so the two agree bit for bit.

The algorithms are FreeBSD's msun, derived from Sun's fdlibm (their notice
below), each with its proven bound: under one unit in the last place
(ulp) for ``sin``, ``cos``, ``atan``, ``atan2``, ``asin``, ``acos``, ``exp``,
``log``, ``cbrt`` and ``hypot``; ``tan`` is ``sin / cos`` (under two ulps).
Arguments too large for the argument reduction's three-part pi/2
(|x| >= 2^20 pi/2) are reduced exactly with integers.

    Copyright (C) 1993, 2004 by Sun Microsystems, Inc. All rights reserved.

    Developed at SunSoft, a Sun Microsystems, Inc. business.
    Permission to use, copy, modify, and distribute this software is freely
    granted, provided that this notice is preserved.

(msun's later changes are Bruce D. Evans's and Steven G. Kargl's, under the
same notice or the FreeBSD licence.) ``math.hypot`` and ``math.sqrt`` need
no replacing: CPython computes ``hypot`` itself, and ``sqrt`` is correctly
rounded everywhere.
"""

from __future__ import annotations

import math
from fractions import Fraction
from functools import lru_cache

from ._bits import bits, from_bits, from_high, high, with_low_zero

__all__ = [
    "acos",
    "asin",
    "atan",
    "atan2",
    "cbrt",
    "cos",
    "exp",
    "log",
    "sin",
    "sincos",
    "tan",
]

_INF = math.inf


def _domain(x: float) -> float:
    """Outside a function's domain: ``math``'s ValueError (a NaN argument gives NaN, as there)."""
    if x != x:
        return x
    raise ValueError("math domain error")


# ----------------------------------------------------------------------
# sin and cos: msun's k_sin.c and k_cos.c on [-pi/4, pi/4], after e_rem_pio2.c
# ----------------------------------------------------------------------
S1 = -1.66666666666666324348e-01
S2 = 8.33333333332248946124e-03
S3 = -1.98412698298579493134e-04
S4 = 2.75573137070700676789e-06
S5 = -2.50507602534068634195e-08
S6 = 1.58969099521155010221e-10

C1 = 4.16666666666666019037e-02
C2 = -1.38888888888741095749e-03
C3 = 2.48015872894767294178e-05
C4 = -2.75573143513906633035e-07
C5 = 2.08757232129817482790e-09
C6 = -1.13596475577881948265e-11


#: cos x rounds to 1 below the high word 0x3e46a09e (about 2^-27 sqrt 2).
_COS_ONE = from_high(0x3E46A09E)


def _k_sin(x: float, y: float, iy: int) -> float:
    """sin(x + y) for |x + y| <= pi/4, y the tail of x (0 where none: iy = 0)."""
    z = x * x
    w = z * z
    r = S2 + z * (S3 + z * S4) + z * w * (S5 + z * S6)
    v = z * x
    if iy == 0:
        return x + v * (S1 + z * r)
    return x - ((z * (0.5 * y - v * r) - y) - v * S1)


def _k_cos(x: float, y: float) -> float:
    """cos(x + y) for |x + y| <= pi/4."""
    z = x * x
    w = z * z
    r = z * (C1 + z * (C2 + z * C3)) + w * w * (C4 + z * (C5 + z * C6))
    hz = 0.5 * z
    w = 1.0 - hz
    return w + (((1.0 - w) - hz) + (z * r - x * y))


INVPIO2 = 6.36619772367581382433e-01
PIO2_1 = 1.57079632673412561417e00  # the first 33 bits of pi/2
PIO2_1T = 6.07710050650619224932e-11  # pi/2 - PIO2_1
PIO2_2 = 6.07710050630396597660e-11  # the second 33 bits
PIO2_2T = 2.02226624879595063154e-21
PIO2_3 = 2.02226624871116645580e-21  # the third 33 bits
PIO2_3T = 8.47842766036889956997e-32
#: Below this the three-part reduction is exact enough (the high word 0x413921fb: about 2^20 pi/2).
MEDIUM = from_high(0x413921FB)
#: Round to the nearest integer, ties to even, in doubles: (x + R) - R.
_RNINT = 6755399441055744.0  # 0x1.8p52
#: The kernels' reach: |x| up to the high word 0x3fe921fb (just past pi/4).
PIO4 = from_high(0x3FE921FC)


def _exponent(x: float) -> int:
    """The biased exponent of ``x`` (its high word's bits 20 to 30): 0 for zero and subnormals."""
    if -2.2250738585072014e-308 < x < 2.2250738585072014e-308:
        return 0
    return math.frexp(x)[1] + 1022


def _rem_pio2(x: float) -> tuple[int, float, float]:
    """``x`` less the nearest multiple ``n`` of pi/2: (n mod 4, the remainder as head and tail)."""
    if abs(x) >= MEDIUM:
        return _rem_pio2_exact(x)
    fn = (x * INVPIO2 + _RNINT) - _RNINT
    n = int(fn)
    r = x - fn * PIO2_1
    w = fn * PIO2_1T
    j = _exponent(x)
    y0 = r - w
    if j - _exponent(y0) > 16:  # a second round, good to 118 bits
        t = r
        w = fn * PIO2_2
        r = t - w
        w = fn * PIO2_2T - ((t - r) - w)
        y0 = r - w
        if j - _exponent(y0) > 49:  # a third, 151 bits
            t = r
            w = fn * PIO2_3
            r = t - w
            w = fn * PIO2_3T - ((t - r) - w)
            y0 = r - w
    y1 = (r - y0) - w
    return n & 3, y0, y1


# The exact reduction of a large argument, with pi to 1,300 bits (Machin's formula, in integers).
_PI_BITS = 1300


def _arctan_inverse(k: int, scale: int) -> int:
    """atan(1/k) * 2^scale, rounded down (to within a few units)."""
    total, power, n, sign = 0, (1 << scale) // k, 1, 1
    k2 = k * k
    while power:
        total += sign * (power // n)
        power //= k2
        n += 2
        sign = -sign
    return total


@lru_cache(maxsize=1)
def _pi_scaled() -> int:
    """pi * 2^_PI_BITS, to within a few units."""
    guard = 16
    scale = _PI_BITS + guard
    pi = 4 * (4 * _arctan_inverse(5, scale) - _arctan_inverse(239, scale))
    return pi >> guard


def _rem_pio2_exact(x: float) -> tuple[int, float, float]:
    pi = _pi_scaled()
    q = Fraction(x) * 2 * (1 << _PI_BITS) / pi  # x / (pi/2), to ~1,250 bits
    n = round(q)
    rest = (q - n) * pi / (2 * (1 << _PI_BITS))  # x - n pi/2
    y0 = float(rest)
    y1 = float(rest - Fraction(y0))
    return int(n) & 3, y0, y1


def sin(x: float) -> float:
    if math.isinf(x):
        raise ValueError("math domain error")
    return _sin(x)


def cos(x: float) -> float:
    if math.isinf(x):
        raise ValueError("math domain error")
    return _cos(x)


def _sin(x: float) -> float:
    if abs(x) < PIO4:
        if abs(x) < 1.4901161193847656e-08:  # 2^-26: sin x is x
            return x
        return _k_sin(x, 0.0, 0)
    if not math.isfinite(x):
        return x - x
    n, y0, y1 = _rem_pio2(x)
    if n == 0:
        return _k_sin(y0, y1, 1)
    if n == 1:
        return _k_cos(y0, y1)
    if n == 2:
        return -_k_sin(y0, y1, 1)
    return -_k_cos(y0, y1)


def _cos(x: float) -> float:
    if abs(x) < PIO4:
        if abs(x) < _COS_ONE:  # the high word 0x3e46a09e: cos x is 1
            return 1.0
        return _k_cos(x, 0.0)
    if not math.isfinite(x):
        return x - x
    n, y0, y1 = _rem_pio2(x)
    if n == 0:
        return _k_cos(y0, y1)
    if n == 1:
        return -_k_sin(y0, y1, 1)
    if n == 2:
        return -_k_cos(y0, y1)
    return _k_sin(y0, y1, 1)


def tan(x: float) -> float:
    """sin x / cos x (under two ulps)."""
    return sin(x) / cos(x)


def sincos(x: float) -> tuple[float, float]:
    """(sin x, cos x), sharing one argument reduction; each exactly :func:`sin` and :func:`cos`."""
    if math.isinf(x):
        raise ValueError("math domain error")
    return _sincos(x)


def _sincos(x: float) -> tuple[float, float]:
    a = abs(x)
    if a < PIO4:
        s = x if a < 1.4901161193847656e-08 else _k_sin(x, 0.0, 0)
        c = 1.0 if a < _COS_ONE else _k_cos(x, 0.0)
        return s, c
    if not math.isfinite(x):
        return x - x, x - x
    n, y0, y1 = _rem_pio2(x)
    s, c = _k_sin(y0, y1, 1), _k_cos(y0, y1)
    if n & 1:
        s, c = c, -s
    if n & 2:
        s, c = -s, -c
    return s, c


# ----------------------------------------------------------------------
# atan and atan2: msun's s_atan.c and e_atan2.c
# ----------------------------------------------------------------------
ATANHI = (
    4.63647609000806093515e-01,  # atan(0.5)
    7.85398163397448278999e-01,  # atan(1.0)
    9.82793723247329054082e-01,  # atan(1.5)
    1.57079632679489655800e00,  # atan(inf)
)
ATANLO = (
    2.26987774529616870924e-17,
    3.06161699786838301793e-17,
    1.39033110312309984516e-17,
    6.12323399573676603587e-17,
)
AT = (
    3.33333333333329318027e-01,
    -1.99999999998764832476e-01,
    1.42857142725034663711e-01,
    -1.11111104054623557880e-01,
    9.09088713343650656196e-02,
    -7.69187620504482999495e-02,
    6.66107313738753120669e-02,
    -5.83357013379057348645e-02,
    4.97687799461593236017e-02,
    -3.65315727442169155270e-02,
    1.62858201153657823623e-02,
)


def atan(x: float) -> float:
    if x != x:
        return x + x
    a = abs(x)
    if a >= 7.378697629483820646e19:  # 2^66: atan x is +-pi/2
        z = ATANHI[3] + ATANLO[3]
        return -z if x < 0 else z
    if a < 0.4375:
        if a < 7.450580596923828e-09:  # 2^-27
            return x
        t = x
        k = -1
    else:
        if a < 1.1875:
            if a < 0.6875:
                k, t = 0, (2.0 * a - 1.0) / (2.0 + a)
            else:
                k, t = 1, (a - 1.0) / (a + 1.0)
        elif a < 2.4375:
            k, t = 2, (a - 1.5) / (1.0 + 1.5 * a)
        else:
            k, t = 3, -1.0 / a
    z = t * t
    w = z * z
    s1 = z * (
        AT[0] + w * (AT[2] + w * (AT[4] + w * (AT[6] + w * (AT[8] + w * AT[10]))))
    )
    s2 = w * (AT[1] + w * (AT[3] + w * (AT[5] + w * (AT[7] + w * AT[9]))))
    if k < 0:
        return t - t * (s1 + s2)
    z = ATANHI[k] - ((t * (s1 + s2) - ATANLO[k]) - t)
    return -z if x < 0 else z


PI = 3.1415926535897931160e00
PI_LO = 1.2246467991473531772e-16
PIO2 = 1.5707963267948965580e00
PIO4_ = 7.8539816339744827900e-01


def atan2(y: float, x: float) -> float:
    if x != x or y != y:
        return x + y
    if x == 1.0:
        return atan(y)
    m = (1 if math.copysign(1.0, y) < 0 else 0) | (
        2 if math.copysign(1.0, x) < 0 else 0
    )
    if y == 0.0:
        return y if m < 2 else (PI if m == 2 else -PI)
    if x == 0.0:
        return -PIO2 if y < 0 else PIO2
    if math.isinf(x):
        if math.isinf(y):
            return (PIO4_, -PIO4_, 3.0 * PIO4_, -3.0 * PIO4_)[m]
        return (0.0, -0.0, PI, -PI)[m]
    if math.isinf(y):
        return -PIO2 if y < 0 else PIO2
    k = math.frexp(y)[1] - math.frexp(x)[1]
    if k > 60:  # |y/x| > 2^60
        z = PIO2 + 0.5 * PI_LO
        m &= 1
    elif x < 0 and k < -60:  # |y|/x < -2^60
        z = 0.0
    else:
        z = atan(abs(y / x))
    if m == 0:
        return z
    if m == 1:
        return -z
    if m == 2:
        return PI - (z - PI_LO)
    return (z - PI_LO) - PI


# ----------------------------------------------------------------------
# asin and acos: msun's e_asin.c and e_acos.c
# ----------------------------------------------------------------------
PIO2_HI = 1.57079632679489655800e00
PIO2_LO = 6.12323399573676603587e-17
PIO4_HI = 7.85398163397448278999e-01
PS0 = 1.66666666666666657415e-01
PS1 = -3.25565818622400915405e-01
PS2 = 2.01212532134862925881e-01
PS3 = -4.00555345006794114027e-02
PS4 = 7.91534994289814532176e-04
PS5 = 3.47933107596021167570e-05
QS1 = -2.40339491173441421878e00
QS2 = 2.02094576023350569471e00
QS3 = -6.88283971605453293030e-01
QS4 = 7.70381505559019352791e-02
#: acos x rounds to pi/2 up to the high word 0x3c600000.
_ACOS_TINY = from_high(0x3C600001)
#: 0x3FEF3333 as the high word: asin's switch to its last branch.
_ASIN_NEAR_ONE = from_high(0x3FEF3333)


def _r(z: float) -> float:
    p = z * (PS0 + z * (PS1 + z * (PS2 + z * (PS3 + z * (PS4 + z * PS5)))))
    q = 1.0 + z * (QS1 + z * (QS2 + z * (QS3 + z * QS4)))
    return p / q


def asin(x: float) -> float:
    if x != x:
        return x + x
    a = abs(x)
    if a >= 1.0:
        if a == 1.0:
            return x * PIO2_HI + x * PIO2_LO
        return _domain(x)
    if a < 0.5:
        if a < 1.4901161193847656e-08:  # 2^-26
            return x
        return x + x * _r(x * x)
    w = 1.0 - a
    t = w * 0.5
    s = math.sqrt(t)
    if a >= _ASIN_NEAR_ONE:
        t = PIO2_HI - (2.0 * (s + s * _r(t)) - PIO2_LO)
    else:
        w = with_low_zero(s)
        c = (t - w * w) / (s + w)
        r = _r(t)
        p = 2.0 * s * r - (PIO2_LO - 2.0 * c)
        q = PIO4_HI - 2.0 * w
        t = PIO4_HI - (p - q)
    return t if x > 0 else -t


def acos(x: float) -> float:
    if x != x:
        return x + x
    a = abs(x)
    if a >= 1.0:
        if a == 1.0:
            return 0.0 if x > 0 else PI + 2.0 * PIO2_LO
        return _domain(x)
    if a < 0.5:
        if a < _ACOS_TINY:  # the high word 0x3c600000 or less: about 2^-57
            return PIO2_HI + PIO2_LO
        return PIO2_HI - (x - (PIO2_LO - x * _r(x * x)))
    if x < 0:
        z = (1.0 + x) * 0.5
        s = math.sqrt(z)
        w = _r(z) * s - PIO2_LO
        return PI - 2.0 * (s + w)
    z = (1.0 - x) * 0.5
    s = math.sqrt(z)
    df = with_low_zero(s)
    c = (z - df * df) / (s + df)
    w = _r(z) * s + c
    return 2.0 * (df + w)


# ----------------------------------------------------------------------
# exp and log: msun's e_exp.c and e_log.c
# ----------------------------------------------------------------------
O_THRESHOLD = 7.09782712893383973096e02
U_THRESHOLD = -7.45133219101941108420e02
LN2HI = 6.93147180369123816490e-01
LN2LO = 1.90821492927058770002e-10
INVLN2 = 1.44269504088896338700e00
P1 = 1.66666666666666019037e-01
P2 = -2.77777777770155933842e-03
P3 = 6.61375632143793436117e-05
P4 = -1.65339022054652515390e-06
P5 = 4.13813679705723846039e-08
#: e_exp.c's switches, as high words: past 0x3fd62e42 the argument is reduced; below 0x3ff0a2b2 by one ln 2.
_EXP_HALF_LN2 = from_high(0x3FD62E43)
_EXP_3HALF_LN2 = from_high(0x3FF0A2B2)


def exp(x: float) -> float:
    if x != x:
        return x + x
    if x > O_THRESHOLD:
        if math.isinf(x):
            return x
        raise OverflowError("math range error")
    if x < U_THRESHOLD:
        return 0.0
    a = abs(x)
    if a >= _EXP_HALF_LN2:  # the high word past 0x3fd62e42: |x| > 0.5 ln 2
        if a < _EXP_3HALF_LN2:  # below the high word 0x3ff0a2b2: |x| < 1.5 ln 2
            if x > 0:
                hi, lo, k = x - LN2HI, LN2LO, 1
            else:
                hi, lo, k = x + LN2HI, -LN2LO, -1
        else:
            k = int(INVLN2 * x + (0.5 if x > 0 else -0.5))  # towards zero, as C's (int)
            t = float(k)
            hi = x - t * LN2HI
            lo = t * LN2LO
        x = hi - lo
    elif a < 3.725290298461914e-09:  # 2^-28
        return 1.0 + x
    else:
        k, hi, lo = 0, 0.0, 0.0
    t = x * x
    c = x - t * (P1 + t * (P2 + t * (P3 + t * (P4 + t * P5))))
    if k == 0:
        return 1.0 - ((x * c) / (c - 2.0) - x)
    y = 1.0 - ((lo - (x * c) / (2.0 - c)) - hi)
    return math.ldexp(y, k)


LG1 = 6.666666666666735130e-01
LG2 = 3.999999999940941908e-01
LG3 = 2.857142874366239149e-01
LG4 = 2.222219843214978396e-01
LG5 = 1.818357216161805012e-01
LG6 = 1.531383769920937332e-01
LG7 = 1.479819860511658591e-01


def log(x: float) -> float:
    if x != x:
        return x + x
    if x <= 0.0:
        return _domain(x)
    if math.isinf(x):
        return x
    # x = 2^k f with f in [sqrt(2)/2, sqrt(2)), as msun normalises it (exact).
    m, e = math.frexp(x)  # x = m 2^e, m in [0.5, 1)
    hx = int(m * 2097152.0) - 1048576  # m's top 20 significand bits (m 2^21 is exact)
    i = (hx + 0x95F64) & 0x100000
    k = e - 1 + (i >> 20)
    f = math.ldexp(m, 1 - (i >> 20)) - 1.0  # 2m - 1, or m - 1 where 2m >= sqrt(2)
    dk = float(k)
    if (0x000FFFFF & (2 + hx)) < 3:  # -2^-20 <= f < 2^-20
        if f == 0.0:
            return 0.0 if k == 0 else dk * LN2HI + dk * LN2LO
        rr = f * f * (0.5 - 0.33333333333333333 * f)
        return f - rr if k == 0 else dk * LN2HI - ((rr - dk * LN2LO) - f)
    s = f / (2.0 + f)
    z = s * s
    i = hx - 0x6147A
    w = z * z
    j = 0x6B851 - hx
    t1 = w * (LG2 + w * (LG4 + w * LG6))
    t2 = z * (LG1 + w * (LG3 + w * (LG5 + w * LG7)))
    i |= j
    rr = t2 + t1
    if i > 0:
        hfsq = 0.5 * f * f
        if k == 0:
            return f - (hfsq - s * (hfsq + rr))
        return dk * LN2HI - ((hfsq - (s * (hfsq + rr) + dk * LN2LO)) - f)
    if k == 0:
        return f - s * (f - rr)
    return dk * LN2HI - ((s * (f - rr) - dk * LN2LO) - f)


# ----------------------------------------------------------------------
# cbrt: msun's s_cbrt.c (Bruce D. Evans, 2009)
# ----------------------------------------------------------------------
B1 = 715094163  # (1023 - 1023/3 - 0.03306235651) * 2^20
B2 = 696219795  # (1023 - 1023/3 - 54/3 - 0.03306235651) * 2^20
CP0 = 1.87595182427177009643
CP1 = -1.88497979543377169875
CP2 = 1.621429720105354466140
CP3 = -0.758397934778766047437
CP4 = 0.145996192886612446982


def cbrt(x: float) -> float:
    if not math.isfinite(x) or x == 0.0:
        return x + x if x != 0.0 else x
    hx = high(x)
    sign = hx & 0x80000000
    hx &= 0x7FFFFFFF
    if hx < 0x00100000:  # subnormal: scale by 2^54 first
        t = x * 18014398509481984.0
        t = from_high(sign | ((high(t) & 0x7FFFFFFF) // 3 + B2))
    else:
        t = from_high(sign | (hx // 3 + B1))
    r = (t * t) * (t / x)
    t = t * ((CP0 + r * (CP1 + r * CP2)) + ((r * r) * r) * (CP3 + r * CP4))
    b = _round_23(t)
    s = b * b
    r = x / s
    w = b + b
    r = (r - b) / (w + r)
    return b + b * r


def _round_23(t: float) -> float:
    """``t`` rounded away from zero to 23 significant bits, as s_cbrt.c does with its words."""
    return from_bits((bits(t) + 0x80000000) & ~0x3FFFFFFF)
