"""One point and one triangle, or one ray and one triangle, many pairs at a time.

- :func:`unit_normals`: each triangle's unit normal, accurate to a few units
  in the last place however thin the triangle: the cross product is taken at
  the corner opposite the longest side, and where even that is too thin to
  trust in floating point (a needle, a cap), it is worked out in twice the
  precision (each difference and product kept with its rounding error), or
  exactly where even that could fall short.
- :func:`closest_points`: the nearest point of each triangle to each point,
  and which of the triangle's seven features it lies on (a corner, a side or
  the face): the point's foot on the triangle's plane, if it falls inside,
  else the nearest point of the three sides. Every step is a projection
  along an accurate unit vector, so the distance is right to within
  :data:`DISTANCE_ERROR` times the size of the coordinates, even on a sliver
  (Ericson's region formulas square the triangle's thinness and lose it).
- :func:`ray_hits`: where each ray crosses each triangle, by the watertight
  test of Woop, Benthin and Wald (*Watertight Ray/Triangle Intersection*,
  2013). A ray through the side two triangles share crosses exactly one of
  them, never both and never neither: the test is worked out from each
  corner's coordinates alone, the same way in both triangles, so where it
  says a ray passes on one side of the shared side for one triangle it says
  the other side for the other. A ray that passes exactly through a side or a
  corner is reported as **grazing**, and whoever cast it casts again.

>>> import numpy as np
>>> a, b, c = (np.array([v], dtype=float) for v in ((0, 0, 0), (1, 0, 0), (0, 1, 0)))
>>> n = unit_normals(a, b, c)
>>> q, region = closest_points(np.array([[2.0, -1.0, 5.0]]), a, b, c, n)
>>> n.tolist(), q.tolist(), region.tolist()
([[0.0, 0.0, 1.0]], [[1.0, 0.0, 0.0]], [1])
>>> hit, t, grazed, front = ray_hits(np.array([[0.2, 0.2, 3.0]]), np.array([[0.0, 0.0, -1.0]]), a, b, c)
>>> hit.tolist(), t.tolist(), grazed.tolist(), front.tolist()
([True], [3.0], [False], [True])
"""

from __future__ import annotations

import math
from fractions import Fraction

import numpy as np
from forge_numeric import vector as fv
from numpy.typing import NDArray

__all__ = [
    "DISTANCE_ERROR",
    "EDGE_AB",
    "EDGE_BC",
    "EDGE_CA",
    "FACE",
    "VERTEX_A",
    "VERTEX_B",
    "VERTEX_C",
    "closest_points",
    "features",
    "ray_hits",
    "unit_normals",
]

#: Which feature of a triangle a closest point lies on.
VERTEX_A, VERTEX_B, VERTEX_C, EDGE_AB, EDGE_BC, EDGE_CA, FACE = range(7)

#: A distance from :func:`closest_points` is within this many times
#: ``|p| + |corner|`` of the true distance (with :func:`unit_normals`' normals).
#: Rounding the sides and the cross product tilts a normal by at most about
#: 13 units in the last place when its widest angle's sine is at least
#: :data:`_THIN` (else it is exact); each projection adds a few more, and a
#: foot too near a side to call is measured to the side, within the slack of
#: the side's test (:data:`_SLACK`, three times over): about 75 in all. Tests
#: measure it against exact rationals on slivers, needles, caps and far-off
#: parts, where it stays near 4.
DISTANCE_ERROR = 128 * 2.0**-53

#: Below this sine of its widest angle (wider than 150 degrees), a triangle's
#: normal is worked out in twice the precision.
_THIN = 0.5
#: Below this sine, exactly: twice the precision leaves an error of about
#: 2^-103 / sine of the normal, which must stay far under its last place.
_NEEDLE = 2.0**-40
#: How far rounding may move a side's test of a point, in units of the
#: side's length times the distances involved.
_SLACK = 16.0 * 2.0**-53

Array = NDArray[np.float64]


def _dot(u: Array, v: Array) -> Array:
    return np.asarray(fv.dot(u, v), dtype=np.float64)


def _exact_normal(a: Array, b: Array, c: Array) -> tuple[float, float, float]:
    """The unit normal of one triangle, from its exact cross product, rounded once."""
    fa, fb, fc = ([Fraction(float(x)) for x in v] for v in (a, b, c))
    u = [fb[i] - fa[i] for i in range(3)]
    w = [fc[i] - fa[i] for i in range(3)]
    n = [
        u[1] * w[2] - u[2] * w[1],
        u[2] * w[0] - u[0] * w[2],
        u[0] * w[1] - u[1] * w[0],
    ]
    biggest = max(abs(x) for x in n)
    if biggest == 0:
        return (0.0, 0.0, 0.0)
    x, y, z = (float(v / biggest) for v in n)
    length = math.sqrt(x * x + y * y + z * z)
    return (x / length, y / length, z / length)


def _two_sum(x: Array, y: Array) -> tuple[Array, Array]:
    """``x + y`` and its rounding error, exactly (Knuth)."""
    s = x + y
    back = s - x
    return s, (x - (s - back)) + (y - back)


def _two_product(x: Array, y: Array) -> tuple[Array, Array]:
    """``x * y`` and its rounding error, exactly (Dekker, halves by Veltkamp's split)."""
    p = x * y
    xs, ys = 134217729.0 * x, 134217729.0 * y
    xh, yh = xs - (xs - x), ys - (ys - y)
    xl, yl = x - xh, y - yh
    return p, ((xh * yh - p) + xh * yl + xl * yh) + xl * yl


def _wide_normal(a: Array, b: Array, c: Array) -> Array:
    """Each triangle's cross product ``(b - a) x (c - a)`` in twice the precision, rounded once to unit length.

    Each side's coordinate is a sum of two doubles, exactly; each product of
    two of them is kept to about 2^-104 of its size, and so each component
    of the cross product to about 2^-103 of ``|b - a| |c - a|``.
    """
    u = [_two_sum(b[:, i], -a[:, i]) for i in range(3)]
    w = [_two_sum(c[:, i], -a[:, i]) for i in range(3)]

    def times(x: tuple[Array, Array], y: tuple[Array, Array]) -> tuple[Array, Array]:
        p, e = _two_product(x[0], y[0])
        return p, e + (x[0] * y[1] + x[1] * y[0])

    found = []
    for i, j in ((1, 2), (2, 0), (0, 1)):
        first, second = times(u[i], w[j]), times(u[j], w[i])
        s, e = _two_sum(first[0], -second[0])
        found.append(s + (e + (first[1] - second[1])))
    n = np.stack(found, axis=1)
    biggest = np.max(np.abs(n), axis=1, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        scaled = n / biggest
        return np.asarray(scaled / fv.norm(scaled, axis=1, keepdims=True))


def unit_normals(a: Array, b: Array, c: Array) -> Array:
    """Each triangle's unit normal (corners anticlockwise seen from its side); zero if it has no area.

    A triangle far out or very small (coordinates past 2^200 or within
    2^-200, where the square of its cross product would overflow or
    underflow) is first scaled by a power of two, which changes no digit of
    its coordinates and so not its normal.
    """
    far = np.max(np.abs(np.stack([a, b, c])), axis=(0, 2))
    odd = (far > 2.0**200) | ((far > 0) & (far < 2.0**-200))
    if np.any(odd):
        shift = np.where(odd, -np.frexp(far)[1], 0)[:, None]
        a, b, c = np.ldexp(a, shift), np.ldexp(b, shift), np.ldexp(c, shift)
    sides = np.stack([fv.norm(b - a, axis=1), fv.norm(c - b, axis=1),
                      fv.norm(a - c, axis=1)], axis=1)  # fmt: skip
    longest = np.argmax(sides, axis=1)
    # The corner opposite the longest side: its two sides are the shortest.
    corner = np.where(longest[:, None] == 1, a, np.where(longest[:, None] == 2, b, c))
    after = np.where(longest[:, None] == 1, b, np.where(longest[:, None] == 2, c, a))
    before = np.where(longest[:, None] == 1, c, np.where(longest[:, None] == 2, a, b))
    u, w = after - corner, before - corner
    cross = np.cross(u, w)
    size = fv.norm(cross, axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        sine = size / (fv.norm(u, axis=1) * fv.norm(w, axis=1))
        unit = cross / size[:, None]
    thin = ~(np.isfinite(unit).all(axis=1) & (sine >= _THIN))
    if thin.any():
        unit[thin] = _wide_normal(a[thin], b[thin], c[thin])
    exact = thin & ~(np.isfinite(unit).all(axis=1) & (sine >= _NEEDLE))
    for k in np.flatnonzero(exact).tolist():
        unit[k] = _exact_normal(a[k], b[k], c[k])
    return np.asarray(unit, dtype=np.float64)


def closest_points(
    p: Array, a: Array, b: Array, c: Array, normal: Array
) -> tuple[Array, NDArray[np.int8]]:
    """For each row: the point of triangle ``a, b, c`` nearest ``p``, and the feature it is on.

    ``normal`` is the triangle's unit normal, from :func:`unit_normals`.
    """
    n = len(p)
    best: Array = np.full(n, np.inf)
    q = np.zeros_like(p)
    region = np.full(n, -1, dtype=np.int8)
    for start, end, side, first, second in (
        (a, b, EDGE_AB, VERTEX_A, VERTEX_B),
        (b, c, EDGE_BC, VERTEX_B, VERTEX_C),
        (c, a, EDGE_CA, VERTEX_C, VERTEX_A),
    ):
        along = end - start
        length2 = _dot(along, along)
        with np.errstate(divide="ignore", invalid="ignore"):
            s = np.where(length2 > 0.0, _dot(p - start, along) / length2, 0.0)
        s = np.clip(s, 0.0, 1.0)
        here = np.where(
            (s <= 0.0)[:, None],
            start,
            np.where((s >= 1.0)[:, None], end, start + s[:, None] * along),
        )
        gap = p - here
        d2 = _dot(gap, gap)
        nearer = d2 < best
        best = np.where(nearer, d2, best)
        q[nearer] = here[nearer]
        kind = np.where(s <= 0.0, first, np.where(s >= 1.0, second, side))
        region[nearer] = kind[nearer]
    # The foot on the plane, where it surely falls inside the triangle, is
    # nearer still. Where rounding can't tell (the foot within its slack of a
    # side's line), the sides' nearest points stand: then the foot is that
    # close to a side, and they are as near as the foot to within the slack.
    # (Taking the foot there was wrong past a needle's tip, where both long
    # sides' lines pass within rounding of a foot that is far outside.)
    height = _dot(p - a, normal)
    foot = p - height[:, None] * normal
    inside = _dot(normal, normal) > 0.5
    for start, end in ((a, b), (b, c), (c, a)):
        edge = end - start
        side_ = np.asarray(np.cross(edge, foot - start), dtype=np.float64)
        slack = _SLACK * _norms_of(edge) * (_norms_of(foot - start) + _norms_of(edge))
        inside &= _dot(side_, normal) > slack
    inside &= height * height <= best
    q[inside] = foot[inside]
    region[inside] = FACE
    return q, region


def features(
    p: Array, a: Array, b: Array, c: Array, normal: Array
) -> tuple[Array, Array, NDArray[np.bool_]]:
    """For each row: the nearest point of each of the triangle's seven features, as far as rounding allows.

    Returns points ``(n, 7, 3)`` and distances ``(n, 7)``, in the order of the
    region codes (three corners, three sides, the face), and which of them
    may be the triangle's nearest feature: every corner; a side if the point's
    foot on its line may fall within it; the face if the foot on its plane
    may fall inside. "May" allows for rounding, so the feature truly nearest
    is never left out.
    """
    n = len(p)
    points = np.empty((n, 7, 3))
    valid = np.ones((n, 7), dtype=bool)
    tiny = _SLACK
    for k, corner in enumerate((a, b, c)):
        points[:, k] = corner
    for k, (start, end) in enumerate(((a, b), (b, c), (c, a))):
        along = end - start
        length2 = _dot(along, along)
        length = np.sqrt(length2)
        reach = _norms_of(p - start)
        with np.errstate(divide="ignore", invalid="ignore"):
            s = _dot(p - start, along) / length2
            slack = tiny * (reach + length) / length
        valid[:, 3 + k] = (length2 > 0.0) & (s > -slack) & (s < 1.0 + slack)
        s = np.clip(np.nan_to_num(s), 0.0, 1.0)
        points[:, 3 + k] = start + s[:, None] * along
    height = _dot(p - a, normal)
    foot = p - height[:, None] * normal
    points[:, 6] = foot
    inside = _dot(normal, normal) > 0.5
    for start, end in ((a, b), (b, c), (c, a)):
        edge = end - start
        side_ = np.asarray(np.cross(edge, foot - start), dtype=np.float64)
        slack = tiny * _norms_of(edge) * (_norms_of(foot - start) + _norms_of(edge))
        inside &= _dot(side_, normal) >= -slack
    valid[:, 6] = inside
    gap = p[:, None, :] - points
    distance = np.sqrt(fv.dot(gap, gap))
    return points, distance, valid


def _norms_of(v: Array) -> Array:
    return np.asarray(np.sqrt(_dot(v, v)), dtype=np.float64)


def ray_hits(
    origin: Array, direction: Array, a: Array, b: Array, c: Array
) -> tuple[NDArray[np.bool_], Array, NDArray[np.bool_], NDArray[np.bool_]]:
    """For each row: does the ray cross the triangle ahead of its origin, and where.

    Returns ``hit``, ``t`` (the distance along the ray, for unit directions),
    ``grazed`` (it meets the triangle exactly on a side or a corner, or lies
    in its plane) and ``front`` (it meets the side the triangle's corners turn
    anticlockwise on, its outside for an outward mesh: the ray is entering).
    """
    k = np.argmax(np.abs(direction), axis=1)
    rows = np.arange(len(k))
    dz = direction[rows, k]
    kx = (k + 1) % 3
    ky = (kx + 1) % 3
    # Keep the corners' turning the same when the main axis points backwards.
    flip = dz < 0.0
    kx, ky = np.where(flip, ky, kx), np.where(flip, kx, ky)
    sx = direction[rows, kx] / dz
    sy = direction[rows, ky] / dz
    sz = 1.0 / dz

    def sheared(corner: Array) -> tuple[Array, Array, Array]:
        local = corner - origin
        z = local[rows, k]
        return local[rows, kx] - sx * z, local[rows, ky] - sy * z, sz * z

    ax, ay, az = sheared(a)
    bx, by, bz = sheared(b)
    cx, cy, cz = sheared(c)
    u = cx * by - cy * bx
    v = ax * cy - ay * cx
    w = bx * ay - by * ax
    negative = (u < 0.0) | (v < 0.0) | (w < 0.0)
    positive = (u > 0.0) | (v > 0.0) | (w > 0.0)
    inside = ~(negative & positive)
    det = u + v + w
    with np.errstate(divide="ignore", invalid="ignore"):
        t = (u * az + v * bz + w * cz) / det
    edge = (u == 0.0) | (v == 0.0) | (w == 0.0)
    ahead = inside & (det != 0.0) & (t > 0.0)
    # On a side or a corner ahead, or in the triangle's plane (all three zero).
    grazed = inside & ((det == 0.0) | (edge & (t > 0.0)))
    return ahead, np.where(ahead, t, np.nan), grazed, det > 0.0
