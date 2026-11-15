"""Orientation predicates whose signs are exact.

Whether two triangles of a mesh touch, whether a triangle has any area, which
side of a plane a point lies on: each comes down to the sign of a small
determinant, and a sign got wrong by rounding is a wrong answer, not a slightly
inaccurate one. So the signs here are exact.

Each is first worked out in floating point, with Shewchuk's error bound
(*Adaptive Precision Floating-Point Arithmetic and Fast Robust Geometric
Predicates*, 1997): where the result is larger than the bound, its sign is
the true one. Where it isn't, the determinant is worked out again in integers,
exactly: every float is a whole number times a power of two, so scaled by a
common power of two they are whole numbers, and Python's integers don't
round. Almost every sign is settled by the first; the second costs a few
microseconds each.

The one assumption: no coordinate is smaller than 1e-50 without being zero
(see :data:`SMALLEST`), so that no product in the first pass underflows. The
mesh view refuses meshes that break it.

>>> import numpy as np
>>> a, b, c = np.array([[0.0, 0, 0]]), np.array([[1.0, 0, 0]]), np.array([[0.0, 1, 0]])
>>> orient3d(a, b, c, np.array([[0.0, 0, -1]])).tolist(), orient3d(a, b, c, np.array([[0.3, 0.3, 0]])).tolist()
([1], [0])
>>> orient2d(a[:, :2], b[:, :2], c[:, :2]).tolist()
[1]
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from numpy.typing import NDArray

__all__ = [
    "LARGEST",
    "SMALLEST",
    "orient2d",
    "orient2d_filtered",
    "orient2d_one",
    "orient3d",
    "orient3d_filtered",
    "orient3d_one",
]

#: Coordinates must be zero or at least this large in size, so that no product
#: of three differences underflows and the error bounds hold.
SMALLEST = 1e-50
#: Nor larger in size than this, so that no product or square overflows.
LARGEST = 1e30

_EPSILON = 2.0**-53
_O3D_BOUND = (7.0 + 56.0 * _EPSILON) * _EPSILON
_O2D_BOUND = (3.0 + 16.0 * _EPSILON) * _EPSILON

Points = NDArray[np.float64]
Signs = NDArray[np.int8]


def _integers(values: Sequence[float]) -> list[int]:
    """The values as whole numbers, all scaled by one power of two."""
    ratios = [float(v).as_integer_ratio() for v in values]
    common = max(d for _, d in ratios)
    return [n * (common // d) for n, d in ratios]


def _sign(value: int) -> int:
    return (value > 0) - (value < 0)


def orient3d_one(a: Sequence[float], b: Sequence[float], c: Sequence[float],
                 d: Sequence[float]) -> int:  # fmt: skip
    """The exact sign of ``det[a - d; b - d; c - d]``, worked out in integers.

    Positive when ``d`` lies below the plane through ``a``, ``b``, ``c``, below
    being the side from which they turn clockwise.

    >>> orient3d_one((0, 0, 0), (1, 0, 0), (0, 1, 0), (0.1, 0.1, 1e-300))
    -1
    """
    ax, ay, az, bx, by, bz, cx, cy, cz, dx, dy, dz = _integers([*a, *b, *c, *d])
    adx, ady, adz = ax - dx, ay - dy, az - dz
    bdx, bdy, bdz = bx - dx, by - dy, bz - dz
    cdx, cdy, cdz = cx - dx, cy - dy, cz - dz
    return _sign(
        adz * (bdx * cdy - cdx * bdy)
        + bdz * (cdx * ady - adx * cdy)
        + cdz * (adx * bdy - bdx * ady)
    )


def orient2d_one(a: Sequence[float], b: Sequence[float], c: Sequence[float]) -> int:
    """The exact sign of ``det[a - c; b - c]``: positive when a, b, c turn anticlockwise.

    >>> orient2d_one((0, 0), (1, 0), (2, 1e-300))
    1
    """
    ax, ay, bx, by, cx, cy = _integers([*a, *b, *c])
    return _sign((ax - cx) * (by - cy) - (ay - cy) * (bx - cx))


def orient3d_filtered(
    a: Points, b: Points, c: Points, d: Points
) -> tuple[Signs, NDArray[np.bool_]]:
    """The floating-point pass of :func:`orient3d`: the signs, and which of them are sure."""
    adx, ady, adz = a[:, 0] - d[:, 0], a[:, 1] - d[:, 1], a[:, 2] - d[:, 2]
    bdx, bdy, bdz = b[:, 0] - d[:, 0], b[:, 1] - d[:, 1], b[:, 2] - d[:, 2]
    cdx, cdy, cdz = c[:, 0] - d[:, 0], c[:, 1] - d[:, 1], c[:, 2] - d[:, 2]
    bdxcdy, cdxbdy = bdx * cdy, cdx * bdy
    cdxady, adxcdy = cdx * ady, adx * cdy
    adxbdy, bdxady = adx * bdy, bdx * ady
    det = adz * (bdxcdy - cdxbdy) + bdz * (cdxady - adxcdy) + cdz * (adxbdy - bdxady)
    permanent = (
        (np.abs(bdxcdy) + np.abs(cdxbdy)) * np.abs(adz)
        + (np.abs(cdxady) + np.abs(adxcdy)) * np.abs(bdz)
        + (np.abs(adxbdy) + np.abs(bdxady)) * np.abs(cdz)
    )
    # A difference of two floats is zero only when they are equal, and no
    # product underflows (SMALLEST), so a permanent of zero is an exact zero.
    sure = (np.abs(det) > _O3D_BOUND * permanent) | (permanent == 0.0)
    return np.sign(det).astype(np.int8), sure


def orient3d(a: Points, b: Points, c: Points, d: Points) -> Signs:
    """:func:`orient3d_one` for each row of four ``(n, 3)`` arrays: exact signs, as int8."""
    signs, sure = orient3d_filtered(a, b, c, d)
    for i in np.flatnonzero(~sure).tolist():
        signs[i] = orient3d_one(a[i], b[i], c[i], d[i])
    return signs


def orient2d_filtered(
    a: Points, b: Points, c: Points
) -> tuple[Signs, NDArray[np.bool_]]:
    """The floating-point pass of :func:`orient2d`: the signs, and which of them are sure."""
    left = (a[:, 0] - c[:, 0]) * (b[:, 1] - c[:, 1])
    right = (a[:, 1] - c[:, 1]) * (b[:, 0] - c[:, 0])
    det = left - right
    permanent = np.abs(left) + np.abs(right)
    sure = (np.abs(det) > _O2D_BOUND * permanent) | (permanent == 0.0)
    return np.sign(det).astype(np.int8), sure


def orient2d(a: Points, b: Points, c: Points) -> Signs:
    """:func:`orient2d_one` for each row of three ``(n, 2)`` arrays: exact signs, as int8."""
    signs, sure = orient2d_filtered(a, b, c)
    for i in np.flatnonzero(~sure).tolist():
        signs[i] = orient2d_one(a[i], b[i], c[i])
    return signs
