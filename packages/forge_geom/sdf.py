"""Signed distance fields with tracked Lipschitz bounds and exact envelopes.

Every node in this module evaluates to a *signed distance* -- negative inside the
solid, positive outside, with magnitude equal to (or a lower bound on) the
distance to the boundary. That property is what makes rigorous measurement
possible: if a cube of half-diagonal ``r`` has ``|f(centre)| > r * L`` for the
field's Lipschitz bound ``L``, then the cube is provably entirely inside or
entirely outside the solid, with no sampling and no guessing.

Two pieces of bookkeeping make that guarantee real rather than aspirational.

**Lipschitz tracking.** Each node reports an upper bound on ``|grad f|``. The
exact primitives are 1-Lipschitz; ``min``/``max`` preserve that; a non-uniform
scale multiplies it by the largest scale factor. Any node that cannot honestly
claim a bound must say so, and measurement falls back to a wider interval rather
than producing a confident wrong number.

**Exact envelopes.** Each node computes its own axis-aligned bounding box
constructively -- a union hulls its operands, an intersection intersects them, a
blend grows by the blend radius. These envelopes are exact bounds derived from
the construction, not fitted to samples, so the measurement octree starts from a
box that provably contains the solid.

Why an implicit kernel at all
-----------------------------
It is not a substitute for OpenCascade, and Forge does not pretend it is: it
carries no B-Rep topology, so it cannot export STEP or drive a Fusion feature
tree. What it can do is run everywhere with no CAD kernel installed, evaluate a
design in milliseconds for optimisation screening, and -- because two independent
kernels computing the same volume is real evidence -- cross-check the B-Rep
backend. A disagreement between them beyond declared tolerance is a bug in one of
them, and Forge would rather find that than average it away.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

from . import ibounds as ib
from .ibounds import IArray

Array = np.ndarray

EPSILON = 1e-12


class GeometryError(Exception):
    """A geometric construction is degenerate or ill-posed."""

    code = "GE1000_GEOMETRY"

    def __init__(self, message: str, **detail: object) -> None:
        super().__init__(message)
        self.message = message
        self.detail = dict(detail)

    def as_dict(self) -> dict[str, object]:
        return {"code": self.code, "message": self.message, "detail": dict(self.detail)}

    def __str__(self) -> str:
        if self.detail:
            rendered = ", ".join(f"{k}={v!r}" for k, v in sorted(self.detail.items()))
            return f"[{self.code}] {self.message} ({rendered})"
        return f"[{self.code}] {self.message}"


class DegenerateGeometryError(GeometryError):
    code = "GE1001_DEGENERATE"


class EmptyResultError(GeometryError):
    code = "GE1002_EMPTY_RESULT"


# ----------------------------------------------------------------------
# Axis-aligned envelopes
# ----------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Box:
    """An axis-aligned bounding box in millimetres."""

    lo: tuple[float, float, float]
    hi: tuple[float, float, float]

    @classmethod
    def empty(cls) -> "Box":
        inf = float("inf")
        return cls((inf, inf, inf), (-inf, -inf, -inf))

    @classmethod
    def universe(cls) -> "Box":
        inf = float("inf")
        return cls((-inf, -inf, -inf), (inf, inf, inf))

    @classmethod
    def around(cls, centre: Sequence[float], half_extent: Sequence[float]) -> "Box":
        return cls(
            tuple(c - h for c, h in zip(centre, half_extent)),  # type: ignore[arg-type]
            tuple(c + h for c, h in zip(centre, half_extent)),  # type: ignore[arg-type]
        )

    @property
    def is_empty(self) -> bool:
        return any(lo > hi for lo, hi in zip(self.lo, self.hi))

    @property
    def size(self) -> tuple[float, float, float]:
        return tuple(max(0.0, hi - lo) for lo, hi in zip(self.lo, self.hi))  # type: ignore[return-value]

    @property
    def centre(self) -> tuple[float, float, float]:
        return tuple((lo + hi) / 2.0 for lo, hi in zip(self.lo, self.hi))  # type: ignore[return-value]

    @property
    def volume(self) -> float:
        sx, sy, sz = self.size
        return sx * sy * sz

    @property
    def diagonal(self) -> float:
        sx, sy, sz = self.size
        return math.sqrt(sx * sx + sy * sy + sz * sz)

    def union(self, other: "Box") -> "Box":
        if self.is_empty:
            return other
        if other.is_empty:
            return self
        return Box(
            tuple(min(a, b) for a, b in zip(self.lo, other.lo)),  # type: ignore[arg-type]
            tuple(max(a, b) for a, b in zip(self.hi, other.hi)),  # type: ignore[arg-type]
        )

    def intersection(self, other: "Box") -> "Box":
        return Box(
            tuple(max(a, b) for a, b in zip(self.lo, other.lo)),  # type: ignore[arg-type]
            tuple(min(a, b) for a, b in zip(self.hi, other.hi)),  # type: ignore[arg-type]
        )

    def grown(self, margin: float) -> "Box":
        if self.is_empty:
            return self
        return Box(
            tuple(v - margin for v in self.lo),  # type: ignore[arg-type]
            tuple(v + margin for v in self.hi),  # type: ignore[arg-type]
        )

    def transformed(self, rotation: Array, translation: Array) -> "Box":
        """Envelope of the rotated box: the exact AABB of the rotated corners."""
        if self.is_empty:
            return self
        corners = np.array(
            [
                [x, y, z]
                for x in (self.lo[0], self.hi[0])
                for y in (self.lo[1], self.hi[1])
                for z in (self.lo[2], self.hi[2])
            ],
            dtype=float,
        )
        moved = corners @ rotation.T + translation
        return Box(
            tuple(moved.min(axis=0).tolist()),  # type: ignore[arg-type]
            tuple(moved.max(axis=0).tolist()),  # type: ignore[arg-type]
        )

    def as_dict(self) -> dict[str, list[float]]:
        return {"lo": list(self.lo), "hi": list(self.hi)}


# ----------------------------------------------------------------------
# Base node
# ----------------------------------------------------------------------
class SDF:
    """Base class for signed-distance nodes.

    Subclasses implement :meth:`_evaluate` on an ``(N, 3)`` array of points and
    declare :attr:`envelope` and :attr:`lipschitz`.
    """

    __slots__ = ()

    #: Upper bound on |grad f| over R^3. Exact distance fields have 1.0.
    lipschitz: float = 1.0

    @property
    def envelope(self) -> Box:  # pragma: no cover - abstract
        raise NotImplementedError

    def _evaluate(self, points: Array) -> Array:  # pragma: no cover - abstract
        raise NotImplementedError

    def __call__(self, points: Array) -> Array:
        points = np.asarray(points, dtype=float)
        if points.ndim == 1:
            return self._evaluate(points.reshape(1, 3))[0]
        if points.ndim != 2 or points.shape[1] != 3:
            raise GeometryError(
                "SDF evaluation expects an (N, 3) array of points",
                shape=tuple(points.shape),
            )
        return self._evaluate(points)

    def contains(self, points: Array) -> Array:
        return self(points) <= 0.0

    def gradient(self, points: Array, *, step: float = 1e-5) -> Array:
        """Central-difference gradient, used for normals and Lipschitz checks."""
        points = np.asarray(points, dtype=float).reshape(-1, 3)
        gradient = np.empty_like(points)
        for axis in range(3):
            offset = np.zeros(3)
            offset[axis] = step
            gradient[:, axis] = (
                self(points + offset) - self(points - offset)
            ) / (2.0 * step)
        return gradient

    # -- interval bounds ------------------------------------------------
    def bounds(self, box: IArray) -> IArray:
        """Enclose the field's range over a batch of axis-aligned cells.

        ``box`` is an interval-valued ``(N, 3)`` point: the lower and upper
        corners of ``N`` cells. The return value encloses ``f(x)`` for every
        ``x`` in each cell.

        Subclasses override :meth:`_bounds`. The default implementation below
        falls back to the Lipschitz estimate, which is always sound but usually
        much looser, so every node that can do better does.
        """
        lo, hi = box
        centres = (lo + hi) / 2.0
        half_diagonal = np.linalg.norm((hi - lo) / 2.0, axis=1)
        margin = half_diagonal * self.lipschitz
        value = self(centres)
        return (value - margin, value + margin)

    def _bounds(self, box: IArray) -> IArray:  # pragma: no cover - overridden
        return self.bounds(box)

    # -- composition sugar ---------------------------------------------
    def __or__(self, other: "SDF") -> "SDF":
        return Union((self, other))

    def __and__(self, other: "SDF") -> "SDF":
        return Intersection((self, other))

    def __sub__(self, other: "SDF") -> "SDF":
        return Difference(self, (other,))


# ----------------------------------------------------------------------
# Primitives
# ----------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class BoxSDF(SDF):
    """An axis-aligned box. The standard exact box distance field."""

    centre: tuple[float, float, float]
    half_extent: tuple[float, float, float]

    def __post_init__(self) -> None:
        for value, axis in zip(self.half_extent, "xyz"):
            if value <= 0.0:
                raise DegenerateGeometryError(
                    "box has a non-positive extent",
                    axis=axis,
                    half_extent=value,
                    hint="a zero-thickness solid has no volume; check the "
                    "parameter that drives this dimension",
                )

    @property
    def lipschitz(self) -> float:
        return 1.0

    @property
    def envelope(self) -> Box:
        return Box.around(self.centre, self.half_extent)

    def _evaluate(self, points: Array) -> Array:
        local = np.abs(points - np.asarray(self.centre)) - np.asarray(self.half_extent)
        if local.ndim == 2 and local.shape[1] == 3:
            # Squared and summed column by column, in the order a row
            # reduction adds them, so the value is the same to the last bit.
            out = np.maximum(local, 0.0)
            outside = np.sqrt(out[:, 0] * out[:, 0] + out[:, 1] * out[:, 1]
                              + out[:, 2] * out[:, 2])
        else:
            outside = np.linalg.norm(np.maximum(local, 0.0), axis=1)
        inside = np.minimum(ib.rowmax(local), 0.0)
        return outside + inside

    def bounds(self, box: IArray) -> IArray:
        # The box field is separable in the three axes, so interval evaluation
        # is essentially exact over an axis-aligned cell. This is what makes a
        # plate's flat faces cost almost no refinement.
        local = ib.isub(
            ib.iabs(ib.isub(box, ib.iconst(np.asarray(self.centre)))),
            ib.iconst(np.asarray(self.half_extent)),
        )
        outside = ib.inorm(ib.imax_zero(local))
        inside = ib.imin_zero(ib.imax_over_axis(local, axis=1))
        return ib.iadd(outside, inside)


@dataclass(frozen=True, slots=True)
class SphereSDF(SDF):
    centre: tuple[float, float, float]
    radius: float

    def __post_init__(self) -> None:
        if self.radius <= 0.0:
            raise DegenerateGeometryError(
                "sphere has a non-positive radius", radius=self.radius
            )

    @property
    def lipschitz(self) -> float:
        return 1.0

    @property
    def envelope(self) -> Box:
        return Box.around(self.centre, (self.radius,) * 3)

    def _evaluate(self, points: Array) -> Array:
        return np.linalg.norm(points - np.asarray(self.centre), axis=1) - self.radius

    def bounds(self, box: IArray) -> IArray:
        relative = ib.isub(box, ib.iconst(np.asarray(self.centre)))
        return ib.iadd_scalar(ib.inorm(relative), -self.radius)


@dataclass(frozen=True, slots=True)
class CylinderSDF(SDF):
    """A right circular cylinder given by its base centre, axis and height."""

    base: tuple[float, float, float]
    axis: tuple[float, float, float]
    radius: float
    height: float

    def __post_init__(self) -> None:
        if self.radius <= 0.0:
            raise DegenerateGeometryError(
                "cylinder has a non-positive radius", radius=self.radius
            )
        if self.height <= 0.0:
            raise DegenerateGeometryError(
                "cylinder has a non-positive height", height=self.height
            )
        norm = math.sqrt(sum(component * component for component in self.axis))
        if norm < EPSILON:
            raise DegenerateGeometryError("cylinder axis has zero length")

    @property
    def unit_axis(self) -> Array:
        axis = np.asarray(self.axis, dtype=float)
        return axis / np.linalg.norm(axis)

    @property
    def lipschitz(self) -> float:
        return 1.0

    @property
    def envelope(self) -> Box:
        axis = self.unit_axis
        base = np.asarray(self.base, dtype=float)
        top = base + axis * self.height
        # The exact envelope of a cylinder: the radial extent along each axis is
        # r * sqrt(1 - a_i^2), the projection of the end disc onto that axis.
        radial = self.radius * np.sqrt(np.maximum(0.0, 1.0 - axis * axis))
        lo = np.minimum(base, top) - radial
        hi = np.maximum(base, top) + radial
        return Box(tuple(lo.tolist()), tuple(hi.tolist()))  # type: ignore[arg-type]

    def _evaluate(self, points: Array) -> Array:
        axis = self.unit_axis
        relative = points - np.asarray(self.base, dtype=float)
        along = relative @ axis
        radial_vector = relative - along[:, None] * axis[None, :]
        radial = np.sqrt(np.einsum("ij,ij->i", radial_vector, radial_vector))

        # Distance in the (radial, axial) half-plane to the rectangle
        # [0, radius] x [0, height]; this is the exact cylinder distance.
        dr = radial - self.radius
        da = np.abs(along - self.height / 2.0) - self.height / 2.0
        outside = np.sqrt(
            np.maximum(dr, 0.0) ** 2 + np.maximum(da, 0.0) ** 2
        )
        inside = np.minimum(np.maximum(dr, da), 0.0)
        return outside + inside

    def bounds(self, box: IArray) -> IArray:
        axis = self.unit_axis
        relative = ib.isub(box, ib.iconst(np.asarray(self.base, dtype=float)))
        along = ib.idot_constant(relative, axis)

        # The radial component. For an axis-aligned cylinder -- which covers
        # essentially every hole and boss in mechanical design -- the axial
        # direction picks out one coordinate exactly, so the remaining two are
        # the radial ones and no tightness is lost. For an oblique axis the
        # subtraction repeats the interval variables and the bound widens, which
        # costs refinement but stays sound.
        radial_lo = []
        radial_hi = []
        for component in range(3):
            projected = ib.iscale(along, float(axis[component]))
            term = ib.isub(ib.icolumn(relative, component), projected)
            radial_lo.append(term[0])
            radial_hi.append(term[1])
        radial_vector = (
            np.stack(radial_lo, axis=1),
            np.stack(radial_hi, axis=1),
        )
        radial = ib.inorm(radial_vector)

        dr = ib.iadd_scalar(radial, -self.radius)
        da = ib.iadd_scalar(
            ib.iabs(ib.iadd_scalar(along, -self.height / 2.0)), -self.height / 2.0
        )
        outside = ib.isqrt(
            ib.iadd(
                ib.isquare(ib.imax_zero(dr)), ib.isquare(ib.imax_zero(da))
            )
        )
        inside = ib.imin_zero(ib.imax(dr, da))
        return ib.iadd(outside, inside)


@dataclass(frozen=True, slots=True)
class ConeSDF(SDF):
    """A cone or a frustum: round, its radius running straight from
    ``bottom_radius`` at ``base`` to ``top_radius`` at ``height`` along
    ``axis``. A top radius of 0 is a pointed cone. The exact distance."""

    base: tuple[float, float, float]
    axis: tuple[float, float, float]
    bottom_radius: float
    top_radius: float
    height: float

    def __post_init__(self) -> None:
        if self.height <= 0.0:
            raise DegenerateGeometryError(
                "cone has a non-positive height", height=self.height)
        if self.bottom_radius < 0.0 or self.top_radius < 0.0 or max(
                self.bottom_radius, self.top_radius) <= 0.0:
            raise DegenerateGeometryError(
                "a cone needs a radius greater than zero at one end at least",
                bottom_radius=self.bottom_radius, top_radius=self.top_radius)
        norm = math.sqrt(sum(c * c for c in self.axis))
        if norm < EPSILON:
            raise DegenerateGeometryError("cone axis has zero length")

    @property
    def unit_axis(self) -> Array:
        axis = np.asarray(self.axis, dtype=float)
        return axis / np.linalg.norm(axis)

    @property
    def lipschitz(self) -> float:
        return 1.0

    @property
    def envelope(self) -> Box:
        axis = self.unit_axis
        base = np.asarray(self.base, dtype=float)
        top = base + axis * self.height
        spread = np.sqrt(np.maximum(0.0, 1.0 - axis * axis))
        ends = np.array([base - spread * self.bottom_radius,
                         base + spread * self.bottom_radius,
                         top - spread * self.top_radius,
                         top + spread * self.top_radius])
        return Box(tuple(ends.min(axis=0).tolist()),  # type: ignore[arg-type]
                   tuple(ends.max(axis=0).tolist()))  # type: ignore[arg-type]

    def _evaluate(self, points: Array) -> Array:
        axis = self.unit_axis
        relative = points - np.asarray(self.base, dtype=float)
        along = relative @ axis
        radial = np.linalg.norm(relative - np.outer(along, axis), axis=1)
        h = self.height / 2.0
        r1, r2 = self.bottom_radius, self.top_radius
        qx, qy = radial, along - h
        # Inigo Quilez's capped cone: the distance to the end discs (ca) and
        # to the slanted side (cb), whichever is nearer, signed inside.
        ca_x = qx - np.minimum(qx, np.where(qy < 0.0, r1, r2))
        ca_y = np.abs(qy) - h
        k2x, k2y = r2 - r1, 2.0 * h
        t = np.clip(((r2 - qx) * k2x + (h - qy) * k2y)
                    / (k2x * k2x + k2y * k2y), 0.0, 1.0)
        cb_x = qx - r2 + k2x * t
        cb_y = qy - h + k2y * t
        sign = np.where((cb_x < 0.0) & (ca_y < 0.0), -1.0, 1.0)
        return sign * np.sqrt(np.minimum(ca_x * ca_x + ca_y * ca_y,
                                         cb_x * cb_x + cb_y * cb_y))


@dataclass(frozen=True, slots=True)
class TorusSDF(SDF):
    """A ring: a circle of radius ``tube_radius`` swept round ``axis`` at
    ``radius`` from ``centre``. The exact distance."""

    centre: tuple[float, float, float]
    axis: tuple[float, float, float]
    radius: float
    tube_radius: float

    def __post_init__(self) -> None:
        if self.tube_radius <= 0.0 or self.radius <= 0.0:
            raise DegenerateGeometryError(
                "a ring needs a radius and a tube radius greater than zero",
                radius=self.radius, tube_radius=self.tube_radius)
        norm = math.sqrt(sum(c * c for c in self.axis))
        if norm < EPSILON:
            raise DegenerateGeometryError("ring axis has zero length")

    @property
    def unit_axis(self) -> Array:
        axis = np.asarray(self.axis, dtype=float)
        return axis / np.linalg.norm(axis)

    @property
    def lipschitz(self) -> float:
        return 1.0

    @property
    def envelope(self) -> Box:
        axis = self.unit_axis
        reach = (self.radius + self.tube_radius) * np.sqrt(
            np.maximum(0.0, 1.0 - axis * axis)) + self.tube_radius * np.abs(
            axis)
        return Box.around(self.centre, tuple(reach.tolist()))

    def _evaluate(self, points: Array) -> Array:
        axis = self.unit_axis
        relative = points - np.asarray(self.centre, dtype=float)
        along = relative @ axis
        radial = np.linalg.norm(relative - np.outer(along, axis), axis=1)
        return np.hypot(radial - self.radius, along) - self.tube_radius


@dataclass(frozen=True, slots=True)
class HalfSpaceSDF(SDF):
    """Everything on the negative side of a plane."""

    point: tuple[float, float, float]
    normal: tuple[float, float, float]

    @property
    def unit_normal(self) -> Array:
        normal = np.asarray(self.normal, dtype=float)
        length = np.linalg.norm(normal)
        if length < EPSILON:
            raise DegenerateGeometryError("half-space normal has zero length")
        return normal / length

    @property
    def lipschitz(self) -> float:
        return 1.0

    @property
    def envelope(self) -> Box:
        return Box.universe()

    def _evaluate(self, points: Array) -> Array:
        normal = self.unit_normal
        return (points - np.asarray(self.point, dtype=float)) @ normal

    def bounds(self, box: IArray) -> IArray:
        relative = ib.isub(box, ib.iconst(np.asarray(self.point, dtype=float)))
        return ib.idot_constant(relative, self.unit_normal)


@dataclass(frozen=True, slots=True)
class ExtrusionSDF(SDF):
    """A 2D profile swept normal to its plane.

    ``profile`` returns the signed distance of ``(u, v)`` points in the plane's
    own coordinates; the class handles the third dimension and the frame.
    """

    profile: "Profile2D"
    origin: tuple[float, float, float]
    u_axis: tuple[float, float, float]
    v_axis: tuple[float, float, float]
    w_axis: tuple[float, float, float]
    distance: float
    offset: float = 0.0
    #: The edges round each end face: rounded to a radius, or chamfered.
    start_round: float = 0.0
    end_round: float = 0.0
    start_chamfer: float = 0.0
    end_chamfer: float = 0.0
    #: Draft: how much the profile shrinks per unit of distance, tan of the
    #: draft angle -- positive tapers in towards the far end.
    taper: float = 0.0

    def __post_init__(self) -> None:
        if self.distance <= 0.0:
            raise DegenerateGeometryError(
                "extrusion distance must be positive", distance=self.distance
            )
        for name in ("start_round", "end_round", "start_chamfer", "end_chamfer"):
            value = getattr(self, name)
            if value < 0.0 or value > self.distance / 2.0 + 1e-9 and (
                    "round" in name):
                raise DegenerateGeometryError(
                    "an end edge's radius must be positive and at most half "
                    "the extrusion's length",
                    **{name: value, "distance": self.distance})
            if value < 0.0 or value > self.distance + 1e-9:
                raise DegenerateGeometryError(
                    "an end edge's chamfer must be positive and at most the "
                    "extrusion's length", **{name: value,
                                             "distance": self.distance})
        if abs(self.taper) >= 10.0:
            raise DegenerateGeometryError(
                "a draft is an angle well under 90 degrees", taper=self.taper)

    @property
    def lipschitz(self) -> float:
        if self.taper:
            # The drafted field combines the slanted-side distance with the
            # axial one as if they were orthogonal, which beyond the rim
            # overestimates the distance and steepens the field: measured
            # peak gradient sqrt(1 + sin(draft)) -- 1.083 at 10 degrees,
            # 1.225 at 30 -- against a declared 1. With `taper` the tangent
            # of the draft, sin(draft) is taper / hypot(1, taper). Declared
            # honestly, the Lipschitz fallback in `bounds` is sound again:
            # an `offset` or `shell` of a drafted boss had 435 cells decided
            # inside that held empty space.
            taper = abs(self.taper)
            return math.sqrt(1.0 + taper / math.hypot(1.0, taper))
        return 1.0

    @property
    def envelope(self) -> Box:
        u_lo, u_hi, v_lo, v_hi = self.profile.bounds()
        # A draft outward grows the profile towards the far end.
        grow = max(0.0, -self.taper * self.distance)
        u_lo, u_hi, v_lo, v_hi = u_lo - grow, u_hi + grow, v_lo - grow, v_hi + grow
        origin = np.asarray(self.origin, dtype=float)
        u = np.asarray(self.u_axis, dtype=float)
        v = np.asarray(self.v_axis, dtype=float)
        w = np.asarray(self.w_axis, dtype=float)
        corners = [
            origin + u * cu + v * cv + w * cw
            for cu in (u_lo, u_hi)
            for cv in (v_lo, v_hi)
            for cw in (self.offset, self.offset + self.distance)
        ]
        stacked = np.array(corners)
        return Box(
            tuple(stacked.min(axis=0).tolist()),  # type: ignore[arg-type]
            tuple(stacked.max(axis=0).tolist()),  # type: ignore[arg-type]
        )

    def _evaluate(self, points: Array) -> Array:
        relative = points - np.asarray(self.origin, dtype=float)
        u = relative @ np.asarray(self.u_axis, dtype=float)
        v = relative @ np.asarray(self.v_axis, dtype=float)
        w = relative @ np.asarray(self.w_axis, dtype=float)
        planar = self.profile.distance(u, v)
        middle = self.offset + self.distance / 2.0
        if self.taper:
            # The side leans in by `taper` per unit along; scaled by the
            # cosine so the field stays a distance across the sloping side.
            planar = (planar + (w - self.offset) * self.taper) / math.sqrt(
                1.0 + self.taper * self.taper)
        axial = np.abs(w - middle) - self.distance / 2.0
        if not (self.start_round or self.end_round or self.start_chamfer
                or self.end_chamfer):
            outside = np.sqrt(
                np.maximum(planar, 0.0) ** 2 + np.maximum(axial, 0.0) ** 2
            )
            inside = np.minimum(np.maximum(planar, axial), 0.0)
            return outside + inside
        far = w > middle
        radius = np.where(far, self.end_round, self.start_round)
        q1, q2 = planar + radius, axial + radius
        outside = np.sqrt(np.maximum(q1, 0.0) ** 2 + np.maximum(q2, 0.0) ** 2)
        inside = np.minimum(np.maximum(q1, q2), 0.0)
        result = outside + inside - radius
        chamfer = np.where(far, self.end_chamfer, self.start_chamfer)
        cut = np.where(chamfer > 0.0,
                       (planar + axial + chamfer) / math.sqrt(2.0), -np.inf)
        return np.maximum(result, cut)

    def bounds(self, box: IArray) -> IArray:
        # Every form of the field above -- sharp, rounded, chamfered -- is at
        # least max(planar, axial): rounding or chamfering an edge only ever
        # takes material away. The axial term is linear in the point, so its
        # range over a cell is exact; the planar term is bounded by the
        # profile's own interval bound where it has one, else by its
        # Lipschitz constant over the cell. Without this an extrusion was
        # bounded by its Lipschitz constant alone, and a slab 0.05 mm above a
        # plate's face could not be proved empty with cells under 0.05 mm.
        value_lo, value_hi = SDF.bounds(self, box)
        if self.taper:
            return value_lo, value_hi
        origin = np.asarray(self.origin, dtype=float)
        relative = ib.isub(box, ib.iconst(origin))
        w = ib.idot_constant(relative, np.asarray(self.w_axis, dtype=float))
        middle = self.offset + self.distance / 2.0
        axial_lo = ib.iabs(ib.iadd_scalar(w, -middle))[0] - self.distance / 2.0
        u = ib.idot_constant(relative, np.asarray(self.u_axis, dtype=float))
        v = ib.idot_constant(relative, np.asarray(self.v_axis, dtype=float))
        lower_of = getattr(self.profile, "lower_bound", None)
        if lower_of is not None:
            planar_lo = lower_of(u, v)
        else:
            cu, cv = (u[0] + u[1]) / 2.0, (v[0] + v[1]) / 2.0
            reach = np.hypot((u[1] - u[0]) / 2.0, (v[1] - v[0]) / 2.0)
            planar_lo = self.profile.distance(cu, cv) - reach
        return np.maximum(value_lo, np.maximum(axial_lo, planar_lo)), value_hi


# ----------------------------------------------------------------------
# 2D profiles
# ----------------------------------------------------------------------
class Profile2D:
    """A closed 2D region expressed as a signed distance in the sketch plane."""

    __slots__ = ()

    def distance(self, u: Array, v: Array) -> Array:  # pragma: no cover - abstract
        raise NotImplementedError

    def bounds(self) -> tuple[float, float, float, float]:  # pragma: no cover
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class RectangleProfile(Profile2D):
    centre: tuple[float, float]
    half_width: float
    half_height: float
    corner_radius: float = 0.0
    corner_chamfer: float = 0.0

    def __post_init__(self) -> None:
        if self.half_width <= 0 or self.half_height <= 0:
            raise DegenerateGeometryError(
                "rectangle profile has a non-positive extent",
                width=2 * self.half_width,
                height=2 * self.half_height,
            )
        limit = min(self.half_width, self.half_height)
        if self.corner_chamfer < 0.0 or self.corner_chamfer > 2 * limit + 1e-9:
            raise DegenerateGeometryError(
                "corner chamfer must be positive and under the shorter side",
                corner_chamfer=self.corner_chamfer, maximum=2 * limit)
        if self.corner_radius > limit + 1e-9:
            raise DegenerateGeometryError(
                "corner radius exceeds half the shorter side of the rectangle",
                corner_radius=self.corner_radius,
                maximum=limit,
                hint="the rounded corners would overlap; reduce the radius or "
                "enlarge the profile",
            )

    def lower_bound(self, u: IArray, v: IArray) -> Array:
        """A floor under the distance over a range of points: the rounded
        or chamfered rectangle lies inside the sharp one, so it is at least
        that one's distance, which separates by axis."""
        du = ib.iabs(ib.iadd_scalar(u, -self.centre[0]))[0] - self.half_width
        dv = ib.iabs(ib.iadd_scalar(v, -self.centre[1]))[0] - self.half_height
        return np.maximum(du, dv)

    def distance(self, u: Array, v: Array) -> Array:
        au = np.abs(u - self.centre[0])
        av = np.abs(v - self.centre[1])
        du = au - (self.half_width - self.corner_radius)
        dv = av - (self.half_height - self.corner_radius)
        outside = np.sqrt(np.maximum(du, 0.0) ** 2 + np.maximum(dv, 0.0) ** 2)
        inside = np.minimum(np.maximum(du, dv), 0.0)
        result = outside + inside - self.corner_radius
        if self.corner_chamfer > 0.0:
            # Each corner cut by the line through the points `corner_chamfer`
            # back from it along both sides.
            cut = (au + av - (self.half_width + self.half_height
                              - self.corner_chamfer)) / math.sqrt(2.0)
            result = np.maximum(result, cut)
        return result

    def bounds(self) -> tuple[float, float, float, float]:
        return (
            self.centre[0] - self.half_width,
            self.centre[0] + self.half_width,
            self.centre[1] - self.half_height,
            self.centre[1] + self.half_height,
        )


@dataclass(frozen=True, slots=True)
class CircleProfile(Profile2D):
    centre: tuple[float, float]
    radius: float

    def __post_init__(self) -> None:
        if self.radius <= 0:
            raise DegenerateGeometryError(
                "circle profile has a non-positive radius", radius=self.radius
            )

    def distance(self, u: Array, v: Array) -> Array:
        return (
            np.sqrt((u - self.centre[0]) ** 2 + (v - self.centre[1]) ** 2)
            - self.radius
        )

    def bounds(self) -> tuple[float, float, float, float]:
        return (
            self.centre[0] - self.radius,
            self.centre[0] + self.radius,
            self.centre[1] - self.radius,
            self.centre[1] + self.radius,
        )


@dataclass(frozen=True, slots=True)
class SlotProfile(Profile2D):
    """An obround: a rectangle capped with semicircles on the short ends."""

    centre: tuple[float, float]
    length: float
    width: float
    rotation: float = 0.0

    def __post_init__(self) -> None:
        if self.width <= 0 or self.length < self.width:
            raise DegenerateGeometryError(
                "slot length must be at least its width, both positive",
                length=self.length,
                width=self.width,
            )

    def distance(self, u: Array, v: Array) -> Array:
        cos_r, sin_r = math.cos(-self.rotation), math.sin(-self.rotation)
        du = u - self.centre[0]
        dv = v - self.centre[1]
        lu = du * cos_r - dv * sin_r
        lv = du * sin_r + dv * cos_r
        radius = self.width / 2.0
        half_span = max(0.0, self.length / 2.0 - radius)
        clamped = np.clip(lu, -half_span, half_span)
        return np.sqrt((lu - clamped) ** 2 + lv**2) - radius

    def bounds(self) -> tuple[float, float, float, float]:
        half = max(self.length, self.width) / 2.0
        return (
            self.centre[0] - half,
            self.centre[0] + half,
            self.centre[1] - half,
            self.centre[1] + half,
        )


@dataclass(frozen=True, slots=True)
class PolygonProfile(Profile2D):
    """A regular polygon, circumscribed about the given diameter."""

    centre: tuple[float, float]
    circumradius: float
    sides: int
    rotation: float = 0.0
    #: Rounds each corner to this radius, the sides staying where they are
    #: -- "rounded triangular cutouts".
    corner_radius: float = 0.0

    def __post_init__(self) -> None:
        if self.sides < 3:
            raise DegenerateGeometryError(
                "a polygon needs at least three sides", sides=self.sides
            )
        if self.circumradius <= 0:
            raise DegenerateGeometryError(
                "polygon has a non-positive circumradius",
                circumradius=self.circumradius,
            )
        apothem = self.circumradius * math.cos(math.pi / self.sides)
        if self.corner_radius < 0 or self.corner_radius >= apothem:
            raise DegenerateGeometryError(
                "a polygon's corner radius must be under its inradius "
                "(half the distance across its flats, less for a triangle)",
                corner_radius=self.corner_radius, inradius=apothem,
            )

    def distance(self, u: Array, v: Array) -> Array:
        du = u - self.centre[0]
        dv = v - self.centre[1]
        apothem = (self.circumradius * math.cos(math.pi / self.sides)
                   - self.corner_radius)
        # Inside: the half-planes, exact for a convex polygon. Outside, the
        # distance to the nearest side, so that offsetting it rounds the
        # corners rather than keeping them sharp.
        result = np.full(du.shape, -np.inf)
        for index in range(self.sides):
            angle = self.rotation + 2.0 * math.pi * index / self.sides
            nx, ny = math.cos(angle), math.sin(angle)
            result = np.maximum(result, du * nx + dv * ny - apothem)
        if self.corner_radius <= 0.0:
            return result
        reach = apothem / math.cos(math.pi / self.sides)
        corners = [
            (reach * math.cos(self.rotation + (2.0 * i + 1.0) * math.pi
                              / self.sides),
             reach * math.sin(self.rotation + (2.0 * i + 1.0) * math.pi
                              / self.sides))
            for i in range(self.sides)]
        nearest = np.full(du.shape, np.inf)
        for i in range(self.sides):
            (ax, ay), (bx, by) = corners[i - 1], corners[i]
            ex, ey = bx - ax, by - ay
            t = np.clip(((du - ax) * ex + (dv - ay) * ey) / (ex * ex + ey * ey),
                        0.0, 1.0)
            nearest = np.minimum(nearest, np.hypot(du - ax - t * ex,
                                                   dv - ay - t * ey))
        exact = np.where(result > 0.0, nearest, result)
        return exact - self.corner_radius

    def bounds(self) -> tuple[float, float, float, float]:
        r = self.circumradius
        return (
            self.centre[0] - r,
            self.centre[0] + r,
            self.centre[1] - r,
            self.centre[1] + r,
        )


@dataclass(frozen=True, slots=True)
class SketchProfile(Profile2D):
    """Any closed outline: a polygon through the given corners, in order.

    Corners that should be round are rounded before the profile is made (see
    :func:`sketch_outline`), so this is always straight segments -- which is
    what lets the distance be exact for any outline, convex or not.
    """

    vertices: tuple[tuple[float, float], ...]

    def __post_init__(self) -> None:
        if len(self.vertices) < 3:
            raise DegenerateGeometryError(
                "an outline needs at least three corners",
                corners=len(self.vertices))
        area = 0.0
        for (u0, v0), (u1, v1) in zip(self.vertices,
                                      self.vertices[1:] + self.vertices[:1]):
            area += u0 * v1 - u1 * v0
        if abs(area) / 2.0 < 1e-9:
            raise DegenerateGeometryError(
                "the outline encloses no area -- its corners lie on one line "
                "or retrace themselves", corners=len(self.vertices))

    def distance(self, u: Array, v: Array) -> Array:
        # The exact signed distance to a polygon: the nearest edge for the
        # size, the crossing count for the sign. Every edge at once, a block
        # of points at a time.
        u = np.asarray(u, dtype=float)
        v = np.asarray(v, dtype=float)
        shape = np.broadcast(u, v).shape
        u = np.broadcast_to(u, shape).ravel()
        v = np.broadcast_to(v, shape).ravel()
        a = np.asarray(self.vertices, dtype=float)
        b = np.roll(a, -1, axis=0)
        ex, ey = (b - a)[:, 0], (b - a)[:, 1]
        length2 = np.maximum(ex * ex + ey * ey, 1e-300)
        out = np.empty(u.shape[0])
        block = max(1, 400_000 // max(len(a), 1))
        for lo in range(0, u.shape[0], block):
            pu = u[lo:lo + block, None]
            pv = v[lo:lo + block, None]
            wx, wy = pu - a[None, :, 0], pv - a[None, :, 1]
            t = np.clip((wx * ex + wy * ey) / length2, 0.0, 1.0)
            dx, dy = wx - ex * t, wy - ey * t
            squared = np.min(dx * dx + dy * dy, axis=1)
            c1 = pv >= a[None, :, 1]
            c2 = pv < b[None, :, 1]
            c3 = ex * wy > ey * wx
            flips = np.count_nonzero((c1 & c2 & c3) | (~c1 & ~c2 & ~c3),
                                     axis=1)
            sign = np.where(flips % 2 == 1, -1.0, 1.0)
            out[lo:lo + block] = sign * np.sqrt(squared)
        return out.reshape(shape)

    def bounds(self) -> tuple[float, float, float, float]:
        vertices = np.asarray(self.vertices, dtype=float)
        return (float(vertices[:, 0].min()), float(vertices[:, 0].max()),
                float(vertices[:, 1].min()), float(vertices[:, 1].max()))


def sketch_outline(
    points: Sequence[Sequence[float]], *, corner_radius: float = 0.0,
    smooth: bool = False, steps: int = 10,
) -> tuple[tuple[float, float], ...]:
    """The polygon a sketch describes: its points in order, each corner
    rounded to its own radius (a third entry) or the sketch's, or the whole
    outline passed smoothly through its points (a closed Catmull-Rom curve).

    A rounded corner is an exact circular arc tangent to both sides, cut back
    along each side by r / tan(half the corner's angle) -- never more than
    half of either side, so neighbouring roundings cannot cross.
    """
    corners = [(float(p[0]), float(p[1])) for p in points]
    radii = [float(p[2]) if len(p) > 2 else corner_radius for p in points]
    # A closing point written twice is one corner.
    if len(corners) > 3 and math.dist(corners[0], corners[-1]) < 1e-9:
        corners, radii = corners[:-1], radii[:-1]
    n = len(corners)
    if n < 3:
        raise DegenerateGeometryError("an outline needs at least three corners",
                                      corners=n)
    if smooth:
        out: list[tuple[float, float]] = []
        for i in range(n):
            p0, p1, p2, p3 = (np.asarray(corners[(i + k) % n]) for k in
                              (-1, 0, 1, 2))
            for j in range(steps):
                t = j / steps
                t2, t3 = t * t, t * t * t
                point = 0.5 * ((2 * p1) + (-p0 + p2) * t
                               + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2
                               + (-p0 + 3 * p1 - 3 * p2 + p3) * t3)
                out.append((float(point[0]), float(point[1])))
        return tuple(out)
    out = []
    for i in range(n):
        here = np.asarray(corners[i])
        before = np.asarray(corners[i - 1])
        after = np.asarray(corners[(i + 1) % n])
        radius = radii[i]
        a, b = before - here, after - here
        la, lb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
        if radius <= 0.0 or la < 1e-12 or lb < 1e-12:
            out.append((float(here[0]), float(here[1])))
            continue
        a, b = a / la, b / lb
        cosine = float(np.clip(np.dot(a, b), -1.0, 1.0))
        angle = math.acos(cosine)
        if angle < 1e-6 or angle > math.pi - 1e-6:
            out.append((float(here[0]), float(here[1])))
            continue
        cut = radius / math.tan(angle / 2.0)
        cut = min(cut, la / 2.0, lb / 2.0)
        radius = cut * math.tan(angle / 2.0)
        start, end = here + a * cut, here + b * cut
        bisector = (a + b) / float(np.linalg.norm(a + b))
        centre = here + bisector * (radius / math.sin(angle / 2.0))
        a0 = math.atan2(start[1] - centre[1], start[0] - centre[0])
        a1 = math.atan2(end[1] - centre[1], end[0] - centre[0])
        sweep = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
        for j in range(steps + 1):
            if j == 0:
                # The arc's ends are the tangent points on the two sides,
                # exactly, rather than cos/sin of an atan2 of them: that
                # round trip put the ends of a 20 mm square's corners at
                # -8.9e-16, so its bounds were not the 0 and 20 it was
                # drawn to and its outline did not meet its own sides.
                point = start
            elif j == steps:
                point = end
            else:
                t = a0 + sweep * j / steps
                point = centre + radius * np.array([math.cos(t), math.sin(t)])
            out.append((float(point[0]), float(point[1])))
    return tuple(out)


def gear_outline(
    module: float, teeth: int, pressure_angle: float = math.radians(20.0), *,
    centre: tuple[float, float] = (0.0, 0.0), rotation: float = 0.0,
    steps: int = 8,
) -> tuple[tuple[float, float], ...]:
    """A spur gear's outline: involute flanks from the base (or root)
    circle to the tip circle, standard proportions -- addendum one module,
    dedendum 1.25 -- with the tooth half a pitch thick on the pitch circle."""
    if teeth < 6 or module <= 0.0:
        raise DegenerateGeometryError(
            "a spur gear needs at least 6 teeth and a positive module",
            teeth=teeth, module=module)
    pitch = module * teeth / 2.0
    base = pitch * math.cos(pressure_angle)
    tip = pitch + module
    root = max(pitch - 1.25 * module, 0.2 * pitch)

    def involute(phi: float) -> float:
        return math.tan(phi) - phi

    half_at_pitch = math.pi / (2.0 * teeth)
    start = max(base, root)

    def half_angle(r: float) -> float:
        phi = math.acos(min(1.0, base / r))
        return half_at_pitch + involute(pressure_angle) - involute(phi)

    radii = [start + (tip - start) * k / steps for k in range(steps + 1)]
    out: list[tuple[float, float]] = []

    def at(r: float, angle: float) -> tuple[float, float]:
        angle += rotation
        return (centre[0] + r * math.cos(angle), centre[1] + r * math.sin(angle))

    pitch_angle = 2.0 * math.pi / teeth
    for k in range(teeth):
        c = k * pitch_angle
        if root < start:
            out.append(at(root, c - half_angle(start)))
        for r in radii:
            out.append(at(r, c - max(half_angle(r), 0.0)))
        for r in reversed(radii):
            out.append(at(r, c + max(half_angle(r), 0.0)))
        if root < start:
            out.append(at(root, c + half_angle(start)))
    return tuple(out)


@dataclass(frozen=True, slots=True)
class GearProfile(Profile2D):
    """A spur gear's outline, its distance found from one tooth and its two
    neighbours: every tooth is the same, so a point is turned into the
    nearest tooth's place first. The outline is star-shaped about its
    centre, so inside is nearer the centre than the outline at that angle."""

    module: float
    teeth: int
    pressure_angle: float = math.radians(20.0)
    centre: tuple[float, float] = (0.0, 0.0)
    rotation: float = 0.0

    def __post_init__(self) -> None:
        gear_outline(self.module, self.teeth, self.pressure_angle)

    def _window(self) -> Array:
        outline = np.asarray(gear_outline(self.module, self.teeth,
                                          self.pressure_angle), dtype=float)
        per = len(outline) // self.teeth
        order = [(i % len(outline)) for i in range(-per, 2 * per + 1)]
        return outline[order]

    def distance(self, u: Array, v: Array) -> Array:
        u = np.asarray(u, dtype=float)
        v = np.asarray(v, dtype=float)
        shape = np.broadcast(u, v).shape
        du = np.broadcast_to(u, shape).ravel() - self.centre[0]
        dv = np.broadcast_to(v, shape).ravel() - self.centre[1]
        period = 2.0 * math.pi / self.teeth
        theta = np.arctan2(dv, du) - self.rotation
        turn = -np.round(theta / period) * period - self.rotation
        c, s_ = np.cos(turn), np.sin(turn)
        qu, qv = du * c - dv * s_, du * s_ + dv * c
        chain = self._window()
        a, b = chain[:-1], chain[1:]
        ex, ey = (b - a)[:, 0], (b - a)[:, 1]
        length2 = np.maximum(ex * ex + ey * ey, 1e-300)
        wx, wy = qu[:, None] - a[None, :, 0], qv[:, None] - a[None, :, 1]
        t = np.clip((wx * ex + wy * ey) / length2, 0.0, 1.0)
        dx, dy = wx - ex * t, wy - ey * t
        unsigned = np.sqrt(np.min(dx * dx + dy * dy, axis=1))
        # Inside: nearer the centre than where the ray from the centre
        # through the point crosses the outline.
        angle = np.arctan2(qv, qu)
        a0 = np.arctan2(a[:, 1], a[:, 0])
        a1 = np.arctan2(b[:, 1], b[:, 0])
        lo_, hi_ = np.minimum(a0, a1), np.maximum(a0, a1)
        spans = (angle[:, None] >= lo_[None]) & (angle[:, None] <= hi_[None])
        cu, cv = np.cos(angle)[:, None], np.sin(angle)[:, None]
        denominator = cu * ey[None] - cv * ex[None]
        safe = np.where(np.abs(denominator) < 1e-15, 1e-15, denominator)
        cross = (a[None, :, 0] * ey[None] - a[None, :, 1] * ex[None]) / safe
        reach = np.where(spans, cross, np.inf).min(axis=1)
        reach = np.where(np.isfinite(reach), reach, 0.0)
        radius = np.hypot(qu, qv)
        sign = np.where(radius < reach, -1.0, 1.0)
        return (sign * unsigned).reshape(shape)

    def bounds(self) -> tuple[float, float, float, float]:
        tip = self.module * self.teeth / 2.0 + self.module
        return (self.centre[0] - tip, self.centre[0] + tip,
                self.centre[1] - tip, self.centre[1] + tip)


def _segment_frames(points: Array) -> list[tuple[Array, Array, Array, Array, float]]:
    """Each straight run of a path with a frame carried along it without
    twisting (rotation-minimising, by double reflection): start, tangent,
    normal, binormal, length."""
    frames = []
    tangents = []
    for a, b in zip(points[:-1], points[1:]):
        d = b - a
        length = float(np.linalg.norm(d))
        if length < 1e-9:
            continue
        tangents.append((a, d / length, length))
    if not tangents:
        raise DegenerateGeometryError("a path needs two different points")
    t0 = tangents[0][1]
    helper = np.array([0.0, 0.0, 1.0]) if abs(t0[2]) < 0.9 else np.array(
        [1.0, 0.0, 0.0])
    normal = np.cross(helper, t0)
    normal /= np.linalg.norm(normal)
    previous_t = t0
    for start, t, length in tangents:
        v1 = t - previous_t
        c1 = float(v1 @ v1)
        if c1 > 1e-18:
            normal = normal - (2.0 / c1) * float(v1 @ normal) * v1
        normal = normal - float(normal @ t) * t
        normal /= np.linalg.norm(normal)
        binormal = np.cross(t, normal)
        frames.append((start, t, normal, binormal, length))
        previous_t = t
    return frames


def round_the_path(points: Sequence[Sequence[float]], radius: float,
                   steps: int = 12) -> tuple[tuple[float, float, float], ...]:
    """A path's corners bent round to a radius: each corner replaced by an
    arc tangent to both runs, as a tube or a wire is bent."""
    pts = [np.asarray(p, dtype=float) for p in points]
    if radius <= 0.0 or len(pts) < 3:
        return tuple(tuple(float(x) for x in p) for p in pts)  # type: ignore
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        here, before, after = pts[i], pts[i - 1], pts[i + 1]
        a, b = before - here, after - here
        la, lb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
        if la < 1e-9 or lb < 1e-9:
            continue
        a, b = a / la, b / lb
        angle = math.acos(float(np.clip(a @ b, -1.0, 1.0)))
        if angle < 1e-6 or angle > math.pi - 1e-6:
            out.append(here)
            continue
        cut = min(radius / math.tan(angle / 2.0), la / 2.0, lb / 2.0)
        r = cut * math.tan(angle / 2.0)
        start, end = here + a * cut, here + b * cut
        bisector = (a + b) / float(np.linalg.norm(a + b))
        centre = here + bisector * (r / math.sin(angle / 2.0))
        u = (start - centre) / r
        w = end - centre
        v = w - (w @ u) * u
        v /= float(np.linalg.norm(v))
        total = math.acos(float(np.clip(((end - centre) / r) @ u, -1.0, 1.0)))
        for j in range(steps + 1):
            t = total * j / steps
            out.append(centre + r * (math.cos(t) * u + math.sin(t) * v))
    out.append(pts[-1])
    return tuple(tuple(float(x) for x in p) for p in out)  # type: ignore


def helix_points(radius: float, pitch: float, turns: float, *,
                 origin: Sequence[float] = (0.0, 0.0, 0.0),
                 axis: Sequence[float] = (0.0, 0.0, 1.0),
                 per_turn: int = 36) -> tuple[tuple[float, float, float], ...]:
    """Points along a helix -- a spring, a coil, a thread's path."""
    if radius <= 0.0 or turns <= 0.0:
        raise DegenerateGeometryError("a helix needs a radius and some turns",
                                      radius=radius, turns=turns)
    z = np.asarray(axis, dtype=float)
    z /= float(np.linalg.norm(z))
    helper = np.array([1.0, 0.0, 0.0]) if abs(z[0]) < 0.9 else np.array(
        [0.0, 1.0, 0.0])
    x = np.cross(z, helper)
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    o = np.asarray(origin, dtype=float)
    count = max(8, int(math.ceil(turns * per_turn)))
    out = []
    for k in range(count + 1):
        t = 2.0 * math.pi * turns * k / count
        p = o + radius * (math.cos(t) * x + math.sin(t) * y) + z * (
            pitch * turns * k / count)
        out.append(tuple(float(c) for c in p))
    return tuple(out)  # type: ignore


@dataclass(frozen=True, slots=True)
class SweepSDF(SDF):
    """A profile carried along a path, square to it at every point.

    Each straight run of the path is the profile extruded along it; runs are
    joined by overlapping each a little past its ends, enough to close the
    outside of a turn of up to the path's sharpest bend -- which, for a path
    bent round to a radius, is a few degrees per run.
    """

    profile: "Profile2D"
    path: tuple[tuple[float, float, float], ...]
    twist_free: bool = True

    def __post_init__(self) -> None:
        if len(self.path) < 2:
            raise DegenerateGeometryError("a sweep needs a path of two points")

    def _runs(self):
        points = np.asarray(self.path, dtype=float)
        frames = _segment_frames(points)
        u_lo, u_hi, v_lo, v_hi = self.profile.bounds()
        reach = max(abs(u_lo), abs(u_hi), abs(v_lo), abs(v_hi))
        runs = []
        for index, (start, t, n, b, length) in enumerate(frames):
            pad_lo = pad_hi = 0.0
            if index > 0:
                turn = math.acos(float(np.clip(t @ frames[index - 1][1], -1, 1)))
                pad_lo = reach * math.tan(min(turn, 1.4) / 2.0)
            if index + 1 < len(frames):
                turn = math.acos(float(np.clip(t @ frames[index + 1][1], -1, 1)))
                pad_hi = reach * math.tan(min(turn, 1.4) / 2.0)
            runs.append((start, t, n, b, length, pad_lo, pad_hi))
        return runs, reach

    @property
    def envelope(self) -> Box:
        # The union of each run's own box: the profile's bounds carried
        # along the run's frame over the padded length it is built with.
        # Exact for the field as built. It used to pad the path's bounding
        # box by 1.5 times the profile's largest half-extent, which a square
        # profile's corner (hypot of both) on a short, turned path reached
        # 1.13 mm past -- material outside the envelope the octree is seeded
        # from, which the octree's own padding was all that caught.
        runs, _ = self._runs()
        u_lo, u_hi, v_lo, v_hi = self.profile.bounds()
        corners = []
        for start, t, n, b, length, pad_lo, pad_hi in runs:
            for cu in (u_lo, u_hi):
                for cv in (v_lo, v_hi):
                    for cw in (-pad_lo, length + pad_hi):
                        corners.append(start + n * cu + b * cv + t * cw)
        stacked = np.asarray(corners, dtype=float)
        return Box(tuple(stacked.min(axis=0).tolist()),  # type: ignore
                   tuple(stacked.max(axis=0).tolist()))  # type: ignore

    def _evaluate(self, points: Array) -> Array:
        runs, _ = self._runs()
        result = np.full(points.shape[0], np.inf)
        for start, t, n, b, length, pad_lo, pad_hi in runs:
            rel = points - start
            w = rel @ t
            planar = self.profile.distance(rel @ n, rel @ b)
            lo, hi = -pad_lo, length + pad_hi
            axial = np.abs(w - (lo + hi) / 2.0) - (hi - lo) / 2.0
            outside = np.sqrt(np.maximum(planar, 0.0) ** 2
                              + np.maximum(axial, 0.0) ** 2)
            inside = np.minimum(np.maximum(planar, axial), 0.0)
            result = np.minimum(result, outside + inside)
        return result


@dataclass(frozen=True, slots=True)
class TubeSDF(SDF):
    """A round bar or tube along a path: the set of points within `radius`
    of the path, its two ends cut flat and square, hollow to `inner_radius`
    when that is given. Exact for a solid bar."""

    path: tuple[tuple[float, float, float], ...]
    radius: float
    inner_radius: float = 0.0
    closed: bool = False

    def __post_init__(self) -> None:
        if self.radius <= 0.0:
            raise DegenerateGeometryError("a tube needs a positive diameter",
                                          radius=self.radius)
        if not 0.0 <= self.inner_radius < self.radius:
            raise DegenerateGeometryError(
                "a tube's bore must be smaller than the tube",
                inner=self.inner_radius, outer=self.radius)
        if len(self.path) < 2:
            raise DegenerateGeometryError("a tube needs a path of two points")

    @property
    def envelope(self) -> Box:
        points = np.asarray(self.path, dtype=float)
        return Box(tuple((points.min(axis=0) - self.radius).tolist()),  # type: ignore
                   tuple((points.max(axis=0) + self.radius).tolist()))  # type: ignore

    def _chain(self, points: Array, radius: float, extend: float) -> Array:
        """Union of a capped cylinder per run and a ball at every inner
        joint: a bar bent along the path, square at its two ends."""
        path = np.asarray(self.path, dtype=float).copy()
        if extend and not self.closed:
            t0 = path[1] - path[0]
            t1 = path[-1] - path[-2]
            path[0] = path[0] - t0 / np.linalg.norm(t0) * extend
            path[-1] = path[-1] + t1 / np.linalg.norm(t1) * extend
        starts, ends = path[:-1], path[1:]
        e = ends - starts
        lengths = np.linalg.norm(e, axis=1)
        keep = lengths > 1e-12
        starts, ends, e, lengths = starts[keep], ends[keep], e[keep], lengths[keep]
        tangents = e / lengths[:, None]
        # Runs in groups, each with a ball round it: a point's distance is
        # only worked out against the groups that could hold its nearest
        # run -- a coil of two hundred runs is a handful for each point.
        size = 8
        groups = []
        for lo in range(0, len(starts), size):
            ends_here = np.concatenate([starts[lo:lo + size], ends[lo:lo + size]])
            centre = ends_here.mean(axis=0)
            reach = float(np.max(np.linalg.norm(ends_here - centre, axis=1)))
            groups.append((lo, min(lo + size, len(starts)), centre, reach))
        centres = np.array([g[2] for g in groups])
        reaches = np.array([g[3] for g in groups])
        gap = np.linalg.norm(points[:, None, :] - centres[None, :, :], axis=2)
        lower = gap - reaches[None, :] - radius
        result = np.min(gap + reaches[None, :], axis=1) - radius

        def exactly(which: Array, index: int) -> Array:
            lo, hi = groups[index][0], groups[index][1]
            p = points[which]
            w = p[:, None, :] - starts[None, lo:hi, :]
            h = np.einsum("pse,se->ps", w, tangents[lo:hi])
            r = np.sqrt(np.maximum(np.einsum("pse,pse->ps", w, w) - h * h,
                                   0.0))
            dx = r - radius
            dy = np.abs(h - lengths[lo:hi] / 2.0) - lengths[lo:hi] / 2.0
            d = np.minimum(np.maximum(dx, dy), 0.0) + np.sqrt(
                np.maximum(dx, 0.0) ** 2 + np.maximum(dy, 0.0) ** 2)
            best = d.min(axis=1)
            # The ball at each joint where a run starts from the one before
            # (every run's start but the path's own, unless it closes).
            first = lo if lo > 0 or self.closed else lo + 1
            if first < hi:
                joints = starts[first:hi]
                offset = p[:, None, :] - joints[None]
                ball = np.sqrt(np.einsum("pje,pje->pj", offset, offset))
                best = np.minimum(best, ball.min(axis=1) - radius)
            return best

        # Nearest group first, for every point: its exact distance is then a
        # tight bound, and the groups after it are worked out only for the
        # points they could still be nearer for -- two or three a point,
        # where taking the groups in path order against a loose bound
        # worked out a dozen. A coil spring spent a minute and a half of
        # its verification here.
        ranked = np.argsort(lower, axis=1)
        live = np.arange(points.shape[0])
        for rank in range(len(groups)):
            column = ranked[live, rank]
            live = live[lower[live, column] <= result[live]]
            if not live.size:
                break
            column = ranked[live, rank]
            order = np.argsort(column, kind="stable")
            live, column = live[order], column[order]
            cuts = np.flatnonzero(np.diff(column)) + 1
            for which in np.split(live, cuts):
                index = int(ranked[which[0], rank])
                result[which] = np.minimum(result[which],
                                           exactly(which, index))
        # Every group that could hold the nearest run was evaluated: one not
        # evaluated is further than a distance already found, and the bound
        # it started from is no smaller than the distance of the group that
        # set it.
        return result

    def _evaluate(self, points: Array) -> Array:
        outer = self._chain(points, self.radius, 0.0)
        if self.inner_radius <= 0.0:
            return outer
        bore = self._chain(points, self.inner_radius, self.radius)
        return np.maximum(outer, -bore)


@dataclass(frozen=True, slots=True)
class LoftSDF(SDF):
    """A solid passing from one profile to another between two parallel
    planes: each section between them the shapes blended in proportion.

    Not an exact distance -- the blend leans the side -- so its Lipschitz
    bound is stated: steeper the further apart the two outlines are for the
    height between them."""

    first: "Profile2D"
    second: "Profile2D"
    origin: tuple[float, float, float]
    u_axis: tuple[float, float, float]
    v_axis: tuple[float, float, float]
    w_axis: tuple[float, float, float]
    height: float
    shift: tuple[float, float] = (0.0, 0.0)
    #: The steepness, worked out once: see `_steepness`.
    _lean: list = field(default_factory=list, compare=False, repr=False)

    def __post_init__(self) -> None:
        if self.height <= 0.0:
            raise DegenerateGeometryError(
                "the two profiles of a loft must be on different planes, "
                "apart along their normal", height=self.height)

    def _spread(self) -> float:
        """How far apart the two outlines can put a point's two distances.

        The blend's lean along the loft is `(d2 - d1) / height`, so its
        steepness is set by the largest `|d2 - d1|` anywhere. This used to
        be bounded by the size of the whole loft -- 159 mm for a 115 by 110
        section -- where the outlines are a few millimetres apart: the field
        came out 1.76 times too shallow, and a `shell` of 8 mm on it built a
        14.07 mm wall. Every calf shell lofted through five sections had it.

        Now measured: the difference of two 1-Lipschitz distances is
        2-Lipschitz, so its largest value on a grid, plus what can hide
        between grid points, bounds it over the grid's region; and for exact
        outline distances the largest difference is reached near the
        outlines, inside the region. Never more than the old bound.
        """
        a = self.first.bounds()
        b = self.second.bounds()
        b = (b[0] + self.shift[0], b[1] + self.shift[0],
             b[2] + self.shift[1], b[3] + self.shift[1])
        coarse = math.hypot(max(a[1], b[1]) - min(a[0], b[0]),
                            max(a[3], b[3]) - min(a[2], b[2]))
        u_lo, u_hi = min(a[0], b[0]), max(a[1], b[1])
        v_lo, v_hi = min(a[2], b[2]), max(a[3], b[3])
        margin = max(5.0, 0.5 * max(u_hi - u_lo, v_hi - v_lo))
        samples = 257
        us = np.linspace(u_lo - margin, u_hi + margin, samples)
        vs = np.linspace(v_lo - margin, v_hi + margin, samples)
        gu, gv = np.meshgrid(us, vs, indexing="ij")
        try:
            gap = np.abs(self.second.distance(gu - self.shift[0],
                                              gv - self.shift[1])
                         - self.first.distance(gu, gv))
            largest = float(np.max(gap))
        except Exception:  # noqa: BLE001 - an outline that cannot be
            # sampled on a grid keeps the bound that needs no sampling.
            return coarse
        if not math.isfinite(largest):
            return coarse
        cell = math.hypot(us[1] - us[0], vs[1] - vs[0])
        return min(coarse, largest + cell)

    def _steepness(self) -> float:
        """The steepest the blend can lean anywhere, `sqrt(1 + (D/h)^2)`."""
        if not self._lean:
            self._lean.append(
                math.sqrt(1.0 + (self._spread() / self.height) ** 2))
        return self._lean[0]

    def _reach(self) -> float:
        """How deep the field is a distance rather than a lower bound on one.

        Within this of the side, each point's planar term is divided by the
        lean AT THAT POINT, which makes it the distance to the sloping side
        to first order; beyond it, by the steepest lean anywhere, which keeps
        the field's slope bounded however far out it is read. Half the
        loft's height: far more than any wall, fillet or offset taken on it.
        """
        return 0.5 * self.height

    @property
    def lipschitz(self) -> float:
        # d(planar/k) = d(planar)/k - planar * dk / k^2, with |d planar| <= k
        # and |dk| <= 2 |g| / (h^2 k) where g = d2 - d1. Inside the reach,
        # |planar| <= R, so the second term is at most 2 R q / h with
        # q = (D/h) / sqrt(1 + (D/h)^2) the largest |g| / (h k). Beyond it
        # the same term is frozen at R and the rest is slope / S <= 1.
        lean = self._spread() / self.height
        q = lean / math.sqrt(1.0 + lean * lean)
        return 1.0 + 2.0 * self._reach() * q / self.height

    @property
    def envelope(self) -> Box:
        a = self.first.bounds()
        b = self.second.bounds()
        u_lo = min(a[0], b[0] + self.shift[0])
        u_hi = max(a[1], b[1] + self.shift[0])
        v_lo = min(a[2], b[2] + self.shift[1])
        v_hi = max(a[3], b[3] + self.shift[1])
        origin = np.asarray(self.origin, dtype=float)
        u, v, w = (np.asarray(x, dtype=float) for x in
                   (self.u_axis, self.v_axis, self.w_axis))
        corners = np.array([origin + u * cu + v * cv + w * cw
                            for cu in (u_lo, u_hi) for cv in (v_lo, v_hi)
                            for cw in (0.0, self.height)])
        return Box(tuple(corners.min(axis=0).tolist()),  # type: ignore
                   tuple(corners.max(axis=0).tolist()))  # type: ignore

    def _evaluate(self, points: Array) -> Array:
        rel = points - np.asarray(self.origin, dtype=float)
        u = rel @ np.asarray(self.u_axis, dtype=float)
        v = rel @ np.asarray(self.v_axis, dtype=float)
        w = rel @ np.asarray(self.w_axis, dtype=float)
        t = np.clip(w / self.height, 0.0, 1.0)
        d1 = self.first.distance(u, v)
        d2 = self.second.distance(u - self.shift[0], v - self.shift[1])
        planar = (1.0 - t) * d1 + t * d2
        # The side leans by (d2 - d1) / h here, so a planar distance is
        # sqrt(1 + lean^2) times the distance to the side: divided by it, the
        # wall a `shell` takes on a loft is the wall asked for. Divided by
        # the steepest lean everywhere instead, as this was, an 8 mm shell on
        # a calf lofted through five sections came out 14.07 mm -- and its
        # closed ends 14 mm as well, though the ends do not lean at all.
        local = np.sqrt(1.0 + ((d2 - d1) / self.height) ** 2)
        reach = self._reach()
        near = np.clip(planar, -reach, reach)
        planar = near / local + (planar - near) / self._steepness()
        axial = np.abs(w - self.height / 2.0) - self.height / 2.0
        outside = np.sqrt(np.maximum(planar, 0.0) ** 2
                          + np.maximum(axial, 0.0) ** 2)
        inside = np.minimum(np.maximum(planar, axial), 0.0)
        return outside + inside


@dataclass(frozen=True, slots=True)
class LoftStackSDF(SDF):
    """One solid lofted through several sections in turn, along one axis.

    A calf shell was lofted through five sections as four lofts, each from
    one section to the next, unioned. Each loft has its own closed ends, so
    inside the union every section plane is where two solids meet face to
    face -- and a union's field there reads the distance to those inner
    faces, not to the outside. A `shell` of it built a hollow with a solid
    floor 16 mm thick across every section: three of them, sealed inside the
    calf, with a crack of no thickness down each. As one solid through all
    its sections there are no inner faces: its only ends are the first
    section and the last.

    Between two sections the outline blends exactly as a two-section loft
    does, with the same lean-by-lean normalisation; across each section
    plane the normalisation is blended over a quarter of the shorter
    neighbour's height, so the field stays continuous, and its Lipschitz
    bound is stated for that.
    """

    #: (outline, distance along the axis from `origin`, (u, v) offset of the
    #: outline's own origin), in order along the axis, the first at 0.
    sections: tuple
    origin: tuple[float, float, float]
    u_axis: tuple[float, float, float]
    v_axis: tuple[float, float, float]
    w_axis: tuple[float, float, float]
    _cache: list = field(default_factory=list, compare=False, repr=False)

    def __post_init__(self) -> None:
        if len(self.sections) < 2:
            raise DegenerateGeometryError("a loft needs two sections at least")
        heights = [float(s[1]) for s in self.sections]
        if any(b - a <= 0.0 for a, b in zip(heights, heights[1:])):
            raise DegenerateGeometryError(
                "the sections of a loft must be on different planes, in order "
                "along their normal", heights=heights)

    def _segments(self) -> list["LoftSDF"]:
        return [LoftSDF(first=a[0], second=b[0], origin=(0.0, 0.0, 0.0),
                        u_axis=(1.0, 0.0, 0.0), v_axis=(0.0, 1.0, 0.0),
                        w_axis=(0.0, 0.0, 1.0), height=float(b[1] - a[1]),
                        shift=(float(b[2][0] - a[2][0]),
                               float(b[2][1] - a[2][1])))
                for a, b in zip(self.sections, self.sections[1:])]

    def _figures(self) -> tuple[float, float, float, float]:
        """(steepest lean S, largest q, reach R, blend width) -- once."""
        if not self._cache:
            segments = self._segments()
            steep = max(seg._steepness() for seg in segments)
            q = 0.0
            for seg in segments:
                lean = seg._spread() / seg.height
                q = max(q, lean / math.sqrt(1.0 + lean * lean))
            shortest = min(seg.height for seg in segments)
            self._cache.append((steep, q, 0.5 * shortest, 0.25 * shortest))
        return self._cache[0]

    @property
    def lipschitz(self) -> float:
        steep, q, reach, blend = self._figures()
        return steep + q + reach * (steep - 1.0) / blend

    @property
    def envelope(self) -> Box:
        origin = np.asarray(self.origin, dtype=float)
        u, v, w = (np.asarray(x, dtype=float) for x in
                   (self.u_axis, self.v_axis, self.w_axis))
        corners = []
        for outline, along, (su, sv) in self.sections:
            b = outline.bounds()
            for cu in (b[0] + su, b[1] + su):
                for cv in (b[2] + sv, b[3] + sv):
                    corners.append(origin + u * cu + v * cv + w * float(along))
        stacked = np.array(corners)
        return Box(tuple(stacked.min(axis=0).tolist()),  # type: ignore
                   tuple(stacked.max(axis=0).tolist()))  # type: ignore

    def _evaluate(self, points: Array) -> Array:
        steep, _, reach, blend = self._figures()
        rel = points - np.asarray(self.origin, dtype=float)
        u = rel @ np.asarray(self.u_axis, dtype=float)
        v = rel @ np.asarray(self.v_axis, dtype=float)
        w = rel @ np.asarray(self.w_axis, dtype=float)
        heights = np.array([float(s[1]) for s in self.sections])
        top = float(heights[-1])
        distances = np.stack([outline.distance(u - su, v - sv)
                              for outline, _, (su, sv) in self.sections])
        n = len(self.sections)
        wc = np.clip(w, 0.0, top)
        index = np.clip(np.searchsorted(heights, wc, side="right") - 1, 0,
                        n - 2)
        lo_h, hi_h = heights[index], heights[index + 1]
        span = hi_h - lo_h
        t = (wc - lo_h) / span
        columns = np.arange(points.shape[0])
        d_lo, d_hi = distances[index, columns], distances[index + 1, columns]
        planar = (1.0 - t) * d_lo + t * d_hi
        gaps = distances[1:] - distances[:-1]
        spans = (heights[1:] - heights[:-1])[:, None]
        leans = np.sqrt(1.0 + (gaps / spans) ** 2)
        local = leans[index, columns]
        # Across each inner section plane, the two segments' normalisations
        # meet halfway: continuous, so the field has no step in it.
        below = (index >= 1) & (wc - lo_h < blend)
        if np.any(below):
            alpha = 0.5 + 0.5 * (wc[below] - lo_h[below]) / blend
            local[below] = (alpha * local[below] + (1.0 - alpha)
                            * leans[index[below] - 1, columns[below]])
        above = (index + 1 <= n - 2) & (hi_h - wc < blend)
        if np.any(above):
            alpha = 0.5 + 0.5 * (hi_h[above] - wc[above]) / blend
            local[above] = (alpha * local[above] + (1.0 - alpha)
                            * leans[index[above] + 1, columns[above]])
        near = np.clip(planar, -reach, reach)
        planar = near / local + (planar - near) / steep
        axial = np.abs(w - top / 2.0) - top / 2.0
        outside = np.sqrt(np.maximum(planar, 0.0) ** 2
                          + np.maximum(axial, 0.0) ** 2)
        inside = np.minimum(np.maximum(planar, axial), 0.0)
        return outside + inside


def stack_lofts(operands: Sequence[SDF]) -> list[SDF]:
    """Lofts that run on from one another, made one loft through them all.

    Two lofts chain when the second starts at the section the first ends on
    -- the same outline, in the same place, on the same axes. Anything else
    is left exactly as it was.
    """
    def as_stack(solid: SDF) -> "LoftStackSDF | None":
        if isinstance(solid, LoftStackSDF):
            return solid
        if isinstance(solid, LoftSDF):
            return LoftStackSDF(
                sections=((solid.first, 0.0, (0.0, 0.0)),
                          (solid.second, float(solid.height),
                           (float(solid.shift[0]), float(solid.shift[1])))),
                origin=tuple(float(c) for c in solid.origin),  # type: ignore
                u_axis=tuple(float(c) for c in solid.u_axis),  # type: ignore
                v_axis=tuple(float(c) for c in solid.v_axis),  # type: ignore
                w_axis=tuple(float(c) for c in solid.w_axis))  # type: ignore
        return None

    def end_of(stack: LoftStackSDF) -> tuple[Profile2D, np.ndarray]:
        outline, along, (su, sv) = stack.sections[-1]
        where = (np.asarray(stack.origin, dtype=float)
                 + np.asarray(stack.u_axis) * su + np.asarray(stack.v_axis) * sv
                 + np.asarray(stack.w_axis) * float(along))
        return outline, where

    def joined(a: LoftStackSDF, b: LoftStackSDF) -> "LoftStackSDF | None":
        for x, y in ((a.u_axis, b.u_axis), (a.v_axis, b.v_axis),
                     (a.w_axis, b.w_axis)):
            if not np.allclose(x, y, atol=1e-9):
                return None
        outline, where = end_of(a)
        first, along0, (su0, sv0) = b.sections[0]
        if outline != first or abs(float(along0)) > 1e-9:
            return None
        start = (np.asarray(b.origin, dtype=float)
                 + np.asarray(b.u_axis) * su0 + np.asarray(b.v_axis) * sv0)
        if not np.allclose(start, where, atol=1e-6):
            return None
        rel = start - np.asarray(a.origin, dtype=float)
        base_w = float(rel @ np.asarray(a.w_axis))
        base_u = float(rel @ np.asarray(a.u_axis)) - su0
        base_v = float(rel @ np.asarray(a.v_axis)) - sv0
        extra = tuple((o, base_w + float(h), (base_u + su, base_v + sv))
                      for o, h, (su, sv) in b.sections[1:])
        return LoftStackSDF(sections=tuple(a.sections) + extra,
                            origin=a.origin, u_axis=a.u_axis,
                            v_axis=a.v_axis, w_axis=a.w_axis)

    items: list[SDF] = list(operands)
    changed = True
    while changed:
        changed = False
        for i in range(len(items)):
            a = as_stack(items[i])
            if a is None:
                continue
            for j in range(len(items)):
                if i == j:
                    continue
                b = as_stack(items[j])
                if b is None:
                    continue
                merged = joined(a, b)
                if merged is not None:
                    items = [x for k, x in enumerate(items)
                             if k not in (i, j)] + [merged]
                    changed = True
                    break
            if changed:
                break
    return items


# ----------------------------------------------------------------------
# Combinators
# ----------------------------------------------------------------------
def _smooth_min(a: Array, b: Array, k: float) -> Array:
    """Round union: a true circular fillet of radius ``k`` at the junction.

    Chosen over the more common polynomial smooth minimum for one reason that
    matters to engineers: the resulting fillet has *exactly* radius ``k``. The
    polynomial form produces a pleasant-looking blend whose actual radius is not
    the number you passed in, which is fine for rendering and not fine for a
    part someone will machine and inspect.

    The formula is the standard exact round-union:

        u = max(k - a, 0), v = max(k - b, 0)
        result = max(k, min(a, b)) - hypot(u, v)

    Two properties the rest of the system depends on:

    *Locality.* When either operand is further than ``k`` from the surface, the
    corresponding term vanishes and the result is exactly ``min(a, b)``. The
    blend cannot affect geometry away from the junction.

    *Monotonicity.* The result is non-decreasing in both ``a`` and ``b``, which
    is what makes interval bounds computable by evaluating the endpoints -- and
    therefore what keeps the rigorous measurement in :mod:`forge_geom.measure`
    valid across blended geometry.

    A caveat worth knowing, because it is a property of implicit blending rather
    than a defect: where two operands share a *coplanar* face, there is no
    concave crease to fill, and the blend still adds material there -- up to
    ``(sqrt(2) - 1) * k``. A design that needs a flush face across a blended
    junction should trim the result to its declared envelope with an explicit
    intersection, which is both a legitimate modelling operation and a statement
    of intent the verifier can then check.
    """
    if k <= 0.0:
        return np.minimum(a, b)
    u = np.maximum(k - a, 0.0)
    v = np.maximum(k - b, 0.0)
    return np.maximum(k, np.minimum(a, b)) - np.hypot(u, v)


def _smooth_max(a: Array, b: Array, k: float) -> Array:
    """Round intersection: the De Morgan dual of :func:`_smooth_min`.

    Also used for a blended subtraction, where it rounds the inside corner left
    behind when material is removed.
    """
    if k <= 0.0:
        return np.maximum(a, b)
    u = np.maximum(k + a, 0.0)
    v = np.maximum(k + b, 0.0)
    return np.minimum(-k, np.maximum(a, b)) + np.hypot(u, v)


def _chamfer_min(a: Array, b: Array, c: float) -> Array:
    """Union with a 45-degree chamfer of leg `c` in the crease."""
    return np.minimum(np.minimum(a, b), (a + b - c) * math.sqrt(0.5))


def _chamfer_max(a: Array, b: Array, c: float) -> Array:
    """Intersection with a 45-degree chamfer of leg `c` on the ridge."""
    return np.maximum(np.maximum(a, b), (a + b + c) * math.sqrt(0.5))


def _chamfer_lipschitz(operands: "tuple[SDF, ...]", chamfer: float) -> float:
    """The Lipschitz constant a chamfered boolean over ``operands`` can declare.

    The chamfer term ``(a + b - c) / sqrt(2)`` has gradient at most
    ``(A + B) / sqrt(2)``: ``sqrt(2)`` for two 1-Lipschitz operands. And, as
    with the blends in :func:`_blend_lipschitz`, the booleans left-fold the
    chamfer over ``n`` operands, feeding each result back in as one side, so
    the constant compounds: ``L_1 = base``, ``L_k = (L_{k-1} + base) /
    sqrt(2)`` -- 1.414, 1.707, 1.914, 2.061, 2.164 for n = 2..6, which is
    exactly what identical chamfered spheres measured. Declared as a flat
    ``sqrt(2)`` the octree decided cells a half millimetre outside a
    three-sphere intersection as empty while a corner of each held material.
    """
    base = max(operand.lipschitz for operand in operands)
    if chamfer <= 0.0:
        return base
    constant = base
    for _ in operands[1:]:
        constant = max(constant, (constant + base) / math.sqrt(2.0))
    return constant


def _blend_lipschitz(operands: "tuple[SDF, ...]", blend_radius: float) -> float:
    """The Lipschitz constant a blended boolean over ``operands`` can declare.

    Getting this right is not cosmetic. The rigorous measurement in
    :mod:`forge_geom.measure` classifies a cell as entirely inside or outside by
    comparing the field value against the cell radius times this constant, so
    understating it lets the measurement decide a cell it has no right to
    decide, and the volume enclosure stops being an enclosure.

    A *sharp* boolean of ``L``-Lipschitz fields stays ``L``-Lipschitz, because
    min and max simply select one operand however many there are.

    A blended one does not. For the round union ``f = k - hypot(k-a, k-b)`` the
    gradient is ``(p*grad_a + q*grad_b)/hypot(p, q)`` with ``p = k-a`` and
    ``q = k-b``. With ``A``- and ``B``-Lipschitz operands its magnitude is at
    most ``(p*A + q*B)/hypot(p, q)``, which by Cauchy-Schwarz peaks at
    ``p/q == A/B`` and equals ``sqrt(A**2 + B**2)`` -- ``sqrt(2)`` for two
    1-Lipschitz operands.

    That is the answer for a *binary* blend, and declaring it for the whole node
    was a bug, because :meth:`Union._evaluate` and its siblings left-fold the
    blend over ``n`` operands. Each fold step feeds the previous result back in
    as one side, so the constant compounds: ``L_1 = base`` and
    ``L_k = sqrt(L_{k-1}**2 + base**2)``, giving ``L_n = base*sqrt(n)``. With
    ``n`` identical blended operands -- the arrangement that sits exactly on the
    Cauchy-Schwarz maximiser at every step -- the measured peak gradient was
    2.0000 at ``n = 4`` and 2.4495 at ``n = 6``, against a declared 1.4142.
    """
    base = max(operand.lipschitz for operand in operands)
    if blend_radius <= 0.0:
        return base
    return base * math.sqrt(len(operands))


@dataclass(frozen=True, slots=True)
class Union(SDF):
    operands: tuple[SDF, ...]
    blend_radius: float = 0.0
    chamfer: float = 0.0

    def __post_init__(self) -> None:
        if len(self.operands) < 1:
            raise DegenerateGeometryError("union needs at least one operand")
        if self.blend_radius < 0.0:
            raise DegenerateGeometryError(
                "blend radius must not be negative", blend_radius=self.blend_radius
            )

    @property
    def lipschitz(self) -> float:
        if self.chamfer > 0.0:
            return _chamfer_lipschitz(self.operands, self.chamfer)
        return _blend_lipschitz(self.operands, self.blend_radius)

    @property
    def envelope(self) -> Box:
        envelope = Box.empty()
        for operand in self.operands:
            envelope = envelope.union(operand.envelope)
        # A blend adds material in the crease, never beyond the blend radius.
        grow = max(self.blend_radius, self.chamfer)
        return envelope.grown(grow) if grow else envelope

    def _within(self) -> "BoxSDF | None":
        """The box a blend's material may not leave: every operand's own.

        A blend fills the creases between solids, and a crease is inside the
        solids' hull. But the smooth minimum also swells wherever two
        surfaces run together -- a 30 mm boss on a 30 mm rail, tangent to
        both its sides and its end -- and there it put 0.37 mm of material
        beyond the rail's side, so a rail drawn 30 wide measured 30.73.
        Bounded by the operands' own envelopes, which contain every real
        fillet, the swelling past the part is cut off and the creases keep
        all of theirs. Lipschitz 1, so the field stays sound.
        """
        if not (self.blend_radius > 0.0 or self.chamfer > 0.0) or len(
                self.operands) < 2:
            return None
        envelope = Box.empty()
        for operand in self.operands:
            envelope = envelope.union(operand.envelope)
        if envelope.is_empty or not all(
                math.isfinite(c) for c in (*envelope.lo, *envelope.hi)):
            return None
        half = [0.5 * (b - a) for a, b in zip(envelope.lo, envelope.hi)]
        if min(half) <= 0.0:
            return None
        return BoxSDF(envelope.centre, tuple(half))  # type: ignore[arg-type]

    def _evaluate(self, points: Array) -> Array:
        result = self.operands[0](points)
        for operand in self.operands[1:]:
            value = operand(points)
            result = (
                _chamfer_min(result, value, self.chamfer)
                if self.chamfer > 0.0 else
                _smooth_min(result, value, self.blend_radius)
                if self.blend_radius > 0.0
                else np.minimum(result, value)
            )
        within = self._within()
        if within is not None:
            result = np.maximum(result, within(points))
        return result

    def bounds(self, box: IArray) -> IArray:
        within = self._within()
        result = self._blended_bounds(box)
        if within is not None:
            result = ib.imax(result, within.bounds(box))
        return result

    def _blended_bounds(self, box: IArray) -> IArray:
        # min is monotone increasing in both arguments, and so is the quadratic
        # smooth minimum, so bounding each operand and combining the bounds is
        # exact with respect to the combination step.
        result = self.operands[0].bounds(box)
        for operand in self.operands[1:]:
            value = operand.bounds(box)
            if self.chamfer > 0.0:
                result = (
                    _chamfer_min(result[0], value[0], self.chamfer),
                    _chamfer_min(result[1], value[1], self.chamfer),
                )
            elif self.blend_radius > 0.0:
                result = (
                    _smooth_min(result[0], value[0], self.blend_radius),
                    _smooth_min(result[1], value[1], self.blend_radius),
                )
            else:
                result = ib.imin(result, value)
        return result


@dataclass(frozen=True, slots=True)
class Intersection(SDF):
    operands: tuple[SDF, ...]
    blend_radius: float = 0.0
    chamfer: float = 0.0

    def __post_init__(self) -> None:
        if len(self.operands) < 1:
            raise DegenerateGeometryError("intersection needs at least one operand")

    @property
    def lipschitz(self) -> float:
        if self.chamfer > 0.0:
            return _chamfer_lipschitz(self.operands, self.chamfer)
        return _blend_lipschitz(self.operands, self.blend_radius)

    @property
    def envelope(self) -> Box:
        envelope = self.operands[0].envelope
        for operand in self.operands[1:]:
            envelope = envelope.intersection(operand.envelope)
        return envelope

    def _evaluate(self, points: Array) -> Array:
        result = self.operands[0](points)
        for operand in self.operands[1:]:
            value = operand(points)
            result = (
                _chamfer_max(result, value, self.chamfer)
                if self.chamfer > 0.0 else
                _smooth_max(result, value, self.blend_radius)
                if self.blend_radius > 0.0
                else np.maximum(result, value)
            )
        return result

    def bounds(self, box: IArray) -> IArray:
        result = self.operands[0].bounds(box)
        for operand in self.operands[1:]:
            value = operand.bounds(box)
            if self.chamfer > 0.0:
                result = (
                    _chamfer_max(result[0], value[0], self.chamfer),
                    _chamfer_max(result[1], value[1], self.chamfer),
                )
            elif self.blend_radius > 0.0:
                result = (
                    _smooth_max(result[0], value[0], self.blend_radius),
                    _smooth_max(result[1], value[1], self.blend_radius),
                )
            else:
                result = ib.imax(result, value)
        return result


def _far_from(envelope: "Box", points: Array, result: Array,
              blend: float) -> Array:
    """Where an exact tool inside `envelope` cannot change max(result, -tool)
    or its blend: the tool is at least the distance to its envelope away, and
    when that is at least -result and at least the blend radius, -tool is at
    most result and at most -blend, where both the sharp and the smooth max
    give back `result` itself."""
    lo = np.asarray(envelope.lo, dtype=float)
    hi = np.asarray(envelope.hi, dtype=float)
    gap = np.maximum(np.maximum(lo - points, points - hi), 0.0)
    squared = np.einsum("ij,ij->i", gap, gap)
    # Outside the envelope only: inside it the tool can be negative.
    reach = np.maximum(-np.asarray(result, dtype=float) + 1e-12, blend)
    return (squared > 0.0) & ((reach <= 0.0) | (squared >= reach * reach))


def _bounds_beside(tool: SDF, box: IArray, result: IArray) -> IArray | None:
    """`max(result, -tool)` over cells, without bounding the tool on the
    cells its envelope does not reach.

    On a cell a gap `g` clear of an exact tool's envelope the tool is at
    least `g`, so `-tool` lies in `(-inf, -g]` and the sharp max is
    `(lo, max(hi, -g))` -- sound, and exactly as decisive about the cell's
    sign. A plate with fifteen holes and four counterbores bounded thirty
    cylinders on every cell of every octree; most of a verification was
    that. None when the cells are not an array of boxes."""
    lo_box, hi_box = box
    lo_box = np.asarray(lo_box, dtype=float)
    hi_box = np.asarray(hi_box, dtype=float)
    if lo_box.ndim != 2 or lo_box.shape[0] < 16 or lo_box.shape[1] != 3:
        return None
    envelope = tool.envelope
    gap_axes = np.maximum(np.maximum(np.asarray(envelope.lo) - hi_box,
                                     lo_box - np.asarray(envelope.hi)), 0.0)
    gap = np.sqrt(np.einsum("ij,ij->i", gap_axes, gap_axes))
    far = gap > 0.0
    if not far.any():
        return None
    lo = np.array(result[0], dtype=float, copy=True)
    hi = np.array(result[1], dtype=float, copy=True)
    if lo.shape != gap.shape:
        return None
    hi[far] = np.maximum(hi[far], -gap[far])
    near = ~far
    if near.any():
        value = ib.ineg(tool.bounds((lo_box[near], hi_box[near])))
        lo[near] = np.maximum(lo[near], value[0])
        hi[near] = np.maximum(hi[near], value[1])
    return lo, hi


#: When a difference sorts its points, or cells, to cull its tools: enough
#: of both that one sort costs less than a pass per tool.
_CULL_POINTS = 4096
_CULL_CELLS = 2048
_CULL_TOOLS = 6


def _bounds_beside_culled(tool: SDF, box: IArray, result: IArray,
                          culled: tuple[Array, Array, float, Array]
                          ) -> IArray:
    """`_bounds_beside` over cells sorted along x: every cell whose low x
    is past the tool's envelope, or more than the widest cell short of it,
    is clear of the tool, and only the run between is looked at."""
    order, lows, widest, _ = culled
    lo_box, hi_box = box
    envelope = tool.envelope
    start = int(np.searchsorted(lows, envelope.lo[0] - widest, "left"))
    stop = int(np.searchsorted(lows, envelope.hi[0], "right"))
    lo = np.array(result[0], dtype=float, copy=True)
    hi = np.array(result[1], dtype=float, copy=True)
    # Clear along x: at least the x gap away, which is a sound floor on the
    # tool everywhere in the cell.
    gap_x = np.maximum(np.maximum(envelope.lo[0] - hi_box[:, 0],
                                  lo_box[:, 0] - envelope.hi[0]), 0.0)
    hi = np.maximum(hi, -gap_x)
    if stop > start:
        run = order[start:stop]
        sub = _bounds_beside(tool, (lo_box[run], hi_box[run]),
                             (result[0][run], result[1][run]))
        if sub is None:
            value = ib.ineg(tool.bounds((lo_box[run], hi_box[run])))
            lo[run] = np.maximum(result[0][run], value[0])
            hi[run] = np.maximum(result[1][run], value[1])
        else:
            lo[run], hi[run] = sub
    return lo, hi


@dataclass(frozen=True, slots=True)
class Difference(SDF):
    base: SDF
    tools: tuple[SDF, ...]
    blend_radius: float = 0.0
    chamfer: float = 0.0

    @property
    def lipschitz(self) -> float:
        if self.chamfer > 0.0:
            return _chamfer_lipschitz((self.base, *self.tools), self.chamfer)
        return _blend_lipschitz((self.base, *self.tools), self.blend_radius)

    @property
    def envelope(self) -> Box:
        # Removing material can only shrink the solid, so the base envelope
        # remains a valid outer bound.
        return self.base.envelope

    def _evaluate(self, points: Array) -> Array:
        result = self.base(points)
        # Many exact tools over many points -- a plate's fifteen holes and
        # their counterbores: the points sorted along x once, and each tool
        # looks only at the run of them its envelope, grown by the furthest
        # any point can be reached, spans. The far test then runs on those
        # alone; every point outside the run is further along x alone.
        culled = None
        if (self.chamfer <= 0.0 and points.shape[0] >= _CULL_POINTS
                and sum(isinstance(t, _EXACT_FIELDS) for t in self.tools)
                >= _CULL_TOOLS):
            order = np.argsort(points[:, 0], kind="stable")
            culled = (order, points[order, 0],
                      max(float(np.max(-np.asarray(result, dtype=float))),
                          self.blend_radius, 0.0) + 1e-9)
        for tool in self.tools:
            # A hole changes the field only near itself. Where an exact tool
            # is further from a point than the point is from the surface --
            # and further than the blend reaches -- the difference is the
            # base's own value, exactly (see `_far_from`), and the tool need
            # not be evaluated there. A plate with fifteen holes evaluated
            # every hole at every point; most of a verification was that.
            if culled is not None and isinstance(tool, _EXACT_FIELDS):
                order, xs, reach = culled
                envelope = tool.envelope
                start = int(np.searchsorted(xs, envelope.lo[0] - reach, "left"))
                stop = int(np.searchsorted(xs, envelope.hi[0] + reach, "right"))
                if stop <= start:
                    continue
                candidates = order[start:stop]
                local = np.asarray(result, dtype=float)[candidates]
                which = candidates[~_far_from(envelope, points[candidates],
                                              local, self.blend_radius)]
                if which.size == 0:
                    continue
                result = np.array(result, dtype=float, copy=True)
                value = -tool(points[which])
                result[which] = (
                    _smooth_max(result[which], value, self.blend_radius)
                    if self.blend_radius > 0.0
                    else np.maximum(result[which], value))
                continue
            if (self.chamfer <= 0.0 and isinstance(tool, _EXACT_FIELDS)
                    and points.shape[0] >= 256):
                near = ~_far_from(tool.envelope, points, result,
                                  self.blend_radius)
                count = int(near.sum())
                if count == 0:
                    continue
                if count < points.shape[0]:
                    result = np.array(result, dtype=float, copy=True)
                    value = -tool(points[near])
                    result[near] = (
                        _smooth_max(result[near], value, self.blend_radius)
                        if self.blend_radius > 0.0
                        else np.maximum(result[near], value))
                    continue
            value = -tool(points)
            result = (
                _chamfer_max(result, value, self.chamfer)
                if self.chamfer > 0.0 else
                _smooth_max(result, value, self.blend_radius)
                if self.blend_radius > 0.0
                else np.maximum(result, value)
            )
        return result

    def bounds(self, box: IArray) -> IArray:
        result = self.base.bounds(box)
        culled = None
        lo_box = np.asarray(box[0], dtype=float)
        if (self.chamfer <= 0.0 and self.blend_radius <= 0.0
                and lo_box.ndim == 2 and lo_box.shape[0] >= _CULL_CELLS
                and sum(isinstance(t, _EXACT_FIELDS) for t in self.tools)
                >= _CULL_TOOLS):
            hi_box = np.asarray(box[1], dtype=float)
            order = np.argsort(lo_box[:, 0], kind="stable")
            culled = (order, lo_box[order, 0],
                      float(np.max(hi_box[:, 0] - lo_box[:, 0])), hi_box)
        for tool in self.tools:
            if culled is not None and isinstance(tool, _EXACT_FIELDS):
                result = _bounds_beside_culled(tool, (lo_box, culled[3]),
                                               result, culled)
                continue
            if (self.chamfer <= 0.0 and self.blend_radius <= 0.0
                    and isinstance(tool, _EXACT_FIELDS)):
                skipped = _bounds_beside(tool, box, result)
                if skipped is not None:
                    result = skipped
                    continue
            value = ib.ineg(tool.bounds(box))
            if self.chamfer > 0.0:
                result = (
                    _chamfer_max(result[0], value[0], self.chamfer),
                    _chamfer_max(result[1], value[1], self.chamfer),
                )
            elif self.blend_radius > 0.0:
                result = (
                    _smooth_max(result[0], value[0], self.blend_radius),
                    _smooth_max(result[1], value[1], self.blend_radius),
                )
            else:
                result = ib.imax(result, value)
        return result


@dataclass(frozen=True, slots=True)
class Shell(SDF):
    """A uniform-thickness wall about the boundary of ``solid``."""

    solid: SDF
    thickness: float
    direction: str = "inward"

    def __post_init__(self) -> None:
        if self.thickness <= 0.0:
            raise DegenerateGeometryError(
                "shell thickness must be positive", thickness=self.thickness
            )
        if self.direction not in ("inward", "outward", "both"):
            raise DegenerateGeometryError(
                "unknown shell direction", direction=self.direction
            )

    @property
    def lipschitz(self) -> float:
        return self.solid.lipschitz

    @property
    def envelope(self) -> Box:
        if self.direction == "inward":
            return self.solid.envelope
        return self.solid.envelope.grown(
            self.thickness if self.direction == "outward" else self.thickness / 2.0
        )

    def _evaluate(self, points: Array) -> Array:
        field = self.solid(points)
        if self.direction == "inward":
            return np.maximum(field, -(field + self.thickness))
        if self.direction == "outward":
            return np.maximum(field - self.thickness, -field)
        half = self.thickness / 2.0
        return np.abs(field) - half

    def bounds(self, box: IArray) -> IArray:
        # The inner field appears twice in each expression below, so interval
        # evaluation loses tightness here (the classic dependency problem).
        # The result stays a sound enclosure; shells simply need a little more
        # refinement than the primitives do.
        field = self.solid.bounds(box)
        if self.direction == "inward":
            return ib.imax(field, ib.ineg(ib.iadd_scalar(field, self.thickness)))
        if self.direction == "outward":
            return ib.imax(ib.iadd_scalar(field, -self.thickness), ib.ineg(field))
        return ib.iadd_scalar(ib.iabs(field), -self.thickness / 2.0)


@dataclass(frozen=True, slots=True)
class Offset(SDF):
    """Grow (positive) or shrink (negative) a solid uniformly."""

    solid: SDF
    distance: float

    @property
    def lipschitz(self) -> float:
        return self.solid.lipschitz

    @property
    def envelope(self) -> Box:
        return self.solid.envelope.grown(max(0.0, self.distance))

    def _evaluate(self, points: Array) -> Array:
        return self.solid(points) - self.distance

    def bounds(self, box: IArray) -> IArray:
        return ib.iadd_scalar(self.solid.bounds(box), -self.distance)


@dataclass(frozen=True, slots=True)
class Transform(SDF):
    """A rigid motion. Distances are preserved, so the field stays exact."""

    solid: SDF
    rotation: tuple[float, ...]  # row-major 3x3
    translation: tuple[float, float, float]

    @property
    def matrix(self) -> Array:
        return np.asarray(self.rotation, dtype=float).reshape(3, 3)

    @property
    def lipschitz(self) -> float:
        return self.solid.lipschitz

    @property
    def envelope(self) -> Box:
        return self.solid.envelope.transformed(
            self.matrix, np.asarray(self.translation, dtype=float)
        )

    def _evaluate(self, points: Array) -> Array:
        # Inverse transform the query points; for a rotation the inverse is the
        # transpose, so no matrix inversion (and no conditioning risk) is needed.
        local = (points - np.asarray(self.translation, dtype=float)) @ self.matrix
        return self.solid(local)

    def bounds(self, box: IArray) -> IArray:
        # Map the cell into the solid's own frame. A rotated cell is not
        # axis-aligned, so we take its axis-aligned hull: centre maps by the
        # rotation, and the half-extent grows by |R| applied to it. The hull
        # contains the true cell, so the bound remains sound.
        rotation = self.matrix
        translation = np.asarray(self.translation, dtype=float)
        lo, hi = box
        centre = (lo + hi) / 2.0
        half = (hi - lo) / 2.0
        local_centre = (centre - translation) @ rotation
        local_half = half @ np.abs(rotation)
        return self.solid.bounds((local_centre - local_half, local_centre + local_half))


@dataclass(frozen=True, slots=True)
class Repeat(SDF):
    """A finite linear pattern, realised as the union of transformed copies."""

    solid: SDF
    step: tuple[float, float, float]
    count: int

    def __post_init__(self) -> None:
        if self.count < 1:
            raise DegenerateGeometryError("pattern count must be at least one",
                                          count=self.count)

    @property
    def lipschitz(self) -> float:
        return self.solid.lipschitz

    @property
    def envelope(self) -> Box:
        envelope = Box.empty()
        for index in range(self.count):
            shift = np.asarray(self.step, dtype=float) * index
            envelope = envelope.union(
                self.solid.envelope.transformed(np.eye(3), shift)
            )
        return envelope

    def _evaluate(self, points: Array) -> Array:
        step = np.asarray(self.step, dtype=float)
        result = self.solid(points)
        for index in range(1, self.count):
            result = np.minimum(result, self.solid(points - step * index))
        return result

    def bounds(self, box: IArray) -> IArray:
        step = np.asarray(self.step, dtype=float)
        lo, hi = box
        result = self.solid.bounds(box)
        for index in range(1, self.count):
            shift = step * index
            result = ib.imin(self.solid.bounds((lo - shift, hi - shift)), result)
        return result


@dataclass(frozen=True, slots=True)
class Mirror(SDF):
    """Union of a solid with its reflection across a plane."""

    solid: SDF
    point: tuple[float, float, float]
    normal: tuple[float, float, float]
    keep_original: bool = True

    @property
    def unit_normal(self) -> Array:
        normal = np.asarray(self.normal, dtype=float)
        length = np.linalg.norm(normal)
        if length < EPSILON:
            raise DegenerateGeometryError("mirror plane normal has zero length")
        return normal / length

    @property
    def lipschitz(self) -> float:
        return self.solid.lipschitz

    @property
    def envelope(self) -> Box:
        normal = self.unit_normal
        reflection = np.eye(3) - 2.0 * np.outer(normal, normal)
        point = np.asarray(self.point, dtype=float)
        translation = point - reflection @ point
        mirrored = self.solid.envelope.transformed(reflection, translation)
        return (
            self.solid.envelope.union(mirrored)
            if self.keep_original
            else mirrored
        )

    def _evaluate(self, points: Array) -> Array:
        normal = self.unit_normal
        point = np.asarray(self.point, dtype=float)
        signed = (points - point) @ normal
        reflected = points - 2.0 * np.outer(signed, normal)
        mirrored = self.solid(reflected)
        if not self.keep_original:
            return mirrored
        return np.minimum(self.solid(points), mirrored)

    def bounds(self, box: IArray) -> IArray:
        normal = self.unit_normal
        point = np.asarray(self.point, dtype=float)
        reflection = np.eye(3) - 2.0 * np.outer(normal, normal)
        lo, hi = box
        centre = (lo + hi) / 2.0
        half = (hi - lo) / 2.0
        # A reflection is its own inverse, so the same matrix maps the cell into
        # the mirrored frame.
        local_centre = (centre - point) @ reflection + point
        local_half = half @ np.abs(reflection)
        mirrored = self.solid.bounds(
            (local_centre - local_half, local_centre + local_half)
        )
        if not self.keep_original:
            return mirrored
        return ib.imin(self.solid.bounds(box), mirrored)


@dataclass(frozen=True, slots=True)
class Revolve(SDF):
    """Revolve a 2D profile about an axis.

    The profile's ``u`` coordinate is the radial distance from the axis and
    ``v`` is the position along it. A partial revolution is the intersection of
    the full revolution with a wedge.
    """

    profile: Profile2D
    origin: tuple[float, float, float]
    axis: tuple[float, float, float]
    reference: tuple[float, float, float]
    angle: float = 2.0 * math.pi

    @property
    def unit_axis(self) -> Array:
        axis = np.asarray(self.axis, dtype=float)
        length = np.linalg.norm(axis)
        if length < EPSILON:
            raise DegenerateGeometryError("revolve axis has zero length")
        return axis / length

    @property
    def lipschitz(self) -> float:
        return 1.0

    @property
    def envelope(self) -> Box:
        u_lo, u_hi, v_lo, v_hi = self.profile.bounds()
        radius = max(abs(u_lo), abs(u_hi))
        axis = self.unit_axis
        origin = np.asarray(self.origin, dtype=float)
        # Every revolved point is ``origin + t*axis + w``, where ``t`` runs over
        # the profile's ``v`` range and ``w`` is perpendicular to the axis and no
        # longer than the profile's outer radius. The furthest coordinate ``i``
        # such a ``w`` can reach is ``radius*sqrt(1 - axis_i**2)``: being
        # perpendicular to the axis costs exactly the ``axis_i`` share of the
        # radius, and costs nothing when ``axis_i`` is zero.
        #
        # An earlier version instead grew each coordinate by ``radius*(1 -
        # |axis_i|)``, which is smaller than that for any axis with two nonzero
        # components and so is not a bound at all. For the rectangle ``u`` in
        # [0, 10], ``v`` in [-1, 1] revolved about ``(1, 1, 0)/sqrt(2)`` it
        # claimed ``x, y`` in [-3.636, 3.636] while interior points reach
        # +/-7.778, and 44% of sampled interior points landed outside the
        # declared envelope. Since this box seeds the octree in
        # :mod:`forge_geom.measure`, that solid measured 375.7 mm^3 against a
        # true 628.3 mm^3 -- an "enclosure" that did not contain the answer.
        radial = radius * np.sqrt(np.maximum(0.0, 1.0 - axis * axis))
        # min/max rather than the v extremes directly, because a negative
        # ``axis_i`` flips which end of the profile reaches furthest along i.
        axial_lo = np.minimum(axis * v_lo, axis * v_hi)
        axial_hi = np.maximum(axis * v_lo, axis * v_hi)
        return Box(
            tuple((origin + axial_lo - radial).tolist()),  # type: ignore[arg-type]
            tuple((origin + axial_hi + radial).tolist()),  # type: ignore[arg-type]
        )

    def _evaluate(self, points: Array) -> Array:
        axis = self.unit_axis
        origin = np.asarray(self.origin, dtype=float)
        relative = points - origin
        along = relative @ axis
        radial_vector = relative - np.outer(along, axis)
        radius = np.linalg.norm(radial_vector, axis=1)
        field = self.profile.distance(radius, along)

        if self.angle >= 2.0 * math.pi - 1e-9:
            return field

        reference = np.asarray(self.reference, dtype=float)
        reference = reference - axis * (reference @ axis)
        if float(np.linalg.norm(reference)) < EPSILON:
            # A reference along the axis says nothing about where the wedge
            # starts; any perpendicular will do, chosen as `Frame.from_axis`
            # chooses one, so the wedge is the same on every build. The zero
            # vector used to be kept, every point then read as inside the
            # wedge, and a partial revolve about such a reference silently
            # came out as the whole turn.
            helper = np.zeros(3)
            helper[int(np.argmin(np.abs(axis)))] = 1.0
            reference = np.cross(helper, axis)
        reference = reference / max(np.linalg.norm(reference), EPSILON)
        bitangent = np.cross(axis, reference)
        x = radial_vector @ reference
        y = radial_vector @ bitangent
        # The wedge as the signed distance to the two half-planes through the
        # axis that bound it: `theta >= 0` is the half-plane `y >= 0`, at
        # signed distance -y; `theta <= angle` is the half-plane whose edge
        # lies at `angle`, at signed distance y*cos(angle) - x*sin(angle).
        # Up to a half turn the wedge is their intersection (max); past it,
        # the union (min). Both are exact 1-Lipschitz distances to the wedge
        # region, so `max(field, wedge)` is a lower bound on the distance to
        # the revolved solid and the declared Lipschitz constant of 1 holds.
        #
        # It used to be `-radius` inside the wedge and `+radius` outside: not
        # a distance at all, discontinuous across the cut planes (a measured
        # secant slope of 7869 against a declared 1), so the octree decided
        # cells it had no right to decide, and a rectangle revolved through
        # 60 degrees measured [5144.8, 6159.9] mm^3 against a true 6283.2 --
        # an "enclosure" that did not contain the answer.
        distance_a = -y
        distance_b = y * math.cos(self.angle) - x * math.sin(self.angle)
        if self.angle <= math.pi:
            wedge = np.maximum(distance_a, distance_b)
        else:
            wedge = np.minimum(distance_a, distance_b)
        return np.maximum(field, wedge)


@dataclass(frozen=True, slots=True)
class Bend(SDF):
    """A solid bent through ``angle`` about a line, as sheet metal is.

    The solid is taken to run along ``along`` and to be bent towards
    ``toward``: the part of it past the bend zone turns through ``angle``
    (radians, 0 < angle < pi) towards ``toward``, about an axis along
    ``toward x along``. The bend zone is centred on ``position`` and is
    ``radius * angle`` long on the solid's inside face (the face that
    ``toward`` points out of); its middle surface keeps its length, so a
    plate 70 mm long is 70 mm long along its middle after bending. A large
    radius is a smooth arc, a small one a fold.

    Built from three pieces, each a lower bound on the distance to itself,
    and so their minimum is a lower bound on the distance to the bent
    solid: the part before the zone, unmoved; the part after it, rigidly
    turned; and the zone, wrapped round the bend axis. Only the zone is not
    an isometry, and its field is scaled by ``min(1, r / r_mid)`` wherever
    the wrap would stretch it, so the field stays a lower bound everywhere
    and the octree's classification of cells stays sound.
    """

    solid: SDF
    position: tuple[float, float, float]
    along: tuple[float, float, float]
    toward: tuple[float, float, float]
    angle: float
    radius: float
    #: Where the inside face is, along ``toward`` from ``position``, and how
    #: thick the solid is there -- read off the solid's envelope when not
    #: given, and given when the solid is already bent elsewhere, so that a
    #: wing already lifted is not taken for the face.
    face: float | None = None
    thickness: float | None = None
    #: How far, in radians, the whole bent solid is turned back about the
    #: bend axis, with the middle of the bend zone (on the solid's middle
    #: surface) put back where it was flat. 0 keeps the part before the
    #: zone where it was; ``angle / 2`` keeps the middle of the bend level --
    #: a curve centred on a plate then rises, or falls, evenly both ways.
    hold: float = 0.0

    def __post_init__(self) -> None:
        if not (0.0 < self.angle < math.pi):
            raise DegenerateGeometryError(
                "a bend angle must be more than 0 and less than 180 degrees",
                angle_deg=math.degrees(self.angle))
        if self.radius <= 0.0:
            raise DegenerateGeometryError(
                "a bend needs an inside radius greater than zero",
                radius=self.radius)
        self.frame  # noqa: B018 - validates the directions

    # -- the bend's own frame ---------------------------------------------
    @property
    def frame(self) -> tuple[Array, Array, Array]:
        e1 = np.asarray(self.along, dtype=float)
        n1 = float(np.linalg.norm(e1))
        if n1 < EPSILON:
            raise DegenerateGeometryError("a bend's `along` has zero length")
        e1 = e1 / n1
        e3 = np.asarray(self.toward, dtype=float)
        e3 = e3 - e1 * float(e3 @ e1)
        n3 = float(np.linalg.norm(e3))
        if n3 < 1e-9:
            raise DegenerateGeometryError(
                "a bend's `toward` runs along `along`: it must point off the "
                "solid's face, across the way the solid runs")
        e3 = e3 / n3
        e2 = np.cross(e3, e1)
        return e1, e2, e3

    @property
    def layout(self) -> tuple[float, float, float, float]:
        """(inside face, thickness, zone start, middle radius), local."""
        if self.face is not None and self.thickness is not None:
            inside, thickness = float(self.face), float(self.thickness)
        else:
            inside, thickness = self.faces_of(self.solid)
        middle = self.radius + thickness / 2.0
        return inside, thickness, -middle * self.angle / 2.0, middle

    def faces_of(self, solid: SDF) -> tuple[float, float]:
        """The inside face and thickness of a flat solid, in this frame."""
        e1, e2, e3 = self.frame
        envelope = solid.envelope
        corners = np.array([[x, y, z] for x in (envelope.lo[0], envelope.hi[0])
                            for y in (envelope.lo[1], envelope.hi[1])
                            for z in (envelope.lo[2], envelope.hi[2])])
        local = (corners - np.asarray(self.position, dtype=float)) @ e3
        inside, outside = float(local.max()), float(local.min())
        return inside, max(inside - outside, 0.0)

    def _local(self, points: Array) -> tuple[Array, Array, Array]:
        e1, e2, e3 = self.frame
        relative = points - np.asarray(self.position, dtype=float)
        return relative @ e1, relative @ e2, relative @ e3

    def _world(self, x: Array, y: Array, z: Array) -> Array:
        e1, e2, e3 = self.frame
        return (np.asarray(self.position, dtype=float)
                + np.outer(x, e1) + np.outer(y, e2) + np.outer(z, e3))

    # -- the map from the flat solid to the bent one ----------------------
    def _held(self) -> tuple[Array, Array]:
        """The rigid turn back, ``q -> R q + t``, that `hold` applies."""
        if not self.hold:
            return np.eye(3), np.zeros(3)
        inside, thickness, start, middle = self.layout
        flat = self._world(np.array([start + middle * self.angle / 2.0]),
                           np.array([0.0]),
                           np.array([inside - thickness / 2.0]))[0]
        bent = self._unheld_forward(flat[None, :])[0]
        rotation = self.rotation_by(-self.hold)
        return rotation, flat - rotation @ bent

    def forward(self, points: Array) -> Array:
        """Where each point of the unbent solid ends up."""
        moved = self._unheld_forward(points)
        if not self.hold:
            return moved
        rotation, translation = self._held()
        return moved @ rotation.T + translation

    def _unheld_forward(self, points: Array) -> Array:
        points = np.asarray(points, dtype=float).reshape(-1, 3)
        x, y, z = self._local(points)
        inside, _, start, middle = self.layout
        cx, cz = start, inside + self.radius
        theta = self.angle
        out_x, out_z = x.copy(), z.copy()
        zone = (x > start) & (x < start + middle * theta)
        past = x >= start + middle * theta
        phi = (x[zone] - start) / middle
        r = cz - z[zone]
        out_x[zone] = cx + r * np.sin(phi)
        out_z[zone] = cz - r * np.cos(phi)
        a = x[past] - start - middle * theta
        b = z[past] - cz
        out_x[past] = cx + a * math.cos(theta) - b * math.sin(theta)
        out_z[past] = cz + a * math.sin(theta) + b * math.cos(theta)
        return self._world(out_x, y, out_z)

    def turn_at(self, points: Array) -> Array:
        """How far, in radians, the solid has turned at each unbent point."""
        x, _, _ = self._local(np.asarray(points, dtype=float).reshape(-1, 3))
        _, _, start, middle = self.layout
        return np.clip((x - start) / middle, 0.0, self.angle)

    def rotation_by(self, turn: float) -> Array:
        """The world rotation turning through ``turn`` about the bend axis."""
        e1, e2, e3 = self.frame
        c, s = math.cos(turn), math.sin(turn)
        frame = np.column_stack([e1, e2, e3])
        local = np.array([[c, 0.0, -s], [0.0, 1.0, 0.0], [s, 0.0, c]])
        return frame @ local @ frame.T

    # -- field --------------------------------------------------------------
    @property
    def lipschitz(self) -> float:
        return self.solid.lipschitz + 1.0

    @property
    def envelope(self) -> Box:
        unheld = self._unheld_envelope
        if not self.hold or unheld.is_empty:
            return unheld
        rotation, translation = self._held()
        corners = np.array([[x, y, z] for x in (unheld.lo[0], unheld.hi[0])
                            for y in (unheld.lo[1], unheld.hi[1])
                            for z in (unheld.lo[2], unheld.hi[2])])
        moved = corners @ rotation.T + translation
        return Box(tuple(moved.min(axis=0).tolist()),  # type: ignore[arg-type]
                   tuple(moved.max(axis=0).tolist()))  # type: ignore[arg-type]

    @property
    def _unheld_envelope(self) -> Box:
        envelope = self.solid.envelope
        if envelope.is_empty:
            return envelope
        e1, e2, e3 = self.frame
        corners = np.array([[x, y, z] for x in (envelope.lo[0], envelope.hi[0])
                            for y in (envelope.lo[1], envelope.hi[1])
                            for z in (envelope.lo[2], envelope.hi[2])])
        rel = corners - np.asarray(self.position, dtype=float)
        xs, ys, zs = rel @ e1, rel @ e2, rel @ e3
        inside, _, start, middle = self.layout
        steps = np.linspace(float(xs.min()), float(xs.max()), 129)
        steps = np.concatenate([steps, [start, start + middle * self.angle]])
        steps = steps[(steps >= xs.min()) & (steps <= xs.max())]
        grid = np.array([[u, 0.0, w] for u in steps
                         for w in (float(zs.min()), float(zs.max()))])
        moved = self._unheld_forward(
            self._world(grid[:, 0], grid[:, 1], grid[:, 2]))
        rel_moved = moved - np.asarray(self.position, dtype=float)
        mx, mz = rel_moved @ e1, rel_moved @ e3
        reach = float(np.max(np.abs(inside + self.radius - zs))) + 1.0
        margin = reach * (1.0 - math.cos(self.angle / 128.0)) + 1e-6
        lo = (float(mx.min()) - margin, float(ys.min()), float(mz.min()) - margin)
        hi = (float(mx.max()) + margin, float(ys.max()), float(mz.max()) + margin)
        box = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1])
                        for z in (lo[2], hi[2])])
        world = self._world(box[:, 0], box[:, 1], box[:, 2])
        return Box(tuple(world.min(axis=0).tolist()),  # type: ignore[arg-type]
                   tuple(world.max(axis=0).tolist()))  # type: ignore[arg-type]

    def _past(self) -> tuple[Array, Array, Array, float]:
        """The affine map taking a bent point past the zone back to where it
        was, as ``unbent = M q + t``, and ``a = n . q + k``, how far past
        the zone's end a point lies."""
        e1, e2, e3 = self.frame
        inside, _, start, middle = self.layout
        theta = self.angle
        c, s_ = math.cos(theta), math.sin(theta)
        cx, cz = start, inside + self.radius
        position = np.asarray(self.position, dtype=float)
        # a = c*dx + s*dz, b = -s*dx + c*dz, with dx = e1.(q-P) - cx and
        # dz = e3.(q-P) - cz; unbent local x = start + middle*theta + a,
        # y = e2.(q-P), z = cz + b.
        n = c * e1 + s_ * e3
        k = -float(n @ position) - c * cx - s_ * cz
        bn = -s_ * e1 + c * e3
        bk = -float(bn @ position) + s_ * cx - c * cz
        matrix = (np.outer(e1, n) + np.outer(e2, e2) + np.outer(e3, bn))
        translation = (position + e1 * (start + middle * theta + k)
                       - np.outer(e2, e2) @ position + e3 * (cz + bk))
        return matrix, translation, n, k

    def _pieces(self, points: Array) -> tuple[Array, Array, Array]:
        x, y, z = self._local(points)
        inside, _, start, middle = self.layout
        theta = self.angle
        cx, cz = start, inside + self.radius
        dx, dz = x - cx, z - cz
        # Before the zone: the solid as it was, cut at the zone's start.
        before = np.maximum(self.solid(points), dx)
        # Past the zone: turned back through the angle, cut at its end.
        a = dx * math.cos(theta) + dz * math.sin(theta)
        b = -dx * math.sin(theta) + dz * math.cos(theta)
        past = np.maximum(
            self.solid(self._world(start + middle * theta + a, y, cz + b)), -a)
        # The zone: unwrapped from the bend axis, where it lies within it.
        r = np.hypot(dx, dz)
        phi = np.arctan2(dx, -dz)
        in_wedge = (dx >= 0.0) & (a <= 0.0)
        wedge = np.maximum(-dx, a)
        zone = wedge.copy()
        if np.any(in_wedge):
            flat = self._world(start + middle * phi[in_wedge], y[in_wedge],
                               cz - r[in_wedge])
            scale = np.minimum(1.0, r[in_wedge] / middle)
            zone[in_wedge] = np.maximum(scale * self.solid(flat),
                                        wedge[in_wedge])
        # Two more floors under the zone's distance, true everywhere: its
        # material lies between the inside and outside radii, and within the
        # solid's own extent along the bend axis. Without them, outside the
        # wedge the field was only the distance to the wedge -- zero on its
        # two bounding planes, all the way to the bend axis -- and a bent
        # arm plate measured 52240 +/- 17034 mm^3, its bounding box looser
        # still, because every cell those empty planes crossed stayed
        # undecided.
        zone = np.maximum(zone, self._zone_floor(r, y))
        return before, past, zone

    def _zone_floor(self, r: Array, y: Array) -> Array:
        """A lower bound on the distance to the bend zone's material from
        its radius and its place along the bend axis alone."""
        _, e2, _ = self.frame
        envelope = self.solid.envelope
        corners = np.array([[x, yy, z] for x in (envelope.lo[0], envelope.hi[0])
                            for yy in (envelope.lo[1], envelope.hi[1])
                            for z in (envelope.lo[2], envelope.hi[2])])
        relative = corners - np.asarray(self.position, dtype=float)
        along = relative @ e2
        floor = np.maximum(float(along.min()) - y, y - float(along.max()))
        inside, thickness, _, middle = self.layout
        across = relative @ self.frame[2]
        if (float(across.max()) <= inside + 1e-9
                and float(across.min()) >= inside - thickness - 1e-9):
            # The whole solid lies between its inside face and the thickness
            # below it, so the zone holds nothing outside these radii. A
            # solid bent elsewhere already -- a wing lifted -- need not, and
            # gets no such floor.
            floor = np.maximum(floor, np.abs(r - middle) - thickness / 2.0)
        return floor

    def _evaluate(self, points: Array) -> Array:
        if self.hold:
            rotation, translation = self._held()
            points = (np.asarray(points, dtype=float) - translation) @ rotation
        before, past, zone = self._pieces(points)
        return np.minimum(np.minimum(before, past), zone)

    def bounds(self, box: IArray) -> IArray:
        if self.hold:
            # Back through the rigid turn: the cell's hull, turned.
            rotation, translation = self._held()
            lo, hi = box
            centre = ((lo + hi) / 2.0 - translation) @ rotation
            half = ((hi - lo) / 2.0) @ np.abs(rotation)
            box = (centre - half, centre + half)
        return self._unheld_bounds(box)

    def _unheld_bounds(self, box: IArray) -> IArray:
        # Before and past the zone the map is rigid, so each is bounded by
        # the solid's own interval over the (hulled) cell, cut by an exact
        # linear interval. The zone's field is a lower bound on distance,
        # which is all classification needs: a value beyond the cell's
        # radius proves the cell clear of it, or wholly inside it.
        e1, _, _ = self.frame
        _, _, start, _ = self.layout
        lo, hi = box
        centre = (lo + hi) / 2.0
        half = (hi - lo) / 2.0
        position = np.asarray(self.position, dtype=float)
        dx = ib.iadd_scalar(ib.idot_constant(box, e1),
                            -float(e1 @ position) - start)
        before = ib.imax(self.solid.bounds(box), dx)
        matrix, translation, n, k = self._past()
        moved_centre = centre @ matrix.T + translation
        moved_half = half @ np.abs(matrix).T
        a = ib.iadd_scalar(ib.idot_constant(box, n), k)
        past = ib.imax(self.solid.bounds((moved_centre - moved_half,
                                          moved_centre + moved_half)),
                       ib.ineg(a))
        _, _, zone = self._pieces(centre)
        radius = np.linalg.norm(half, axis=1)
        zone_iv = (np.maximum(zone - radius, self._zone_floor_over(box)),
                   zone + radius)
        return ib.imin(ib.imin(before, past), zone_iv)

    def _zone_floor_over(self, box: IArray) -> Array:
        """The zone's floors -- the wedge it lies in, its radii, its run
        along the bend axis -- bounded over a whole cell. Each is linear or
        nearly so in the point, so its interval is close to exact, and a slab
        beside a bent part's face is proved empty in one step instead of by
        cells smaller than its distance from the face."""
        e1, e2, e3 = self.frame
        inside, thickness, start, middle = self.layout
        theta = self.angle
        position = np.asarray(self.position, dtype=float)
        cx, cz = start, inside + self.radius
        dx = ib.iadd_scalar(ib.idot_constant(box, e1),
                            -float(e1 @ position) - cx)
        dz = ib.iadd_scalar(ib.idot_constant(box, e3),
                            -float(e3 @ position) - cz)
        y = ib.iadd_scalar(ib.idot_constant(box, e2), -float(e2 @ position))
        a = ib.iadd(ib.iscale(dx, math.cos(theta)), ib.iscale(dz, math.sin(theta)))
        # The wedge field max(-dx, a): its floor is the larger floor.
        floor = np.maximum(-dx[1], a[0])
        envelope = self.solid.envelope
        corners = np.array([[x, yy, z] for x in (envelope.lo[0], envelope.hi[0])
                            for yy in (envelope.lo[1], envelope.hi[1])
                            for z in (envelope.lo[2], envelope.hi[2])])
        relative = corners - position
        along = relative @ e2
        floor = np.maximum(floor, np.maximum(float(along.min()) - y[1],
                                             y[0] - float(along.max())))
        across = relative @ e3
        if (float(across.max()) <= inside + 1e-9
                and float(across.min()) >= inside - thickness - 1e-9):
            r_lo = np.sqrt(ib.iabs(dx)[0] ** 2 + ib.iabs(dz)[0] ** 2)
            r_hi = np.sqrt(ib.iabs(dx)[1] ** 2 + ib.iabs(dz)[1] ** 2)
            off = np.where((r_lo <= middle) & (r_hi >= middle), 0.0,
                           np.minimum(np.abs(r_lo - middle),
                                      np.abs(r_hi - middle)))
            floor = np.maximum(floor, off - thickness / 2.0)
        return floor


#: Fields that are the exact distance to their solid, so never nearer than
#: their envelope: what `Difference` may skip outside of.
_EXACT_FIELDS = (BoxSDF, SphereSDF, CylinderSDF)


__all__ = [
    "SDF",
    "Box",
    "BoxSDF",
    "SphereSDF",
    "CylinderSDF",
    "ConeSDF",
    "TorusSDF",
    "HalfSpaceSDF",
    "ExtrusionSDF",
    "Revolve",
    "Profile2D",
    "RectangleProfile",
    "CircleProfile",
    "SlotProfile",
    "PolygonProfile",
    "Union",
    "Intersection",
    "Difference",
    "Shell",
    "Offset",
    "Transform",
    "Repeat",
    "Mirror",
    "Bend",
    "GeometryError",
    "DegenerateGeometryError",
    "EmptyResultError",
]
