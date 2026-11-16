"""Exact solids: signed distance, nearest surface point, outward normal, and the facets at a point.

The oracle builds the spec's shape from these (:mod:`forge_checks.oracle`).
Every solid here is one of:

- a **prism**: a convex outline in a plane, pushed straight between two
  planes across it: blocks, posts, ribs, plain and round-ended tabs, rods,
  bosses, holes, counterbores, slots, pockets, letters' boxes;
- a **frustum**: a cone between two planes across its axis, either end's
  radius possibly 0: cones, countersinks;
- a **ball**;
- a **torus**: the solid a disc sweeps turning round an axis;
- a **round** space: everything within a radius of an endless axis;
- a **half-space**: everything on one side of a plane;

or the complement of one. All but the torus are convex, so near a point on
their surface each is, to first order, the intersection of the half-spaces
of the facets the point is on: a flat face, a strip of a round side, a
cap, a corner's arc. :meth:`Solid.facets` gives their outward normals,
from which the oracle settles a point that lies on several surfaces at once.
A torus's surface is smooth: one facet everywhere. The only point that is
none of these is a cone's apex, where :meth:`Solid.facets` says None.

Distances are exact closed forms, accurate to rounding (a few units in the
last place of the coordinates), so each solid's signed distance is the true
distance to its surface, 1-Lipschitz, which is what the oracle's bounds
and culling rest on.

>>> import numpy as np
>>> box = Prism.box((0, 0, 0), (10, 4, 2))
>>> box.signed_distance(np.array([[5.0, 2.0, 1.0], [12.0, 7.0, 1.0]])).tolist()
[-1.0, 3.605551275463989]
>>> rod = Prism(Frame.along((0, 0, 0), (0, 0, 1)), Disc(3.0), 0.0, 10.0)
>>> q, n = rod.nearest(np.array([[5.0, 0.0, 4.0]]))
>>> q.tolist(), n.tolist()
([[3.0, 0.0, 4.0]], [[1.0, 0.0, 0.0]])
>>> sorted(n.tolist() for n in box.facets((10.0, 4.0, 1.0)))
[[0.0, 1.0, 0.0], [1.0, 0.0, 0.0]]
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
from forge_numeric import scalar as fs
from forge_numeric import vector as fv
from numpy.typing import NDArray

__all__ = [
    "INSIDE",
    "ON",
    "OUTSIDE",
    "SINGULAR",
    "SURFACE",
    "Ball",
    "Complement",
    "Disc",
    "Frame",
    "Frustum",
    "Halfspace",
    "Local",
    "Locals",
    "Polygon",
    "Prism",
    "Revolved",
    "Round",
    "RoundRect",
    "Shape2D",
    "Solid",
    "Torus",
]

Array = NDArray[np.float64]
Vec = tuple[float, float, float]

#: A point this close to a surface is on it (mm).
ON = 1e-9

_INF = math.inf


def _unit(v: Sequence[float] | NDArray[np.float64]) -> NDArray[np.float64]:
    a = np.asarray(v, dtype=np.float64)
    length = float(fv.norm(a))
    if not math.isfinite(length) or length == 0.0:
        raise ValueError(f"not a direction: {v}")
    return a / length


def _on_axis(frame: Frame, c: float) -> Vec:
    """The point ``c`` along a frame's third axis, in the world."""
    o, w = frame.origin, frame.w
    return (o[0] + c * w[0], o[1] + c * w[1], o[2] + c * w[2])


@dataclass(frozen=True)
class Frame:
    """An origin and three orthonormal axes, right-handed: local (a, b, c) to the frame and back."""

    origin: Vec
    u: Vec
    v: Vec
    w: Vec

    @staticmethod
    def along(origin: Sequence[float] | Array, axis: Sequence[float] | Array) -> Frame:
        """A frame whose third axis is ``axis``; the first two are the frame's own for a frame axis.

        Along +z the first two are x and y; along +x, y and z; along +y, z and
        x (so they turn the right way round every axis). Along any other
        direction, the first is the direction across it nearest a frame axis.
        """
        w = _unit(axis)
        k = int(np.argmax(np.abs(w)))
        if np.count_nonzero(w) == 1:  # a frame axis, exactly
            u = np.array(
                {0: (0.0, 1.0, 0.0), 1: (0.0, 0.0, 1.0), 2: (1.0, 0.0, 0.0)}[k]
            )
            v = np.cross(w, u)
        else:
            e = np.zeros(3)
            e[int(np.argmin(np.abs(w)))] = 1.0
            u = _unit(np.asarray(np.cross(e, w), dtype=np.float64))
            v = np.cross(w, u)
        o = tuple(float(x) for x in origin)
        return Frame(
            (o[0], o[1], o[2]),
            (float(u[0]), float(u[1]), float(u[2])),
            (float(v[0]), float(v[1]), float(v[2])),
            (float(w[0]), float(w[1]), float(w[2])),
        )

    def local(self, points: Array) -> tuple[Array, Array, Array]:
        d = points - np.asarray(self.origin)
        abc = fv.matmul(d, np.array([self.u, self.v, self.w]).T)
        return abc[..., 0], abc[..., 1], abc[..., 2]

    def world(self, a: Array, b: Array, c: Array) -> Array:
        return np.asarray(
            np.asarray(self.origin)
            + a[:, None] * np.asarray(self.u)
            + b[:, None] * np.asarray(self.v)
            + c[:, None] * np.asarray(self.w)
        )

    def turn(self, a: Array, b: Array, c: Array) -> Array:
        """A direction from local components to the frame's."""
        return np.asarray(
            a[:, None] * np.asarray(self.u)
            + b[:, None] * np.asarray(self.v)
            + c[:, None] * np.asarray(self.w)
        )


# ----------------------------------------------------------------------
# Outlines in a plane, many points at a time
# ----------------------------------------------------------------------
class Shape2D:
    """A convex outline: its signed distance, nearest edge point and outward normal there.

    Its edge is a closed run of straight sides and arcs, anticlockwise.
    """

    lo: tuple[float, float]
    hi: tuple[float, float]

    def inside(self, a: Array, b: Array) -> NDArray[np.bool_]:
        raise NotImplementedError

    def pieces(self) -> list[tuple[str, tuple[float, ...]]]:
        """The edge's pieces: ("seg", (x0, y0, x1, y1)) or ("arc", (cx, cy, r, start, sweep))."""
        raise NotImplementedError

    def edge(self, a: Array, b: Array) -> tuple[Array, Array, Array, Array, Array]:
        """For each point: its distance to the edge, the nearest edge point, and the outward normal there."""
        best = np.full(a.shape, _INF)
        qa, qb = np.zeros_like(a), np.zeros_like(b)
        na, nb = np.zeros_like(a), np.zeros_like(b)
        for kind, data in self.pieces():
            if kind == "seg":
                x0, y0, x1, y1 = data
                dx, dy = x1 - x0, y1 - y0
                length2 = dx * dx + dy * dy
                t = np.clip(((a - x0) * dx + (b - y0) * dy) / length2, 0.0, 1.0)
                pa, pb = x0 + t * dx, y0 + t * dy
                length = math.sqrt(length2)
                ma, mb = np.full_like(a, dy / length), np.full_like(a, -dx / length)
            else:
                cx, cy, r, start, sweep = data
                angle = fv.arctan2(b - cy, a - cx)
                along = np.mod(angle - start, 2 * math.pi)
                on_arc = along <= sweep
                end = np.where(
                    along - sweep < 2 * math.pi - along, start + sweep, start
                )
                use = np.where(on_arc, angle, end)
                ma, mb = fv.cos(use), fv.sin(use)
                pa, pb = cx + r * ma, cy + r * mb
            d = fv.hypot(a - pa, b - pb)
            nearer = d < best
            best = np.where(nearer, d, best)
            qa, qb = np.where(nearer, pa, qa), np.where(nearer, pb, qb)
            na, nb = np.where(nearer, ma, na), np.where(nearer, mb, nb)
        return best, qa, qb, na, nb

    def distance(self, a: Array, b: Array) -> Array:
        """Each point's distance to the edge (what :meth:`edge` gives first, alone)."""
        best = np.full(a.shape, _INF)
        for kind, data in self.pieces():
            if kind == "seg":
                x0, y0, x1, y1 = data
                dx, dy = x1 - x0, y1 - y0
                t = np.clip(
                    ((a - x0) * dx + (b - y0) * dy) / (dx * dx + dy * dy), 0.0, 1.0
                )
                d = fv.hypot(a - (x0 + t * dx), b - (y0 + t * dy))
            else:
                cx, cy, r, start, sweep = data
                angle = fv.arctan2(b - cy, a - cx)
                along = np.mod(angle - start, 2 * math.pi)
                end = np.where(
                    along - sweep < 2 * math.pi - along, start + sweep, start
                )
                use = np.where(along <= sweep, angle, end)
                d = fv.hypot(a - (cx + r * fv.cos(use)), b - (cy + r * fv.sin(use)))
            np.minimum(best, d, out=best)
        return best

    def sd(self, a: Array, b: Array) -> Array:
        d = self.distance(a, b)
        return np.where(self.inside(a, b), -d, d)

    def nearest2d(self, a: Array, b: Array) -> tuple[Array, Array, Array, Array, Array]:
        """The signed distance, the nearest edge point, and the outward normal there.

        Outside, the normal is the way from the nearest point to the point (at
        a sharp corner, any way between its sides' normals); inside and on the
        edge, the nearest piece's.
        """
        d, qa, qb, na, nb = self.edge(a, b)
        inside = self.inside(a, b)
        out = ~inside & (d > 0)
        da, db = a - qa, b - qb
        length = fv.hypot(da, db)
        safe = out & (length > 0)
        na = np.where(safe, da / np.where(safe, length, 1.0), na)
        nb = np.where(safe, db / np.where(safe, length, 1.0), nb)
        return np.where(inside, -d, d), qa, qb, na, nb

    def facet_normals(self, a: Array, b: Array, eps: float) -> Array:
        """The outward normal of each piece of the edge within ``eps`` of each point: (n, pieces, 2), NaN where it isn't."""
        pieces = self.pieces()
        found = np.full((len(a), len(pieces), 2), np.nan)
        for k, (kind, data) in enumerate(pieces):
            if kind == "seg":
                x0, y0, x1, y1 = data
                dx, dy = x1 - x0, y1 - y0
                length2 = dx * dx + dy * dy
                t = np.clip(((a - x0) * dx + (b - y0) * dy) / length2, 0.0, 1.0)
                near = fv.hypot(a - (x0 + t * dx), b - (y0 + t * dy)) <= eps
                length = math.sqrt(length2)
                found[near, k, 0] = dy / length
                found[near, k, 1] = -dx / length
            else:
                cx, cy, r, start, sweep = data
                angle = fv.arctan2(b - cy, a - cx)
                along = np.mod(angle - start, 2 * math.pi)
                # The arc's nearest point: at the point's own angle, or the nearer end.
                end = np.where(
                    along - sweep < 2 * math.pi - along, start + sweep, start
                )
                at = np.where(along <= sweep, angle, end)
                qa, qb = cx + r * fv.cos(at), cy + r * fv.sin(at)
                near = fv.hypot(a - qa, b - qb) <= eps
                found[near, k, 0] = fv.cos(at[near])
                found[near, k, 1] = fv.sin(at[near])
        return found

    def meets(self, a: Array, b: Array, da: Array, db: Array) -> Array:
        """Where each line ``(a, b) + t (da, db)`` may meet the edge: each side's line and each arc's circle, (n, k)."""
        found = []
        for kind, data in self.pieces():
            if kind == "seg":
                x0, y0, x1, y1 = data
                nx, ny = y1 - y0, x0 - x1
                found.append(
                    _plane((a - x0) * nx + (b - y0) * ny, da * nx + db * ny)[:, None]
                )
            else:
                cx, cy, r, _, _ = data
                ra, rb = a - cx, b - cy
                found.append(
                    _quadratic(
                        da * da + db * db,
                        2 * (ra * da + rb * db),
                        ra * ra + rb * rb - r * r,
                    )
                )
        return np.concatenate(found, axis=1)

    def facets(self, a: float, b: float, eps: float) -> list[tuple[float, float]]:
        """The outward normals of the edge's pieces within ``eps`` of the point."""
        rows = self.facet_normals(
            np.array([a], dtype=float), np.array([b], dtype=float), eps
        )[0]
        return [(float(x), float(y)) for x, y in rows if not math.isnan(x)]


@dataclass(frozen=True, eq=False)
class _OffAxis(Shape2D):
    """A convex outline in the half-plane of (distance from an axis, height), less the sides of it on the axis.

    Turned round the axis, a side on the axis is inside the solid, not on
    its surface: its distance, nearest points and facets are the other
    sides'.
    """

    outline: Polygon
    lo: tuple[float, float] = field(init=False)
    hi: tuple[float, float] = field(init=False)
    sides: tuple[tuple[str, tuple[float, ...]], ...] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "lo", self.outline.lo)
        object.__setattr__(self, "hi", self.outline.hi)
        found = tuple(
            piece
            for piece in self.outline.pieces()
            if not (piece[1][0] == 0 and piece[1][2] == 0)
        )
        object.__setattr__(self, "sides", found)

    def inside(self, a: Array, b: Array) -> NDArray[np.bool_]:
        return self.outline.inside(a, b)

    def pieces(self) -> list[tuple[str, tuple[float, ...]]]:
        return list(self.sides)


@dataclass(frozen=True)
class Disc(Shape2D):
    """A disc of radius ``r`` about the origin."""

    r: float
    lo: tuple[float, float] = field(init=False)
    hi: tuple[float, float] = field(init=False)

    def __post_init__(self) -> None:
        if not (math.isfinite(self.r) and self.r > 0):
            raise ValueError(f"a disc has a radius: {self.r}")
        object.__setattr__(self, "lo", (-self.r, -self.r))
        object.__setattr__(self, "hi", (self.r, self.r))

    def inside(self, a: Array, b: Array) -> NDArray[np.bool_]:
        return fv.hypot(a, b) <= self.r

    def pieces(self) -> list[tuple[str, tuple[float, ...]]]:
        return [("arc", (0.0, 0.0, self.r, 0.0, 2 * math.pi))]

    def sd(self, a: Array, b: Array) -> Array:
        return fv.hypot(a, b) - self.r

    def edge(self, a: Array, b: Array) -> tuple[Array, Array, Array, Array, Array]:
        rho = fv.hypot(a, b)
        safe = rho > 0
        na = np.where(safe, a / np.where(safe, rho, 1.0), 1.0)
        nb = np.where(safe, b / np.where(safe, rho, 1.0), 0.0)
        return np.abs(rho - self.r), self.r * na, self.r * nb, na, nb


@dataclass(frozen=True)
class RoundRect(Shape2D):
    """A rectangle about the origin, half sizes ``h1``, ``h2``, each corner rounded by its own radius.

    Corners by quadrant: (+, +), (-, +), (-, -), (+, -). The two corners at
    the ends of a side may take up the whole side, no more (a slot's round
    end, a round-ended tab's).
    """

    h1: float
    h2: float
    corners: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    lo: tuple[float, float] = field(init=False)
    hi: tuple[float, float] = field(init=False)

    def __post_init__(self) -> None:
        if not all(math.isfinite(x) for x in (self.h1, self.h2, *self.corners)):
            raise ValueError(
                f"a rectangle's sizes are finite: {self.h1}, {self.h2}, {self.corners}"
            )
        if self.h1 <= 0 or self.h2 <= 0 or min(self.corners) < 0:
            raise ValueError(
                f"a rectangle has some size and corners of 0 or more: {self.h1}, {self.h2}, {self.corners}"
            )
        r1, r2, r3, r4 = self.corners
        sides = ((r1 + r4, 2 * self.h2), (r1 + r2, 2 * self.h1), (r2 + r3, 2 * self.h2), (r3 + r4, 2 * self.h1))  # fmt: skip
        if any(used > room * (1 + 1e-12) for used, room in sides):
            raise ValueError(
                f"two rounded corners overlap along a side: {self.h1}, {self.h2}, {self.corners}"
            )
        object.__setattr__(self, "lo", (-self.h1, -self.h2))
        object.__setattr__(self, "hi", (self.h1, self.h2))

    def _centre(self, k: int) -> tuple[float, float]:
        s1, s2 = ((1, 1), (-1, 1), (-1, -1), (1, -1))[k]
        r = self.corners[k]
        return s1 * (self.h1 - r), s2 * (self.h2 - r)

    def inside(self, a: Array, b: Array) -> NDArray[np.bool_]:
        found = (np.abs(a) <= self.h1) & (np.abs(b) <= self.h2)
        for k, (s1, s2) in enumerate(((1, 1), (-1, 1), (-1, -1), (1, -1))):
            r = self.corners[k]
            if r > 0:
                cx, cy = self._centre(k)
                corner = (s1 * a > self.h1 - r) & (s2 * b > self.h2 - r)
                found &= ~corner | (fv.hypot(a - cx, b - cy) <= r)
        return found

    def pieces(self) -> list[tuple[str, tuple[float, ...]]]:
        h1, h2 = self.h1, self.h2
        r1, r2, r3, r4 = self.corners
        straight = (
            (h1 - r1, h2, -h1 + r2, h2),
            (-h1, h2 - r2, -h1, -h2 + r3),
            (-h1 + r3, -h2, h1 - r4, -h2),
            (h1, -h2 + r4, h1, h2 - r1),
        )
        found: list[tuple[str, tuple[float, ...]]] = []
        for k in range(4):
            r = self.corners[k]
            if r > 0:
                cx, cy = self._centre(k)
                found.append(("arc", (cx, cy, r, k * math.pi / 2, math.pi / 2)))
            x0, y0, x1, y1 = straight[k]
            if (x0, y0) != (x1, y1):
                found.append(("seg", straight[k]))
        return found


@dataclass(frozen=True)
class Polygon(Shape2D):
    """A convex polygon, its corners anticlockwise."""

    corners: tuple[tuple[float, float], ...]
    lo: tuple[float, float] = field(init=False)
    hi: tuple[float, float] = field(init=False)

    def __post_init__(self) -> None:
        pts = self.corners
        if len(pts) < 3 or not all(math.isfinite(c) for p in pts for c in p):
            raise ValueError(f"a polygon has three corners or more: {pts}")
        for k in range(len(pts)):
            (x0, y0), (x1, y1), (x2, y2) = (
                pts[k],
                pts[(k + 1) % len(pts)],
                pts[(k + 2) % len(pts)],
            )
            if (x1 - x0) * (y2 - y1) - (y1 - y0) * (x2 - x1) <= 0:
                raise ValueError(f"a polygon turns left at every corner: {pts}")
        object.__setattr__(self, "lo", (min(p[0] for p in pts), min(p[1] for p in pts)))
        object.__setattr__(self, "hi", (max(p[0] for p in pts), max(p[1] for p in pts)))

    def inside(self, a: Array, b: Array) -> NDArray[np.bool_]:
        found = np.ones(a.shape, dtype=bool)
        n = len(self.corners)
        for k in range(n):
            (x0, y0), (x1, y1) = self.corners[k], self.corners[(k + 1) % n]
            found &= (x1 - x0) * (b - y0) - (y1 - y0) * (a - x0) >= 0
        return found

    def pieces(self) -> list[tuple[str, tuple[float, ...]]]:
        n = len(self.corners)
        return [
            ("seg", (*self.corners[k], *self.corners[(k + 1) % n])) for k in range(n)
        ]


# ----------------------------------------------------------------------
# Solids
# ----------------------------------------------------------------------
#: Where a point is, to a solid.
INSIDE, OUTSIDE, SURFACE, SINGULAR = 1, -1, 0, 2


@dataclass(frozen=True)
class Local:
    """A solid near one point, to first order.

    Inside or outside it; or on its surface, where it is the intersection of
    its facets' half-spaces there (``inverted``: the complement of that, for
    the complement of a convex solid); or at a singular point (a cone's apex).
    Where facets are taken together (``groups``, each facet's group), the
    solid there is the intersection, over the groups, of the union of each
    group's half-spaces: an inside corner of a line of letters is the union
    of its two walls' half-spaces, and where it meets their floor, that
    union met with the floor's.
    """

    where: int
    normals: tuple[NDArray[np.float64], ...] = ()
    inverted: bool = False
    groups: tuple[int, ...] = ()

    def toward(self, directions: Array) -> NDArray[np.bool_]:
        """Whether the solid holds the points just off this one along each direction."""
        if self.where == INSIDE:
            return np.ones(len(directions), dtype=bool)
        if self.where == OUTSIDE:
            return np.zeros(len(directions), dtype=bool)
        if self.where == SINGULAR:
            raise ValueError("a singular point has no first-order model")
        held = np.ones(len(directions), dtype=bool)
        groups = self.groups or tuple(range(len(self.normals)))
        for g in sorted(set(groups)):
            some = np.zeros(len(directions), dtype=bool)
            for n, k in zip(self.normals, groups, strict=True):
                if k == g:
                    some |= fv.matmul(directions, n) < 0
            held &= some
        return ~held if self.inverted else held


@dataclass(frozen=True, eq=False)
class Locals:
    """Many points' :class:`Local`: where each is, and the outward normals of the facets it is on.

    ``normals`` is (points, slots, 3), NaN in the slots a point doesn't use;
    ``inverted`` as in :class:`Local`, the same for every point of one solid;
    ``groups`` (points, slots), each slot's group (:class:`Local`), or None:
    each slot its own.
    """

    where: NDArray[np.int8]
    normals: Array
    inverted: bool = False
    groups: NDArray[np.int64] | None = None

    def __len__(self) -> int:
        return len(self.where)

    def __getitem__(self, i: int) -> Local:
        where = int(self.where[i])
        if where != SURFACE:
            return Local(where)
        rows = self.normals[i]
        used = [k for k in range(len(rows)) if not math.isnan(rows[k, 0])]
        found = tuple(rows[k].copy() for k in used)
        groups = (
            () if self.groups is None else tuple(int(self.groups[i, k]) for k in used)
        )
        return Local(SURFACE, found, self.inverted, groups)

    def held(self, dots: Array, unused: NDArray[np.bool_]) -> NDArray[np.bool_]:
        """Whether each point's solid holds the points just off it along each way: (points, ways), from the ways' dot products with each slot's normal (points, ways, slots) and the slots unused (points, 1, slots); ``inverted`` not applied."""
        ahead = dots < 0
        if self.groups is None:
            found: NDArray[np.bool_] = np.all(unused | ahead, axis=2)
            return found
        held = np.ones(dots.shape[:2], dtype=bool)
        for g in np.unique(self.groups[self.groups >= 0]):
            member = (self.groups == g)[:, None, :] & ~unused
            held &= ~member.any(axis=2) | (member & ahead).any(axis=2)
        return held


def _locals(
    sd: Array, eps: float, normals: Array, singular: NDArray[np.bool_] | None = None
) -> Locals:
    """Where each point is, from its signed distance; on the surface with no facet found, singular (as unsure)."""
    where = np.where(sd < -eps, INSIDE, np.where(sd > eps, OUTSIDE, SURFACE)).astype(
        np.int8
    )
    surface = where == SURFACE
    where[surface & np.all(np.isnan(normals[:, :, 0]), axis=1)] = SINGULAR
    if singular is not None:
        where[surface & singular] = SINGULAR
    normals[where != SURFACE] = np.nan
    return Locals(where, normals)


#: How near the surface a place a line may meet it must be, to be kept (mm): far above rounding, far below any feature.
_MEET = 1e-6
#: How near the surface a place found to half the digits may be, to be polished onto it (mm).
_POLISH = 1e-4
#: A place this near the surface (mm) is on its root to within :data:`ON` along any line steeper than
#: :data:`_STEEP`; one farther, up to :data:`_POLISH`, is polished.
_EXACT = 1e-12
#: The most steps of Newton's method a place is polished with (each squares how far it is off).
_NEWTON = 3
#: The least slope along a line a place is polished on (its normal's part along the line): less, and the line grazes.
_STEEP = 1e-3

#: Points round a circle its pieces' polynomials are read at: enough for degree 7 (a torus's is 4).
_ROUND = 16

#: How far off the unit circle a root may be and still be tried as a place (two crossings close together, found to half the digits).
_ROUND_NEAR = 1e-4


def _quadratic(qa: Array, qb: Array, qc: Array) -> Array:
    """The real roots of ``qa t^2 + qb t + qc`` (rounded so they lose nothing to cancellation), (n, 2), NaN where none.

    A line that grazes a round surface may come out a hair short of
    touching it: a discriminant below zero by rounding alone is taken as 0.
    """
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        disc = qb * qb - 4.0 * qa * qc
        graze = (disc < 0) & (disc >= -1e-12 * (qb * qb + np.abs(4.0 * qa * qc)))
        root = np.sqrt(np.where(graze, 0.0, disc))
        q = -0.5 * (qb + np.where(qb >= 0, root, -root))
        found = np.stack([q / qa, qc / q], axis=1)
        # A straight line (no square term): its one root.
        flat = qa == 0
        found[flat, 0] = -qc[flat] / qb[flat]
        found[flat, 1] = np.nan
    return np.asarray(np.where(np.isfinite(found), found, np.nan))


def _plane(offset: Array, rate: Array) -> Array:
    """Where ``offset + t rate`` is 0: (n,), NaN where it never is (or always)."""
    with np.errstate(divide="ignore", invalid="ignore"):
        found = -offset / rate
    return np.asarray(np.where(np.isfinite(found), found, np.nan))


class Solid:
    """A solid's closed forms. ``lo``, ``hi``: the box round it (infinite where it is endless)."""

    lo: Vec
    hi: Vec

    def locals(self, points: Array, eps: float = ON) -> Locals:
        """The solid near each point: inside, outside, or the facets there (one point at a time is :meth:`local`)."""
        raise NotImplementedError

    def local(self, point: Sequence[float], eps: float = ON) -> Local:
        """The solid near a point: inside, outside, or its facets there."""
        return self.locals(np.asarray(point, dtype=float)[None, :], eps)[0]

    def signed_distance(self, points: Array) -> Array:
        """How far each point is outside: negative inside, by how far it is from the surface."""
        raise NotImplementedError

    def nearest(self, points: Array) -> tuple[Array, Array]:
        """Each point's nearest surface point, and the outward unit normal there."""
        raise NotImplementedError

    def apexes(self) -> tuple[Vec, ...]:
        """The solid's singular points: where a cone of it comes to a point (none for most solids)."""
        return ()

    def facets(
        self, point: Sequence[float], eps: float = ON
    ) -> list[NDArray[np.float64]] | None:
        """The outward normals of the facets within ``eps`` of a point; None at a singular point."""
        local = self.local(point, eps)
        if local.where == SINGULAR:
            return None
        return list(local.normals) if local.where == SURFACE else []

    def crossings(self, origins: Array, directions: Array) -> Array:
        """Where each line ``origins[i] + t directions[i]`` (unit directions) meets the surface.

        (lines, k) distances ``t``, NaN where a line has fewer. Every place a
        line passes from inside the solid to outside or back is among them. A
        few more do no harm, and are dropped when they are not on the surface;
        a line that only touches the surface may or may not have the place it
        touches.
        """
        found = self._candidates(origins, directions)
        line, column = np.nonzero(np.isfinite(found))
        t = found[line, column]
        gap = self.signed_distance(origins[line] + t[:, None] * directions[line])
        on = np.abs(gap) <= _MEET
        # A root found to half the digits (a double one: two places together, or a surface the line touches)
        # may land a little past the surface, or on it by _MEET but, along a shallow line, off the place by
        # more than ON: up to _NEWTON steps of Newton's method along the line, on the surface's slope there
        # (its normal's part along the line), land it on the place, so that no sliver is left between it and
        # the same place found exactly (they are one within 2 ON). The nearest it came is kept, if on the
        # surface.
        near = np.flatnonzero((np.abs(gap) > _EXACT) & (np.abs(gap) <= _POLISH))
        best, best_gap = t[near], gap[near]
        tried, off = best.copy(), best_gap.copy()
        moving = np.arange(len(near))
        for _ in range(_NEWTON):
            moving = moving[np.abs(off[moving]) > _EXACT]
            if not len(moving):
                break
            rows = line[near[moving]]
            _, normal = self.nearest(
                origins[rows] + tried[moving, None] * directions[rows]
            )
            rate = fv.dot(normal, directions[rows])
            steep = np.abs(rate) >= _STEEP
            moving, rows, rate = moving[steep], rows[steep], rate[steep]
            tried[moving] -= off[moving] / rate
            off[moving] = self.signed_distance(
                origins[rows] + tried[moving, None] * directions[rows]
            )
            nearer = moving[np.abs(off[moving]) < np.abs(best_gap[moving])]
            best[nearer], best_gap[nearer] = tried[nearer], off[nearer]
        met = np.abs(best_gap) <= _MEET
        t[near[met]] = best[met]
        on[near[met]] = True
        kept = np.full(found.shape, np.nan)
        kept[line[on], column[on]] = t[on]
        return kept

    def _candidates(self, origins: Array, directions: Array) -> Array:
        """Every place each line may meet the surface: each smooth piece's surface carried on past its edges."""
        raise NotImplementedError

    def circle_crossings(
        self, centre: Array, u: Array, v: Array, radius: float
    ) -> Array:
        """Where the circle ``centre + radius (cos a u + sin a v)`` meets the surface: its angles ``a``, in order, in [0, 2 pi).

        ``u`` and ``v`` are unit and square. Every place the circle passes from
        inside the solid to outside or back, or onto or off a stretch of the
        surface it runs along (a circle in a prism's cap, where it crosses
        the outline), is among them: there it crosses the surface of some
        smooth piece carried on past its edges. A few more do no harm, and are
        dropped when they are not on the surface; a circle that only touches
        the surface may or may not have the place it touches, and one that
        lies on a piece's surface all round has none from it.

        Each piece's carried-on surface is a polynomial of degree ``d`` in
        the point (:meth:`_implicit`), so round the circle a trigonometric
        polynomial of degree ``d`` in the angle: its coefficients are exact
        from its values at :data:`_ROUND` points, and its places are the roots
        on the unit circle of ``z^d`` times it, in ``z = e^(i a)``, polished by
        Newton's method.
        """
        centre, u, v = (np.asarray(x, dtype=np.float64) for x in (centre, u, v))
        angles = 2 * math.pi * np.arange(_ROUND) / _ROUND
        sines, cosines = fv.sincos(angles)
        points = centre + radius * (cosines[:, None] * u + sines[:, None] * v)
        values, degrees = self._implicit(points)
        # The discrete Fourier transform of the values, (1/N) sum_j v_j e^(-2 pi i j m / N),
        # its real and imaginary parts as products with a table, in a fixed order.
        steps = np.outer(np.arange(_ROUND), np.arange(_ROUND)) % _ROUND
        table_sin, table_cos = fv.sincos(2 * math.pi * steps / _ROUND)
        spectrum_re = fv.matmul(table_cos, values) / _ROUND
        spectrum_im = -fv.matmul(table_sin, values) / _ROUND
        found: list[Array] = []
        for k, d in enumerate(degrees):
            which = np.arange(d, -d - 1, -1) % _ROUND
            cr, ci = spectrum_re[which, k], spectrum_im[which, k]
            scale = float(np.max(fv.hypot(cr, ci)))
            if scale == 0:
                continue
            cr, ci = cr / scale, ci / scale
            coeffs = cr.astype(np.complex128)
            coeffs.imag = ci
            roots = fv.roots(coeffs)
            on = np.abs(fv.hypot(roots.real, roots.imag) - 1.0) <= _ROUND_NEAR
            a = fv.arctan2(roots.imag[on], roots.real[on])
            powers = np.arange(d, -d - 1, -1, dtype=np.float64)
            for _ in range(3):
                # f(a) = Re sum_p c_p e^(i p a), and its derivative, in real arithmetic.
                s, c = fv.sincos(np.outer(a, powers))
                f = fv.matmul(c, cr) - fv.matmul(s, ci)
                df = -(fv.matmul(s, powers * cr) + fv.matmul(c, powers * ci))
                with np.errstate(divide="ignore", invalid="ignore"):
                    better = a - f / df
                a = np.where(np.isfinite(better), better, a)
            found.append(a)
        if not found:
            return np.zeros(0)
        a = np.mod(np.concatenate(found), 2 * math.pi)
        at = centre + radius * (fv.cos(a)[:, None] * u + fv.sin(a)[:, None] * v)
        keep = np.abs(self.signed_distance(at)) <= _MEET
        return np.sort(a[keep])

    def _implicit(self, points: Array) -> tuple[Array, tuple[int, ...]]:
        """Each smooth piece's surface carried on past its edges, as a polynomial of the point: its value at each point (n, pieces), and its degree."""
        raise NotImplementedError

    def own_patches(self) -> list[Patch] | None:
        """The smooth pieces of its surface, for a solid that works them out itself (a line of letters); else None."""
        return None

    def _smooth(self, points: Array, eps: float) -> Locals:
        """A smooth surface's: one facet, the nearest point's normal."""
        return _locals(
            self.signed_distance(points),
            eps,
            self.nearest(points)[1][:, None, :].copy(),
        )


def _box_of(
    frame: Frame,
    lo2: tuple[float, float],
    hi2: tuple[float, float],
    t0: float,
    t1: float,
) -> tuple[Vec, Vec]:
    corners = np.array(
        [
            [a, b, c]
            for a in (lo2[0], hi2[0])
            for b in (lo2[1], hi2[1])
            for c in (t0, t1)
        ],
        dtype=float,
    )
    world = frame.world(corners[:, 0], corners[:, 1], corners[:, 2])
    lo, hi = world.min(axis=0), world.max(axis=0)
    return (float(lo[0]), float(lo[1]), float(lo[2])), (
        float(hi[0]),
        float(hi[1]),
        float(hi[2]),
    )


@dataclass(frozen=True)
class Prism(Solid):
    """A convex outline in the frame's (a, b) plane, pushed along its third axis from ``t0`` to ``t1``."""

    frame: Frame
    shape: Shape2D
    t0: float
    t1: float
    lo: Vec = field(init=False)
    hi: Vec = field(init=False)

    def __post_init__(self) -> None:
        if not (
            math.isfinite(self.t0) and math.isfinite(self.t1) and self.t1 > self.t0
        ):
            raise ValueError(f"a prism runs a positive length: {self.t0}, {self.t1}")
        lo, hi = _box_of(self.frame, self.shape.lo, self.shape.hi, self.t0, self.t1)
        object.__setattr__(self, "lo", lo)
        object.__setattr__(self, "hi", hi)

    @staticmethod
    def box(lo: Sequence[float], hi: Sequence[float]) -> Prism:
        """An axis-aligned box."""
        if not all(hi[k] > lo[k] for k in range(3)):
            raise ValueError(f"a box has some size: {lo}, {hi}")
        centre = ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2])
        frame = Frame(centre, (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        return Prism(
            frame,
            RoundRect((hi[0] - lo[0]) / 2, (hi[1] - lo[1]) / 2),
            0.0,
            hi[2] - lo[2],
        )

    def _parts(self, points: Array) -> tuple[Array, Array, Array, Array, Array]:
        a, b, c = self.frame.local(points)
        d2 = self.shape.sd(a, b)
        dz = np.maximum(self.t0 - c, c - self.t1)
        return a, b, c, d2, dz

    def signed_distance(self, points: Array) -> Array:
        _, _, _, d2, dz = self._parts(points)
        inside = np.minimum(np.maximum(d2, dz), 0.0)
        return np.asarray(inside + fv.hypot(np.maximum(d2, 0.0), np.maximum(dz, 0.0)))

    def nearest(self, points: Array) -> tuple[Array, Array]:
        a, b, c, d2, dz = self._parts(points)
        _, qa, qb, na, nb = self.shape.nearest2d(a, b)
        cap = np.clip(c, self.t0, self.t1)
        up = np.where(c > (self.t0 + self.t1) / 2, 1.0, -1.0)
        near_cap = np.where(np.abs(c - self.t0) < np.abs(c - self.t1), self.t0, self.t1)
        cap_sign = np.where(near_cap == self.t1, 1.0, -1.0)
        outside_side, outside_cap = d2 > 0, dz > 0
        side = outside_side | (~outside_cap & (d2 >= dz))
        # On the side: the outline's nearest point at the point's height (or the rim's, beyond a cap).
        ra = np.where(side, qa, a)
        rb = np.where(side, qb, b)
        rc = np.where(side, cap, np.where(outside_cap, cap, near_cap))
        q = self.frame.world(ra, rb, rc)
        rim = outside_side & outside_cap
        normal = np.where(
            rim[:, None],
            points - q,
            np.where(
                side[:, None],
                self.frame.turn(na, nb, np.zeros_like(na)),
                self.frame.turn(
                    np.zeros_like(a),
                    np.zeros_like(a),
                    np.where(outside_cap, up, cap_sign),
                ),
            ),
        )
        length = fv.norm(normal, axis=1)
        return q, normal / np.where(length > 0, length, 1.0)[:, None]

    def _candidates(self, origins: Array, directions: Array) -> Array:
        a, b, c = self.frame.local(origins)
        da, db, dc = (
            fv.matmul(directions, np.asarray(x))
            for x in (self.frame.u, self.frame.v, self.frame.w)
        )
        caps = np.stack([_plane(c - self.t0, dc), _plane(c - self.t1, dc)], axis=1)
        return np.concatenate([caps, self.shape.meets(a, b, da, db)], axis=1)

    def _implicit(self, points: Array) -> tuple[Array, tuple[int, ...]]:
        a, b, c = self.frame.local(points)
        found, degrees = [c - self.t0, c - self.t1], [1, 1]
        for kind, data in self.shape.pieces():
            if kind == "seg":
                x0, y0, x1, y1 = data
                found.append((y1 - y0) * (a - x0) - (x1 - x0) * (b - y0))
                degrees.append(1)
            else:
                cx, cy, r, _, _ = data
                found.append(fv.sq(a - cx) + fv.sq(b - cy) - r * r)
                degrees.append(2)
        return np.stack(found, axis=1), tuple(degrees)

    def locals(self, points: Array, eps: float = ON) -> Locals:
        a, b, c, d2, dz = self._parts(points)
        inside = np.minimum(np.maximum(d2, dz), 0.0)
        sd = inside + fv.hypot(np.maximum(d2, 0.0), np.maximum(dz, 0.0))
        side = self.shape.facet_normals(a, b, eps)
        side[(c < self.t0 - eps) | (c > self.t1 + eps)] = np.nan
        u, v, w = (np.asarray(x) for x in (self.frame.u, self.frame.v, self.frame.w))
        count = side.shape[1]
        normals = np.full((len(points), count + 2, 3), np.nan)
        normals[:, :count] = side[:, :, 0:1] * u + side[:, :, 1:2] * v
        rim = d2 <= eps
        normals[rim & (np.abs(c - self.t0) <= eps), count] = -w
        normals[rim & (np.abs(c - self.t1) <= eps), count + 1] = w
        return _locals(np.asarray(sd), eps, normals)


@dataclass(frozen=True)
class Frustum(Solid):
    """A cone along the frame's third axis, radius ``r0`` at ``t0`` to ``r1`` at ``t1`` (either may be 0)."""

    frame: Frame
    t0: float
    t1: float
    r0: float
    r1: float
    lo: Vec = field(init=False)
    hi: Vec = field(init=False)
    section: Polygon = field(init=False)

    def __post_init__(self) -> None:
        values = (self.t0, self.t1, self.r0, self.r1)
        if not all(math.isfinite(x) for x in values) or self.t1 <= self.t0:
            raise ValueError(f"a frustum runs a positive length: {values}")
        if min(self.r0, self.r1) < 0 or max(self.r0, self.r1) <= 0:
            raise ValueError(f"a frustum has a radius: {values}")
        corners = [
            (self.r0, self.t0),
            (self.r1, self.t1),
            (-self.r1, self.t1),
            (-self.r0, self.t0),
        ]
        unique = [p for k, p in enumerate(corners) if p != corners[k - 1]]
        object.__setattr__(self, "section", Polygon(tuple(unique)))
        r = max(self.r0, self.r1)
        lo, hi = _box_of(self.frame, (-r, -r), (r, r), self.t0, self.t1)
        object.__setattr__(self, "lo", lo)
        object.__setattr__(self, "hi", hi)

    def _polar(self, points: Array) -> tuple[Array, Array, Array, Array]:
        a, b, c = self.frame.local(points)
        rho = fv.hypot(a, b)
        safe = rho > 0
        ca = np.where(safe, a / np.where(safe, rho, 1.0), 1.0)
        cb = np.where(safe, b / np.where(safe, rho, 1.0), 0.0)
        return rho, c, ca, cb

    def signed_distance(self, points: Array) -> Array:
        rho, c, _, _ = self._polar(points)
        return self.section.sd(rho, c)

    def nearest(self, points: Array) -> tuple[Array, Array]:
        rho, c, ca, cb = self._polar(points)
        _, qr, qc, nr, nc = self.section.nearest2d(rho, c)
        q = self.frame.world(qr * ca, qr * cb, qc)
        n = self.frame.turn(nr * ca, nr * cb, nc)
        return q, n / fv.norm(n, axis=1)[:, None]

    def _candidates(self, origins: Array, directions: Array) -> Array:
        a, b, c = self.frame.local(origins)
        da, db, dc = (
            fv.matmul(directions, np.asarray(x))
            for x in (self.frame.u, self.frame.v, self.frame.w)
        )
        caps = np.stack([_plane(c - self.t0, dc), _plane(c - self.t1, dc)], axis=1)
        # The cone's surface carried on both ways: a^2 + b^2 = r(c)^2, r growing by k along the axis.
        k = (self.r1 - self.r0) / (self.t1 - self.t0)
        r = self.r0 + (c - self.t0) * k
        side = _quadratic(
            da * da + db * db - fv.sq(k * dc),
            2 * (a * da + b * db - r * k * dc),
            a * a + b * b - r * r,
        )
        return np.concatenate([caps, side], axis=1)

    def _implicit(self, points: Array) -> tuple[Array, tuple[int, ...]]:
        a, b, c = self.frame.local(points)
        r = self.r0 + (c - self.t0) * (self.r1 - self.r0) / (self.t1 - self.t0)
        return np.stack([c - self.t0, c - self.t1, a * a + b * b - r * r], axis=1), (
            1,
            1,
            2,
        )

    def apexes(self) -> tuple[Vec, ...]:
        return tuple(
            _on_axis(self.frame, t)
            for r, t in ((self.r0, self.t0), (self.r1, self.t1))
            if r == 0
        )

    def locals(self, points: Array, eps: float = ON) -> Locals:
        rho, c, ca, cb = self._polar(points)
        sd = self.section.sd(rho, c)
        # The apex: no facets meet there, only a cone of them.
        apex = np.zeros(len(points), dtype=bool)
        for r, t in ((self.r0, self.t0), (self.r1, self.t1)):
            if r == 0:
                apex |= fv.hypot(rho, c - t) <= eps
        section = self.section.facet_normals(rho, c, eps)
        nr, nc = section[:, :, 0], section[:, :, 1]
        # The far half of the section is not a facet of the solid.
        far = (nr < 0) & (np.abs(nc) < 1)
        nr, nc = np.where(far, np.nan, nr), np.where(far, np.nan, nc)
        u, v, w = (np.asarray(x) for x in (self.frame.u, self.frame.v, self.frame.w))
        across = ca[:, None, None] * u + cb[:, None, None] * v
        normals = nr[:, :, None] * across + nc[:, :, None] * w
        normals /= fv.norm(normals, axis=2, keepdims=True)
        return _locals(sd, eps, normals, apex)


@dataclass(frozen=True)
class Ball(Solid):
    centre: Vec
    r: float
    lo: Vec = field(init=False)
    hi: Vec = field(init=False)

    def __post_init__(self) -> None:
        if not (math.isfinite(self.r) and self.r > 0):
            raise ValueError(f"a ball has a radius: {self.r}")
        c = self.centre
        object.__setattr__(self, "lo", (c[0] - self.r, c[1] - self.r, c[2] - self.r))
        object.__setattr__(self, "hi", (c[0] + self.r, c[1] + self.r, c[2] + self.r))

    def signed_distance(self, points: Array) -> Array:
        return np.asarray(fv.norm(points - np.asarray(self.centre), axis=1) - self.r)

    def nearest(self, points: Array) -> tuple[Array, Array]:
        d = points - np.asarray(self.centre)
        length = fv.norm(d, axis=1)
        n = np.where(
            (length > 0)[:, None],
            d / np.where(length > 0, length, 1.0)[:, None],
            np.array([0.0, 0.0, 1.0]),
        )
        return np.asarray(self.centre) + self.r * n, n

    def _candidates(self, origins: Array, directions: Array) -> Array:
        d = origins - np.asarray(self.centre)
        along = fv.dot(d, directions)
        return _quadratic(fv.dot(directions, directions), 2 * along,
                          fv.dot(d, d) - self.r * self.r)  # fmt: skip

    def _implicit(self, points: Array) -> tuple[Array, tuple[int, ...]]:
        d = points - np.asarray(self.centre)
        return (fv.dot(d, d) - self.r * self.r)[:, None], (2,)

    def locals(self, points: Array, eps: float = ON) -> Locals:
        return self._smooth(points, eps)


@dataclass(frozen=True)
class Torus(Solid):
    """Everything within ``r`` of the circle of radius ``big`` round the frame's third axis, in its (a, b) plane.

    The circle may be narrower than the tube (``big < r``, as a rounding of a
    rim nearly as big as the rim makes): then the solid is what the tube's
    disc sweeps, bounded by the outer part of its surface alone, and the two
    points where that surface meets the axis are singular (a cone of facets,
    as at a frustum's apex). With ``big == 0`` it is a ball.
    """

    frame: Frame
    big: float
    r: float
    lo: Vec = field(init=False)
    hi: Vec = field(init=False)

    def __post_init__(self) -> None:
        if not (
            math.isfinite(self.big)
            and math.isfinite(self.r)
            and self.big >= 0
            and self.r > 0
        ):
            raise ValueError(
                f"a torus has a tube and a circle of 0 or more: {self.big}, {self.r}"
            )
        reach = self.big + self.r
        lo, hi = _box_of(self.frame, (-reach, -reach), (reach, reach), -self.r, self.r)
        object.__setattr__(self, "lo", lo)
        object.__setattr__(self, "hi", hi)

    def _meridian(self, points: Array) -> tuple[Array, Array, Array, Array]:
        a, b, c = self.frame.local(points)
        rho = fv.hypot(a, b)
        safe = rho > 0
        ca = np.where(safe, a / np.where(safe, rho, 1.0), 1.0)
        cb = np.where(safe, b / np.where(safe, rho, 1.0), 0.0)
        return rho, c, ca, cb

    def signed_distance(self, points: Array) -> Array:
        rho, c, _, _ = self._meridian(points)
        found = fv.hypot(rho - self.big, c) - self.r
        if 0 < self.big < self.r:
            # Where the tube's circle's nearest point is past the axis, the
            # surface's is where it meets the axis, above or below.
            dr, dc = rho - self.big, c
            length = fv.hypot(dr, dc)
            ur = np.where(length > 0, dr / np.where(length > 0, length, 1.0), 1.0)
            across = self.big + self.r * ur < 0
            if across.any():
                h = math.sqrt(self.r * self.r - self.big * self.big)
                pole = fv.hypot(rho, np.abs(c) - h)
                found = np.where(across, np.where(found < 0, -pole, pole), found)
        return np.asarray(found)

    def nearest(self, points: Array) -> tuple[Array, Array]:
        rho, c, ca, cb = self._meridian(points)
        dr, dc = rho - self.big, c
        length = fv.hypot(dr, dc)
        safe = length > 0
        ur = np.where(safe, dr / np.where(safe, length, 1.0), 1.0)
        uc = np.where(safe, dc / np.where(safe, length, 1.0), 0.0)
        if 0 < self.big < self.r:
            # Past the axis the tube's circle isn't the surface: its nearest
            # point is then where the surface meets the axis, above or below.
            across = self.big + self.r * ur < 0
            h = math.sqrt(self.r * self.r - self.big * self.big)
            ur = np.where(across, -self.big / self.r, ur)
            uc = np.where(across, np.where(c >= 0, h, -h) / self.r, uc)
        q = self.frame.world(
            (self.big + self.r * ur) * ca, (self.big + self.r * ur) * cb, self.r * uc
        )
        return q, self.frame.turn(ur * ca, ur * cb, uc)

    def _candidates(self, origins: Array, directions: Array) -> Array:
        # From the point of each line nearest the centre, s along it: the
        # torus's quartic (|p|^2 + R^2 - r^2)^2 = 4 R^2 (a^2 + b^2) in s: its real
        # roots (forge_numeric's, a near-real pair a double root), polished by
        # Newton's method.
        a, b, c = self.frame.local(origins)
        da, db, dc = (
            fv.matmul(directions, np.asarray(x))
            for x in (self.frame.u, self.frame.v, self.frame.w)
        )
        shift = a * da + b * db + c * dc
        a, b, c = a - shift * da, b - shift * db, c - shift * dc
        big2 = self.big * self.big
        g = a * a + b * b + c * c + big2 - self.r * self.r
        flat2 = da * da + db * db
        coeffs = np.stack(
            [
                np.zeros_like(a),
                2 * g - 4 * big2 * flat2,
                -8 * big2 * (a * da + b * db),
                g * g - 4 * big2 * (a * a + b * b),
            ],
            axis=1,
        )  # s^4 + 0 s^3 + c2 s^2 + c1 s + c0
        n = len(a)
        s_ = (
            fv.real_roots(np.concatenate([np.ones((n, 1)), coeffs], axis=1))
            if n
            else np.zeros((0, 4))
        )
        c2, c1, c0 = coeffs[:, 1:2], coeffs[:, 2:3], coeffs[:, 3:4]
        with np.errstate(divide="ignore", invalid="ignore"):
            for _ in range(3):
                f = ((s_ * s_ + c2) * s_ + c1) * s_ + c0
                df = (4 * s_ * s_ + 2 * c2) * s_ + c1
                better = s_ - f / df
                s_ = np.where(np.isfinite(better), better, s_)
        return np.asarray(s_ - shift[:, None])

    def _implicit(self, points: Array) -> tuple[Array, tuple[int, ...]]:
        a, b, c = self.frame.local(points)
        if self.big == 0:
            return (a * a + b * b + c * c - self.r * self.r)[:, None], (2,)
        big2 = self.big * self.big
        g = a * a + b * b + c * c + big2 - self.r * self.r
        return (g * g - 4 * big2 * (a * a + b * b))[:, None], (4,)

    def locals(self, points: Array, eps: float = ON) -> Locals:
        found = self._smooth(points, eps)
        if 0 < self.big <= self.r:
            # Where the surface meets the axis it comes to a point.
            rho, _, _, _ = self._meridian(points)
            pole = (found.where == SURFACE) & (rho <= eps)
            found.where[pole] = SINGULAR
            found.normals[pole] = np.nan
        return found


@dataclass(frozen=True)
class Revolved(Solid):
    """A convex outline in the half-plane of (distance from the axis, height), turned round the frame's third axis.

    No corner of the outline is across the axis (its distance is 0 or more).
    Off the axis it is a ring whose section is the outline; touching it, a
    solid round the axis (a side on the axis is inside, not on the surface).
    Its signed distance is the outline's at the point's own distance and
    height, to its sides off the axis: no point of the surface in another
    half-plane is nearer, since every one is at a distance 0 or more. Its
    surface is a flat ring or disc, a round band or a cone's band for each
    side off the axis; a corner on the axis where a side that isn't flat
    across it meets it is a cone's point (singular). Roundings and chamfers
    of round rims are made from these.
    """

    frame: Frame
    section: Polygon
    lo: Vec = field(init=False)
    hi: Vec = field(init=False)
    meridian: _OffAxis = field(init=False, repr=False, compare=False)
    #: The heights of the corners on the axis that are cones' points.
    points: tuple[float, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if min(x for x, _ in self.section.corners) < 0:
            raise ValueError(
                f"a revolved outline is off the axis or touches it: {self.section.corners}"
            )
        meridian = _OffAxis(self.section)
        object.__setattr__(self, "meridian", meridian)
        apexes = []
        for x, z in self.section.corners:
            if x == 0:
                meeting = [
                    d
                    for _, d in meridian.sides
                    if (d[0], d[1]) == (x, z) or (d[2], d[3]) == (x, z)
                ]
                if any(d[1] != d[3] for d in meeting):
                    apexes.append(z)
        object.__setattr__(self, "points", tuple(apexes))
        reach = max(x for x, _ in self.section.corners)
        lo, hi = _box_of(
            self.frame,
            (-reach, -reach),
            (reach, reach),
            self.section.lo[1],
            self.section.hi[1],
        )
        object.__setattr__(self, "lo", lo)
        object.__setattr__(self, "hi", hi)

    def _polar(self, points: Array) -> tuple[Array, Array, Array, Array]:
        a, b, c = self.frame.local(points)
        rho = fv.hypot(a, b)
        safe = rho > 0
        ca = np.where(safe, a / np.where(safe, rho, 1.0), 1.0)
        cb = np.where(safe, b / np.where(safe, rho, 1.0), 0.0)
        return rho, c, ca, cb

    def signed_distance(self, points: Array) -> Array:
        rho, c, _, _ = self._polar(points)
        return self.meridian.sd(rho, c)

    def nearest(self, points: Array) -> tuple[Array, Array]:
        rho, c, ca, cb = self._polar(points)
        _, qr, qc, nr, nc = self.meridian.nearest2d(rho, c)
        q = self.frame.world(qr * ca, qr * cb, qc)
        n = self.frame.turn(nr * ca, nr * cb, nc)
        return q, n / fv.norm(n, axis=1)[:, None]

    def _candidates(self, origins: Array, directions: Array) -> Array:
        # Each side's line, a rho + b z = k, met where a^2 (a0 + t da)^2 + ... = (k - b z(t))^2.
        a0, b0, z0 = self.frame.local(origins)
        da, db, dz = (
            fv.matmul(directions, np.asarray(x))
            for x in (self.frame.u, self.frame.v, self.frame.w)
        )
        across2 = da * da + db * db
        across1 = 2 * (a0 * da + b0 * db)
        across0 = a0 * a0 + b0 * b0
        found = []
        for _, (x0, y0, x1, y1) in self.meridian.sides:
            a, b = y1 - y0, x0 - x1
            if a == 0:
                # A flat side, a ring or disc at its height: a plane, met once. As a square, its root is
                # a double one, found to half the digits (a line along the axis came out a micrometre off).
                once = _plane(z0 - y0, dz)
                found.append(np.stack([once, np.full_like(once, np.nan)], axis=1))
                continue
            k = a * x0 + b * y0 - b * z0
            m = b * dz
            found.append(
                _quadratic(
                    a * a * across2 - m * m,
                    a * a * across1 + 2 * k * m,
                    a * a * across0 - k * k,
                )
            )
        return np.concatenate(found, axis=1)

    def _implicit(self, points: Array) -> tuple[Array, tuple[int, ...]]:
        # Each side's line a rho + b z = k turned round: a flat ring where a = 0, else a^2 rho^2 = (k - b z)^2.
        x, y, z = self.frame.local(points)
        found, degrees = [], []
        for _, (x0, y0, x1, y1) in self.meridian.sides:
            a, b = y1 - y0, x0 - x1
            k = a * x0 + b * y0
            if a == 0:
                found.append(z - y0)
                degrees.append(1)
            else:
                found.append(a * a * (x * x + y * y) - fv.sq(k - b * z))
                degrees.append(2)
        return np.stack(found, axis=1), tuple(degrees)

    def apexes(self) -> tuple[Vec, ...]:
        return tuple(_on_axis(self.frame, z) for z in self.points)

    def locals(self, points: Array, eps: float = ON) -> Locals:
        rho, c, ca, cb = self._polar(points)
        sd = self.meridian.sd(rho, c)
        section = self.meridian.facet_normals(rho, c, eps)
        nr, nc = section[:, :, 0], section[:, :, 1]
        u, v, w = (np.asarray(x) for x in (self.frame.u, self.frame.v, self.frame.w))
        across = ca[:, None, None] * u + cb[:, None, None] * v
        normals = nr[:, :, None] * across + nc[:, :, None] * w
        apex = np.zeros(len(points), dtype=bool)
        for z in self.points:
            apex |= fv.hypot(rho, c - z) <= eps
        return _locals(sd, eps, normals, apex)


@dataclass(frozen=True)
class Round(Solid):
    """Everything within ``r`` of an endless axis through the frame's origin along its third axis."""

    frame: Frame
    r: float
    lo: Vec = field(init=False)
    hi: Vec = field(init=False)

    def __post_init__(self) -> None:
        if not (math.isfinite(self.r) and self.r > 0):
            raise ValueError(f"a round space has a radius: {self.r}")
        object.__setattr__(self, "lo", (-_INF, -_INF, -_INF))
        object.__setattr__(self, "hi", (_INF, _INF, _INF))

    def signed_distance(self, points: Array) -> Array:
        a, b, _ = self.frame.local(points)
        return fv.hypot(a, b) - self.r

    def nearest(self, points: Array) -> tuple[Array, Array]:
        a, b, c = self.frame.local(points)
        rho = fv.hypot(a, b)
        safe = rho > 0
        ca = np.where(safe, a / np.where(safe, rho, 1.0), 1.0)
        cb = np.where(safe, b / np.where(safe, rho, 1.0), 0.0)
        return self.frame.world(self.r * ca, self.r * cb, c), self.frame.turn(
            ca, cb, np.zeros_like(ca)
        )

    def _candidates(self, origins: Array, directions: Array) -> Array:
        a, b, _ = self.frame.local(origins)
        da, db = (
            fv.matmul(directions, np.asarray(self.frame.u)),
            fv.matmul(directions, np.asarray(self.frame.v)),
        )
        return _quadratic(
            da * da + db * db, 2 * (a * da + b * db), a * a + b * b - self.r * self.r
        )

    def _implicit(self, points: Array) -> tuple[Array, tuple[int, ...]]:
        a, b, _ = self.frame.local(points)
        return (a * a + b * b - self.r * self.r)[:, None], (2,)

    def locals(self, points: Array, eps: float = ON) -> Locals:
        return self._smooth(points, eps)


@dataclass(frozen=True)
class Halfspace(Solid):
    """Everything on the side of a plane its normal points away from: ``(p - point) . normal <= 0``."""

    point: Vec
    normal: Vec
    lo: Vec = field(init=False)
    hi: Vec = field(init=False)

    def __post_init__(self) -> None:
        n = _unit(self.normal)
        object.__setattr__(self, "normal", (float(n[0]), float(n[1]), float(n[2])))
        lo, hi = [-_INF] * 3, [_INF] * 3
        k = int(np.argmax(np.abs(n)))
        if np.count_nonzero(n) == 1:  # a frame plane, exactly: bounded on one side
            if n[k] > 0:
                hi[k] = self.point[k]
            else:
                lo[k] = self.point[k]
        object.__setattr__(self, "lo", (lo[0], lo[1], lo[2]))
        object.__setattr__(self, "hi", (hi[0], hi[1], hi[2]))

    def signed_distance(self, points: Array) -> Array:
        return np.asarray(
            fv.matmul(points - np.asarray(self.point), np.asarray(self.normal))
        )

    def nearest(self, points: Array) -> tuple[Array, Array]:
        n = np.asarray(self.normal)
        d = self.signed_distance(points)
        return points - d[:, None] * n, np.broadcast_to(n, points.shape).copy()

    def _candidates(self, origins: Array, directions: Array) -> Array:
        n = np.asarray(self.normal)
        return _plane(
            fv.matmul(origins - np.asarray(self.point), n), fv.matmul(directions, n)
        )[:, None]

    def _implicit(self, points: Array) -> tuple[Array, tuple[int, ...]]:
        return self.signed_distance(points)[:, None], (1,)

    def locals(self, points: Array, eps: float = ON) -> Locals:
        return self._smooth(points, eps)


@dataclass(frozen=True)
class Complement(Solid):
    """Everything not in a solid (its surface is the solid's, facing the other way)."""

    of: Solid
    lo: Vec = field(init=False, default=(-_INF, -_INF, -_INF))
    hi: Vec = field(init=False, default=(_INF, _INF, _INF))

    def signed_distance(self, points: Array) -> Array:
        return -self.of.signed_distance(points)

    def nearest(self, points: Array) -> tuple[Array, Array]:
        q, n = self.of.nearest(points)
        return q, -n

    def _candidates(self, origins: Array, directions: Array) -> Array:
        return self.of._candidates(origins, directions)

    def _implicit(self, points: Array) -> tuple[Array, tuple[int, ...]]:
        return self.of._implicit(points)

    def locals(self, points: Array, eps: float = ON) -> Locals:
        inner = self.of.locals(points, eps)
        where = np.where(
            inner.where == INSIDE,
            OUTSIDE,
            np.where(inner.where == OUTSIDE, INSIDE, inner.where),
        )
        return Locals(
            where.astype(np.int8), inner.normals, not inner.inverted, inner.groups
        )

    def facets(
        self, point: Sequence[float], eps: float = ON
    ) -> list[NDArray[np.float64]] | None:
        found = self.of.facets(point, eps)
        return None if found is None else [-n for n in found]


# ----------------------------------------------------------------------
# Patches: the smooth pieces of a solid's surface
# ----------------------------------------------------------------------
class Patch:
    """One smooth piece of a solid's surface, over parameters ``(u, v)`` in ``[0, U] x [0, V]``.

    The parameters are lengths along the surface, or shorter (a step of the
    parameter moves a point no farther than the step): so every point of a
    cell of the parameters lies within half the cell's diagonal of its
    centre. Some points of the rectangle may be off the patch (a cap's
    outline within its box): :meth:`at` says which. ``owner`` is the solid
    it is a piece of.
    """

    owner: Solid
    size: tuple[float, float]

    def at(self, u: Array, v: Array) -> tuple[Array, Array, NDArray[np.bool_]]:
        """The points at these parameters, the outward normals there, and which are on the patch."""
        raise NotImplementedError

    def inside(self, u: Array, v: Array, reach: Array) -> NDArray[np.int8]:
        """Whether the parameter disc of radius ``reach`` round each point is wholly on (1), off (-1) the patch, or both (0)."""
        return np.ones(len(u), dtype=np.int8)

    def foot(self, x: Array) -> Array:
        """The point of the patch nearest ``x``."""
        raise NotImplementedError

    def box(self) -> tuple[Vec, Vec] | None:
        """A box round the patch, where it is cheap to know (a stretch of a letter's wall); else None."""
        return None


@dataclass(frozen=True)
class FlatPatch(Patch):
    """A flat piece: an outline in a plane, ``origin + a e1 + b e2``, facing ``normal``."""

    owner: Solid
    origin: Vec
    e1: Vec
    e2: Vec
    normal: Vec
    shape: Shape2D
    size: tuple[float, float] = field(init=False)

    def __post_init__(self) -> None:
        lo, hi = self.shape.lo, self.shape.hi
        object.__setattr__(self, "size", (hi[0] - lo[0], hi[1] - lo[1]))

    def _ab(self, u: Array, v: Array) -> tuple[Array, Array]:
        return u + self.shape.lo[0], v + self.shape.lo[1]

    def at(self, u: Array, v: Array) -> tuple[Array, Array, NDArray[np.bool_]]:
        a, b = self._ab(u, v)
        points = (
            np.asarray(self.origin)
            + a[:, None] * np.asarray(self.e1)
            + b[:, None] * np.asarray(self.e2)
        )
        normals = np.broadcast_to(np.asarray(self.normal), points.shape).copy()
        return points, normals, self.shape.inside(a, b)

    def inside(self, u: Array, v: Array, reach: Array) -> NDArray[np.int8]:
        a, b = self._ab(u, v)
        d = self.shape.sd(a, b)
        return np.where(d <= -reach, 1, np.where(d >= reach, -1, 0)).astype(np.int8)

    def foot(self, x: Array) -> Array:
        d = np.asarray(x, dtype=float) - np.asarray(self.origin)
        a, b = (
            np.array([fv.matmul(d, np.asarray(self.e1))]),
            np.array([fv.matmul(d, np.asarray(self.e2))]),
        )
        if not self.shape.inside(a, b)[0]:
            _, a, b, _, _ = self.shape.edge(a, b)
        return np.asarray(
            np.asarray(self.origin)
            + a[0] * np.asarray(self.e1)
            + b[0] * np.asarray(self.e2)
        )


@dataclass(frozen=True)
class RoundPatch(Patch):
    """A piece of a round side: radius ``r`` about the line through ``centre`` along ``w``,
    from angle ``start`` (from ``e1`` towards ``e2``) through ``sweep``, from ``t0`` to ``t1`` along it.
    ``sign`` is 1 where the solid is inside the round surface, -1 outside it."""

    owner: Solid
    centre: Vec
    e1: Vec
    e2: Vec
    w: Vec
    r: float
    start: float
    sweep: float
    t0: float
    t1: float
    sign: float = 1.0
    size: tuple[float, float] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "size", (self.r * self.sweep, self.t1 - self.t0))

    def _radial(self, theta: Array) -> Array:
        cos, sin = fv.cos(theta)[:, None], fv.sin(theta)[:, None]
        return np.asarray(cos * np.asarray(self.e1) + sin * np.asarray(self.e2))

    def at(self, u: Array, v: Array) -> tuple[Array, Array, NDArray[np.bool_]]:
        theta = self.start + u / self.r
        radial = self._radial(theta)
        points = (
            np.asarray(self.centre)
            + self.r * radial
            + (self.t0 + v)[:, None] * np.asarray(self.w)
        )
        return points, self.sign * radial, np.ones(len(u), dtype=bool)

    def foot(self, x: Array) -> Array:
        d = np.asarray(x, dtype=float) - np.asarray(self.centre)
        a, b, c = (
            fv.matmul(d, np.asarray(self.e1)),
            fv.matmul(d, np.asarray(self.e2)),
            fv.matmul(d, np.asarray(self.w)),
        )
        theta = fs.atan2(b, a)
        along = (theta - self.start) % (2 * math.pi)
        if along > self.sweep:  # off the arc: its nearer end
            along = self.sweep if along - self.sweep < 2 * math.pi - along else 0.0
        t = min(max(c, self.t0), self.t1)
        return np.asarray(
            self.at(np.array([along * self.r]), np.array([t - self.t0]))[0][0]
        )


@dataclass(frozen=True)
class ConePatch(Patch):
    """A frustum's side: from radius ``r0`` at ``t0`` to ``r1`` at ``t1`` about ``w`` through ``origin``."""

    owner: Solid
    origin: Vec
    e1: Vec
    e2: Vec
    w: Vec
    r0: float
    r1: float
    t0: float
    t1: float
    size: tuple[float, float] = field(init=False)

    def __post_init__(self) -> None:
        slant = math.hypot(self.r1 - self.r0, self.t1 - self.t0)
        object.__setattr__(self, "size", (slant, 2 * math.pi * max(self.r0, self.r1)))

    def _section(self, s: Array) -> tuple[Array, Array]:
        return self.r0 + (self.r1 - self.r0) * s, self.t0 + (self.t1 - self.t0) * s

    def at(self, u: Array, v: Array) -> tuple[Array, Array, NDArray[np.bool_]]:
        slant = self.size[0]
        s = u / slant
        rho, t = self._section(s)
        theta = v / max(self.r0, self.r1)
        radial = fv.cos(theta)[:, None] * np.asarray(self.e1) + fv.sin(theta)[
            :, None
        ] * np.asarray(self.e2)
        points = (
            np.asarray(self.origin)
            + rho[:, None] * radial
            + t[:, None] * np.asarray(self.w)
        )
        # The section's outward normal: (t1 - t0, -(r1 - r0)), turned round the axis.
        nr, nc = (self.t1 - self.t0) / slant, -(self.r1 - self.r0) / slant
        normals = nr * radial + nc * np.asarray(self.w)
        return points, normals, np.ones(len(u), dtype=bool)

    def foot(self, x: Array) -> Array:
        d = np.asarray(x, dtype=float) - np.asarray(self.origin)
        a, b, c = (
            fv.matmul(d, np.asarray(self.e1)),
            fv.matmul(d, np.asarray(self.e2)),
            fv.matmul(d, np.asarray(self.w)),
        )
        rho = math.hypot(a, b)
        dr, dt = self.r1 - self.r0, self.t1 - self.t0
        s = min(
            max(((rho - self.r0) * dr + (c - self.t0) * dt) / (dr * dr + dt * dt), 0.0),
            1.0,
        )
        theta = fs.atan2(b, a) % (2 * math.pi)
        found = self.at(
            np.array([s * self.size[0]]), np.array([theta * max(self.r0, self.r1)])
        )
        return np.asarray(found[0][0])


@dataclass(frozen=True)
class SpherePatch(Patch):
    """A ball's surface, ``u`` its polar arc from ``w`` and ``v`` its arc round ``w`` (at the equator)."""

    owner: Solid
    centre: Vec
    e1: Vec
    e2: Vec
    w: Vec
    r: float
    size: tuple[float, float] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "size", (math.pi * self.r, 2 * math.pi * self.r))

    def at(self, u: Array, v: Array) -> tuple[Array, Array, NDArray[np.bool_]]:
        phi, theta = u / self.r, v / self.r
        n = (
            (fv.sin(phi) * fv.cos(theta))[:, None] * np.asarray(self.e1)
            + (fv.sin(phi) * fv.sin(theta))[:, None] * np.asarray(self.e2)
            + fv.cos(phi)[:, None] * np.asarray(self.w)
        )
        return np.asarray(self.centre) + self.r * n, n, np.ones(len(u), dtype=bool)

    def foot(self, x: Array) -> Array:
        d = np.asarray(x, dtype=float) - np.asarray(self.centre)
        length = float(fv.norm(d))
        n = d / length if length > 0 else np.asarray(self.w)
        return np.asarray(np.asarray(self.centre) + self.r * n)


@dataclass(frozen=True)
class TorusPatch(Patch):
    """A torus's surface: ``u`` round its axis (at its outer equator), ``v`` round its tube.

    Where the tube crosses the axis, only the part of it outside the axis is
    the surface: ``v`` runs over that part alone.
    """

    owner: Solid
    centre: Vec
    e1: Vec
    e2: Vec
    w: Vec
    big: float
    r: float
    size: tuple[float, float] = field(init=False)
    phi0: float = field(init=False)

    def __post_init__(self) -> None:
        reach = math.pi if self.big >= self.r else fs.acos(-self.big / self.r)
        object.__setattr__(self, "phi0", -reach)
        object.__setattr__(
            self, "size", (2 * math.pi * (self.big + self.r), 2 * reach * self.r)
        )

    def at(self, u: Array, v: Array) -> tuple[Array, Array, NDArray[np.bool_]]:
        theta, phi = u / (self.big + self.r), self.phi0 + v / self.r
        radial = fv.cos(theta)[:, None] * np.asarray(self.e1) + fv.sin(theta)[
            :, None
        ] * np.asarray(self.e2)
        n = fv.cos(phi)[:, None] * radial + fv.sin(phi)[:, None] * np.asarray(self.w)
        points = np.asarray(self.centre) + self.big * radial + self.r * n
        return points, n, np.ones(len(u), dtype=bool)

    def foot(self, x: Array) -> Array:
        q, _ = (
            self.owner.nearest(np.asarray(x, dtype=float)[None, :])
            if isinstance(self.owner, Torus)
            else (None, None)
        )
        assert q is not None
        return np.asarray(q[0])


@dataclass(frozen=True)
class Flipped(Patch):
    """A patch of a complement: the same points, facing the other way."""

    of: Patch
    owner: Solid
    size: tuple[float, float] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "size", self.of.size)

    def at(self, u: Array, v: Array) -> tuple[Array, Array, NDArray[np.bool_]]:
        p, n, valid = self.of.at(u, v)
        return p, -n, valid

    def inside(self, u: Array, v: Array, reach: Array) -> NDArray[np.int8]:
        return self.of.inside(u, v, reach)

    def foot(self, x: Array) -> Array:
        return self.of.foot(x)


def _clip_polygon(
    origin: Array, e1: Array, e2: Array, lo: Vec, hi: Vec
) -> Polygon | None:
    """The convex polygon where the plane through ``origin`` (spanned by ``e1``, ``e2``) crosses a box, in the plane's coordinates.

    Its corners are the box's corners on the plane and the points where the
    plane crosses the box's edges; their convex hull, with corners that make
    no turn (a crossing a hair from a box corner) left out. None if the plane
    only touches the box.
    """
    corners = np.array(
        [
            [x, y, z]
            for x in (lo[0], hi[0])
            for y in (lo[1], hi[1])
            for z in (lo[2], hi[2])
        ]
    )
    n = np.cross(e1, e2)
    side = fv.matmul(corners - origin, n)
    found = [corners[i] for i in range(8) if side[i] == 0]
    for i in range(8):
        for j in range(i + 1, 8):
            if bin(i ^ j).count("1") != 1:
                continue  # not an edge of the box
            si, sj = side[i], side[j]
            if (si < 0 < sj) or (sj < 0 < si):
                found.append(corners[i] + (corners[j] - corners[i]) * (si / (si - sj)))
    if len(found) < 3:
        return None
    pts = sorted(
        {
            (float(fv.matmul(q - origin, e1)), float(fv.matmul(q - origin, e2)))
            for q in found
        }
    )
    size = max(max(abs(x), abs(y)) for x, y in pts) + float(
        np.max(np.abs(corners - origin))
    )
    least = fv.sq(1e-12 * size)

    def turn(
        o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]
    ) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    # Andrew's monotone chain: the lower and upper hulls, anticlockwise, turns only.
    hull: list[tuple[float, float]] = []
    for chain in (pts, pts[::-1]):
        part: list[tuple[float, float]] = []
        for q in chain:
            while len(part) >= 2 and turn(part[-2], part[-1], q) <= least:
                part.pop()
            part.append(q)
        hull += part[:-1]
    try:
        return Polygon(tuple(hull))
    except ValueError:
        return None  # it only touches the box


def patches(solid: Solid, lo: Vec, hi: Vec) -> list[Patch]:
    """The smooth pieces of a solid's surface (an endless one's within the box ``lo``, ``hi``)."""
    own = solid.own_patches()
    if own is not None:
        return own
    if isinstance(solid, Complement):
        return [Flipped(p, solid) for p in patches(solid.of, lo, hi)]
    if isinstance(solid, Prism):
        f = solid.frame
        o, u, v, w = (np.asarray(x, dtype=float) for x in (f.origin, f.u, f.v, f.w))
        found: list[Patch] = []
        for kind, data in solid.shape.pieces():
            if kind == "seg":
                x0, y0, x1, y1 = data
                length = math.hypot(x1 - x0, y1 - y0)
                d = ((x1 - x0) * u + (y1 - y0) * v) / length
                n2 = ((y1 - y0) * u - (x1 - x0) * v) / length
                start = o + x0 * u + y0 * v + solid.t0 * w
                rect = RoundRect(length / 2, (solid.t1 - solid.t0) / 2)
                found.append(
                    FlatPatch(
                        solid,
                        _vec(start + d * length / 2 + w * (solid.t1 - solid.t0) / 2),
                        _vec(d),
                        _vec(w),
                        _vec(n2),
                        rect,
                    )
                )
            else:
                cx, cy, r, s0, sweep = data
                found.append(
                    RoundPatch(
                        solid,
                        _vec(o + cx * u + cy * v),
                        _vec(u),
                        _vec(v),
                        _vec(w),
                        r,
                        s0,
                        sweep,
                        solid.t0,
                        solid.t1,
                    )
                )
        for t, sign in ((solid.t0, -1.0), (solid.t1, 1.0)):
            found.append(
                FlatPatch(
                    solid,
                    _vec(o + t * w),
                    _vec(u),
                    _vec(v),
                    _vec(sign * w),
                    solid.shape,
                )
            )
        return found
    if isinstance(solid, Frustum):
        f = solid.frame
        o, u, v, w = (np.asarray(x, dtype=float) for x in (f.origin, f.u, f.v, f.w))
        found = [
            ConePatch(
                solid, f.origin, f.u, f.v, f.w, solid.r0, solid.r1, solid.t0, solid.t1
            )
        ]
        for r, t, sign in ((solid.r0, solid.t0, -1.0), (solid.r1, solid.t1, 1.0)):
            if r > 0:
                found.append(
                    FlatPatch(
                        solid,
                        _vec(o + t * w),
                        _vec(u),
                        _vec(v),
                        _vec(sign * w),
                        Disc(r),
                    )
                )
        return found
    if isinstance(solid, Revolved):
        f = solid.frame
        return [
            ConePatch(solid, f.origin, f.u, f.v, f.w, x0, x1, y0, y1)
            for _, (x0, y0, x1, y1) in solid.meridian.sides
        ]
    if isinstance(solid, Ball):
        return [
            SpherePatch(
                solid,
                solid.centre,
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (0.0, 0.0, 1.0),
                solid.r,
            )
        ]
    if isinstance(solid, Torus):
        f = solid.frame
        return [TorusPatch(solid, f.origin, f.u, f.v, f.w, solid.big, solid.r)]
    if isinstance(solid, Round):
        f = solid.frame
        o, w = np.asarray(f.origin, dtype=float), np.asarray(f.w, dtype=float)
        corners = np.array(
            [
                [x, y, z]
                for x in (lo[0], hi[0])
                for y in (lo[1], hi[1])
                for z in (lo[2], hi[2])
            ]
        )
        along = fv.matmul(corners - o, w)
        return [
            RoundPatch(
                solid,
                f.origin,
                f.u,
                f.v,
                f.w,
                solid.r,
                0.0,
                2 * math.pi,
                float(along.min()),
                float(along.max()),
            )
        ]
    if isinstance(solid, Halfspace):
        n = np.asarray(solid.normal, dtype=float)
        frame = Frame.along(solid.point, n)
        e1, e2 = np.asarray(frame.u), np.asarray(frame.v)
        polygon = _clip_polygon(np.asarray(solid.point, dtype=float), e1, e2, lo, hi)
        if polygon is None:
            return []
        return [FlatPatch(solid, solid.point, frame.u, frame.v, solid.normal, polygon)]
    raise TypeError(f"no patches for {type(solid).__name__}")


def _vec(v: Sequence[float] | Array) -> Vec:
    return (float(v[0]), float(v[1]), float(v[2]))
