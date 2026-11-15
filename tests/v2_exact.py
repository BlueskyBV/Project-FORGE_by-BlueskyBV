"""Exact geometry in rationals and integers, for checking the mesh view's floating-point answers.

Independent of forge_checks: nothing here imports it. Slow, so the tests use
it on small meshes and samples of points.

- :func:`distance2`: a point's exact squared distance to a closed triangle;
- :func:`side`: a point's exact side of a closed mesh: ON if it lies on a
  triangle, else inside or outside by the parity of an exact ray, cast again
  in another random direction if it meets a side, a corner or a plane edge-on.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from fractions import Fraction

import numpy as np
from numpy.typing import NDArray

Vec = tuple[Fraction, Fraction, Fraction]
IVec = list[int]


def exact(point: Sequence[float]) -> Vec:
    x, y, z = (Fraction(float(v)) for v in point)
    return (x, y, z)


def _sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a: Vec, b: Vec) -> Fraction:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec, b: Vec) -> Vec:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def distance2(p: Vec, a: Vec, b: Vec, c: Vec) -> Fraction:
    """The exact squared distance from ``p`` to the closed triangle ``abc``."""
    n = _cross(_sub(b, a), _sub(c, a))
    nn = _dot(n, n)
    best: Fraction | None = None
    if nn:
        t = _dot(_sub(p, a), n) / nn
        q = (p[0] - n[0] * t, p[1] - n[1] * t, p[2] - n[2] * t)
        if all(
            _dot(_cross(_sub(v, u), _sub(q, u)), n) >= 0
            for u, v in ((a, b), (b, c), (c, a))
        ):
            best = _dot(_sub(p, q), _sub(p, q))
    for u, v in ((a, b), (b, c), (c, a)):
        e = _sub(v, u)
        ee = _dot(e, e)
        s = (
            min(max(_dot(_sub(p, u), e) / ee, Fraction(0)), Fraction(1))
            if ee
            else Fraction(0)
        )
        q = (u[0] + e[0] * s, u[1] + e[1] * s, u[2] + e[2] * s)
        d = _dot(_sub(p, q), _sub(p, q))
        if best is None or d < best:
            best = d
    assert best is not None
    return best


def _scaled(values: list[float]) -> list[int]:
    """The values as whole numbers, all scaled by one power of two."""
    ratios = [v.as_integer_ratio() for v in values]
    common = max(d for _, d in ratios)
    return [n * (common // d) for n, d in ratios]


def _isub(a: IVec, b: IVec) -> IVec:
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _icross(a: IVec, b: IVec) -> IVec:
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]


def _idot(a: IVec, b: IVec) -> int:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def side(soup: NDArray[np.float64], point: Sequence[float], seed: int = 0) -> int:
    """+1 inside, -1 outside, 0 on the surface: exactly (the mesh must be closed and sound)."""
    values = _scaled(
        [float(v) for v in np.asarray(soup).reshape(-1)] + [float(v) for v in point]
    )
    *corners, ox, oy, oz = values
    o = [ox, oy, oz]
    tris = [(corners[9 * k : 9 * k + 3], corners[9 * k + 3 : 9 * k + 6], corners[9 * k + 6 : 9 * k + 9])
            for k in range(len(soup))]  # fmt: skip
    for a, b, c in tris:
        n = _icross(_isub(b, a), _isub(c, a))
        if _idot(n, _isub(o, a)) == 0 and all(
            _idot(_icross(_isub(v, u), _isub(o, u)), n) >= 0
            for u, v in ((a, b), (b, c), (c, a))
        ):
            return 0
    rng = random.Random(seed)
    for _ in range(50):
        d = [rng.randint(-(10**12), 10**12) for _ in range(3)]
        count, clean = 0, True
        for a, b, c in tris:
            ao, bo, co = _isub(a, o), _isub(b, o), _isub(c, o)
            va, vb, vc = (
                _idot(d, _icross(bo, co)),
                _idot(d, _icross(co, ao)),
                _idot(d, _icross(ao, bo)),
            )
            if (va > 0 or vb > 0 or vc > 0) and (va < 0 or vb < 0 or vc < 0):
                continue  # the ray's line misses the triangle
            if va == 0 or vb == 0 or vc == 0:
                clean = False  # through a side or a corner, or edge-on
                break
            n = _icross(_isub(b, a), _isub(c, a))
            ahead = _idot(n, ao) * _idot(n, d)
            if ahead == 0:
                clean = False
                break
            count += ahead > 0
        if clean:
            return 1 if count % 2 else -1
    raise RuntimeError("no clean ray in 50 tries")
