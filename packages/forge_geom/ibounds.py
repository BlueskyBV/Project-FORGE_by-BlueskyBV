"""Vectorised interval arithmetic over arrays, for bounding an SDF on a cell.

Measuring an implicit solid rigorously requires knowing, for a whole cell at
once, whether the field can reach zero inside it. The cheap way is a Lipschitz
bound: ``f(centre) +/- r*L``. That is sound but badly pessimistic on the
geometry engineers actually build, because it assumes the field might be
changing at its maximum rate in every direction, when in fact the distance field
of a plate's flat face is exactly linear and changes only along one axis.

The consequence is not academic. On a 60 x 24 x 6 plate, the Lipschitz test
marks a band roughly half a millimetre thick as "unknown" around every face,
which is around 13% of the part's volume. The same cells evaluated with interval
arithmetic come back decided, because ``|p - c| - h`` over an axis-aligned cell
is computed essentially exactly.

Each value here is a pair of arrays ``(lo, hi)`` of the same shape, and every
operation is sound: the result encloses the true result for every point in the
input box. Where an operation loses tightness -- notably when the same variable
appears more than once, as in a projection onto a non-axis-aligned direction --
the loss widens the interval, which costs refinement steps but never correctness.
"""

from __future__ import annotations

import numpy as np

Array = np.ndarray
#: An interval-valued array: matching lower and upper bounds.
IArray = tuple[Array, Array]


def iconst(value: Array | float) -> IArray:
    array = np.asarray(value, dtype=float)
    return (array, array)


def iadd(a: IArray, b: IArray) -> IArray:
    return (a[0] + b[0], a[1] + b[1])


def isub(a: IArray, b: IArray) -> IArray:
    return (a[0] - b[1], a[1] - b[0])


def ineg(a: IArray) -> IArray:
    return (-a[1], -a[0])


def iscale(a: IArray, factor: float) -> IArray:
    if factor >= 0.0:
        return (a[0] * factor, a[1] * factor)
    return (a[1] * factor, a[0] * factor)


def iadd_scalar(a: IArray, value: float) -> IArray:
    return (a[0] + value, a[1] + value)


def imul(a: IArray, b: IArray) -> IArray:
    products = np.stack(
        [a[0] * b[0], a[0] * b[1], a[1] * b[0], a[1] * b[1]], axis=0
    )
    return (products.min(axis=0), products.max(axis=0))


def iabs(a: IArray) -> IArray:
    lo, hi = a
    magnitude = np.maximum(np.abs(lo), np.abs(hi))
    straddles = (lo <= 0.0) & (hi >= 0.0)
    low = np.where(straddles, 0.0, np.minimum(np.abs(lo), np.abs(hi)))
    return (low, magnitude)


def isquare(a: IArray) -> IArray:
    lo, hi = a
    squares_lo = lo * lo
    squares_hi = hi * hi
    straddles = (lo <= 0.0) & (hi >= 0.0)
    low = np.where(straddles, 0.0, np.minimum(squares_lo, squares_hi))
    return (low, np.maximum(squares_lo, squares_hi))


def isqrt(a: IArray) -> IArray:
    return (np.sqrt(np.maximum(a[0], 0.0)), np.sqrt(np.maximum(a[1], 0.0)))


def imax(a: IArray, b: IArray) -> IArray:
    return (np.maximum(a[0], b[0]), np.maximum(a[1], b[1]))


def imin(a: IArray, b: IArray) -> IArray:
    return (np.minimum(a[0], b[0]), np.minimum(a[1], b[1]))


def imax_zero(a: IArray) -> IArray:
    return (np.maximum(a[0], 0.0), np.maximum(a[1], 0.0))


def imin_zero(a: IArray) -> IArray:
    return (np.minimum(a[0], 0.0), np.minimum(a[1], 0.0))


def icolumn(a: IArray, index: int) -> IArray:
    return (a[0][:, index], a[1][:, index])


def rowmax(a: Array) -> Array:
    """The largest of each row: three columns compared directly, which is
    the same answer as `a.max(axis=1)` a dozen times faster -- numpy reduces
    a short inner axis slowly, and every box field and cell bound does it."""
    if a.ndim == 2 and a.shape[1] == 3:
        return np.maximum(np.maximum(a[:, 0], a[:, 1]), a[:, 2])
    return a.max(axis=1)


def rowsum(a: Array) -> Array:
    """Each row summed, left to right, as `a.sum(axis=1)` does."""
    if a.ndim == 2 and a.shape[1] == 3:
        return a[:, 0] + a[:, 1] + a[:, 2]
    return a.sum(axis=1)


def imax_over_axis(a: IArray, axis: int = 1) -> IArray:
    if axis == 1:
        return (rowmax(a[0]), rowmax(a[1]))
    return (a[0].max(axis=axis), a[1].max(axis=axis))


def isum_over_axis(a: IArray, axis: int = 1) -> IArray:
    if axis == 1:
        return (rowsum(a[0]), rowsum(a[1]))
    return (a[0].sum(axis=axis), a[1].sum(axis=axis))


def idot_constant(a: IArray, vector: Array) -> IArray:
    """Dot an interval vector with a constant vector.

    Exact when the constant is axis-aligned (only one term contributes), which
    is the common case for hole axes and extrusion directions.
    """
    vector = np.asarray(vector, dtype=float)
    nonzero = np.flatnonzero(vector)
    if nonzero.size == 1 and a[0].ndim == 2:
        # Along one axis -- a hole's, an extrusion's: one column, scaled.
        k = int(nonzero[0])
        v = float(vector[k])
        if v >= 0.0:
            return (a[0][:, k] * v, a[1][:, k] * v)
        return (a[1][:, k] * v, a[0][:, k] * v)
    lo_terms = np.where(vector >= 0.0, a[0] * vector, a[1] * vector)
    hi_terms = np.where(vector >= 0.0, a[1] * vector, a[0] * vector)
    return (rowsum(lo_terms), rowsum(hi_terms))


def inorm(a: IArray) -> IArray:
    """Euclidean norm of an interval 3-vector."""
    squares = isquare(a)
    total = isum_over_axis(squares, axis=1)
    return isqrt(total)


def iwidth(a: IArray) -> Array:
    return a[1] - a[0]


def cell_box(centres: Array, half: Array) -> IArray:
    """Turn cell centres and a half-extent into an interval-valued point."""
    return (centres - half, centres + half)


__all__ = [
    "IArray",
    "iconst",
    "iadd",
    "isub",
    "ineg",
    "iscale",
    "iadd_scalar",
    "imul",
    "iabs",
    "isquare",
    "isqrt",
    "imax",
    "imin",
    "imax_zero",
    "imin_zero",
    "icolumn",
    "imax_over_axis",
    "isum_over_axis",
    "idot_constant",
    "inorm",
    "iwidth",
    "cell_box",
]
