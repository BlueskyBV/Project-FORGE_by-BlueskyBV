"""Frames, points, directions and rigid motions, between NumPy and OpenCascade.

The conventions are V1's, read as definitions (docs/V2-stage3.md, 7.2):

- a frame built from an axis alone takes for its x axis the cross product of
  the world axis least parallel to it (the first, of equals) with the axis,
  and y = z cross x (:meth:`Frame.from_axis`);
- the standard planes are XY (normal +z), YZ (normal +x, its u along y), XZ
  (normal -y, so that x and z stay a right-handed pair), each offset along
  the axis it isn't in: XZ's along +y;
- a rotation turns by the right hand about its axis (Rodrigues).

>>> Frame.from_axis((0, 0, 0), (0, 0, 1)).x
(0.0, -1.0, 0.0)
>>> Frame.standard("XZ", 5.0).origin, Frame.standard("XZ", 5.0).z
((0.0, 5.0, 0.0), (0.0, -1.0, 0.0))
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.gp import gp_Ax1, gp_Ax2, gp_Ax3, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec
from OCP.TopoDS import TopoDS_Shape

from .errors import DesignError
from .occt import boundary

__all__ = [
    "Frame",
    "Motion",
    "Vec3",
    "Vector",
    "rotation_about",
    "unit",
]

Vec3 = tuple[float, float, float]
Array = NDArray[np.float64]
#: Three numbers, as a sequence or an array: what every function here takes for a point or a direction.
Vector = Sequence[float] | NDArray[np.floating[Any]]

#: Below this a direction has no length (mm, or a unit vector's length).
NO_LENGTH = 1e-12


def unit(vector: Vector, what: str = "a direction") -> Array:
    """``vector`` made unit; a vector with no length is a :class:`DesignError`."""
    v = np.asarray(vector, dtype=np.float64)
    if v.shape != (3,) or not np.isfinite(v).all():
        raise DesignError(
            f"{what} must be three finite numbers", value=list(map(float, v.ravel()))
        )
    length = float(np.linalg.norm(v))
    if length < NO_LENGTH:
        raise DesignError(f"{what} has no length", value=v.tolist())
    return v / length


def _tuple(v: NDArray[np.floating[Any]]) -> Vec3:
    return float(v[0]), float(v[1]), float(v[2])


def rotation_about(axis: Vector, angle: float) -> Array:
    """The rotation by ``angle`` (radians, right hand) about the unit ``axis`` (Rodrigues)."""
    x, y, z = (float(c) for c in unit(axis, "a rotation's axis"))
    cross = np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])
    return np.asarray(
        np.eye(3) + math.sin(angle) * cross + (1.0 - math.cos(angle)) * (cross @ cross),
        dtype=np.float64,
    )


@dataclass(frozen=True)
class Frame:
    """A right-handed frame: an origin and three unit axes, in mm."""

    origin: Vec3
    x: Vec3 = (1.0, 0.0, 0.0)
    y: Vec3 = (0.0, 1.0, 0.0)
    z: Vec3 = (0.0, 0.0, 1.0)

    @classmethod
    def through(cls, origin: Vector, x: Vector, y: Vector, z: Vector) -> Frame:
        """The frame of these origin and axes, given as sequences or arrays."""
        return cls(
            *(_tuple(np.asarray(v, dtype=np.float64)) for v in (origin, x, y, z))
        )

    @classmethod
    def from_axis(cls, origin: Vector, axis: Vector) -> Frame:
        """The frame whose z is ``axis``, its x from the world axis least parallel to it."""
        z = unit(axis, "an axis")
        helper = np.zeros(3)
        helper[int(np.argmin(np.abs(z)))] = 1.0
        x = np.cross(helper, z)
        x = x / np.linalg.norm(x)
        y = np.cross(z, x)
        o = np.asarray(origin, dtype=np.float64)
        return cls(_tuple(o), _tuple(x), _tuple(y), _tuple(z))

    @classmethod
    def standard(cls, base: str, offset: float = 0.0) -> Frame:
        """XY, YZ or XZ, moved by ``offset`` along the axis it isn't in (XZ's: +y)."""
        planes: dict[str, tuple[Vec3, Vec3, Vec3, Vec3]] = {
            "XY": ((0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
            "YZ": ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 0.0)),
            "XZ": ((0.0, 1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, -1.0, 0.0)),
        }
        if base not in planes:
            raise DesignError("a standard plane is XY, YZ or XZ", base=base)
        along, x, y, z = planes[base]
        origin = (along[0] * offset, along[1] * offset, along[2] * offset)
        return cls(origin, x, y, z)

    @property
    def matrix(self) -> Array:
        """Columns x, y, z: local to world directions."""
        return np.array([self.x, self.y, self.z], dtype=np.float64).T

    def at(self, u: float, v: float, w: float = 0.0) -> Array:
        """The world point at local (u, v, w)."""
        return np.asarray(self.origin, dtype=np.float64) + self.matrix @ np.array(
            [u, v, w], dtype=np.float64
        )

    def moved(self, by: Vector) -> Frame:
        o = np.asarray(self.origin, dtype=np.float64) + np.asarray(by, dtype=np.float64)
        return Frame(_tuple(o), self.x, self.y, self.z)

    def ax3(self) -> gp_Ax3:
        return gp_Ax3(gp_Pnt(*self.origin), gp_Dir(*self.z), gp_Dir(*self.x))

    def ax2(self) -> gp_Ax2:
        return gp_Ax2(gp_Pnt(*self.origin), gp_Dir(*self.z), gp_Dir(*self.x))


@dataclass(frozen=True)
class Motion:
    """A rigid motion (or a reflection): ``p ↦ rotation @ p + translation``."""

    rotation: tuple[float, ...]  # row-major, 3 by 3
    translation: Vec3 = (0.0, 0.0, 0.0)

    @classmethod
    def of(cls, rotation: Array, translation: Vector = (0.0, 0.0, 0.0)) -> Motion:
        r = np.asarray(rotation, dtype=np.float64)
        if r.shape != (3, 3) or abs(abs(np.linalg.det(r)) - 1.0) > 1e-9:
            raise DesignError("a motion's matrix must be a rotation or a reflection")
        if not np.allclose(r @ r.T, np.eye(3), atol=1e-9):
            raise DesignError("a motion's matrix must be orthogonal")
        t = np.asarray(translation, dtype=np.float64)
        return cls(tuple(float(c) for c in r.ravel()), _tuple(t))

    @classmethod
    def identity(cls) -> Motion:
        return cls.of(np.eye(3))

    @property
    def matrix(self) -> Array:
        return np.asarray(self.rotation, dtype=np.float64).reshape(3, 3)

    @property
    def reflects(self) -> bool:
        return bool(np.linalg.det(self.matrix) < 0.0)

    def then(self, other: Motion) -> Motion:
        """This motion, then ``other``."""
        m = other.matrix @ self.matrix
        t = other.matrix @ np.asarray(self.translation) + np.asarray(other.translation)
        return Motion.of(m, t)

    def point(self, p: Vector) -> Array:
        return np.asarray(
            self.matrix @ np.asarray(p, dtype=np.float64) + np.asarray(self.translation)
        )

    def direction(self, d: Vector) -> Array:
        return np.asarray(self.matrix @ np.asarray(d, dtype=np.float64))

    def trsf(self) -> gp_Trsf:
        """The motion as OpenCascade's ``gp_Trsf`` (a reflection is the reflection's own form)."""
        m, t = self.matrix, self.translation
        trsf = gp_Trsf()
        with boundary("making a motion"):
            if self.reflects:
                # gp_Trsf takes only rotations in SetValues; a reflection is a
                # mirror about the plane whose normal the matrix negates, then the rest.
                eigen, vectors = np.linalg.eigh((m + m.T) / 2.0)
                normal = vectors[:, int(np.argmin(eigen))]
                mirror = gp_Trsf()
                mirror.SetMirror(gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(*normal)))
                rest = m @ (np.eye(3) - 2.0 * np.outer(normal, normal))
                rotation = gp_Trsf()
                rotation.SetValues(
                    rest[0, 0], rest[0, 1], rest[0, 2], t[0],
                    rest[1, 0], rest[1, 1], rest[1, 2], t[1],
                    rest[2, 0], rest[2, 1], rest[2, 2], t[2],
                )  # fmt: skip
                trsf = rotation.Multiplied(mirror)
            else:
                trsf.SetValues(
                    m[0, 0], m[0, 1], m[0, 2], t[0],
                    m[1, 0], m[1, 1], m[1, 2], t[1],
                    m[2, 0], m[2, 1], m[2, 2], t[2],
                )  # fmt: skip
        return trsf

    def apply(self, shape: TopoDS_Shape) -> TopoDS_Shape:
        """A moved copy of ``shape`` (its geometry copied, so nothing is shared)."""
        with boundary("moving a shape"):
            maker = BRepBuilderAPI_Transform(shape, self.trsf(), True)
            return maker.Shape()


def ax1(origin: Vector, direction: Vector) -> gp_Ax1:
    return gp_Ax1(gp_Pnt(*map(float, origin)), gp_Dir(*unit(direction)))


def vec(v: Vector) -> gp_Vec:
    return gp_Vec(*map(float, v))


def pnt(p: Vector) -> gp_Pnt:
    return gp_Pnt(*map(float, p))
