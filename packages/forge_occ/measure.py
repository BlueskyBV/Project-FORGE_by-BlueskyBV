"""Exact measurement beyond the view's questions: a part's mass properties, and points' distances from one face's surface (docs/V2-stage3.md, section 11).

- :func:`volume_interval`: OpenCascade's volume integral at 1e-12, as an
  interval of ±1e-6 relative (the bound a test holds on analytic solids,
  with a margin of five).
- :func:`properties`: volume, area, centre of mass and box, together, for
  comparing a part with itself read back from a file.
- :func:`surface_distance`: how far points are from a face's surface (the
  whole surface, not trimmed to the face): exactly, and vectorised, for
  planes, cylinders, cones, spheres and tori; by OpenCascade's projection
  for any other. For measuring how far a mesh made of the face strays from
  it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from forge_numeric import vector as fv
from forge_units import Interval
from numpy.typing import NDArray
from OCP.Bnd import Bnd_Box
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepGProp import BRepGProp
from OCP.GeomAbs import (
    GeomAbs_Cone,
    GeomAbs_Cylinder,
    GeomAbs_Plane,
    GeomAbs_Sphere,
    GeomAbs_Torus,
)
from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
from OCP.gp import gp_Pnt
from OCP.GProp import GProp_GProps

from .occt import INTEGRATION, boundary, box_limits

__all__ = [
    "VOLUME_RELATIVE",
    "Properties",
    "properties",
    "surface_distance",
    "volume_interval",
]

Array = NDArray[np.float64]

#: The volume's interval, relative: OpenCascade's integral (at :data:`~forge_occ.occt.INTEGRATION`) is tested to be within a fifth of this on analytic solids made rational B-splines.
VOLUME_RELATIVE = 1e-6


def _signed_volume(shape: Any) -> float:
    props = GProp_GProps()
    with boundary("measuring a volume"):
        BRepGProp.VolumeProperties_s(shape, props, INTEGRATION, False)
    return float(props.Mass())


def volume_interval(shape: Any) -> Interval:
    """The shape's volume (mm³), as an interval sure to hold it."""
    v = _signed_volume(shape)
    slack = VOLUME_RELATIVE * abs(v)
    return Interval(v - slack, v + slack)


@dataclass(frozen=True)
class Properties:
    volume: float
    area: float
    centre: tuple[float, float, float]
    lo: tuple[float, float, float]
    hi: tuple[float, float, float]

    def differences(self, other: Properties) -> dict[str, float]:
        """How far ``other`` is from this, each relative to this part's size (volume to volume, area to area, lengths to the box's diagonal)."""
        size = float(fv.norm(np.subtract(self.hi, self.lo))) or 1.0
        return {
            "volume": abs(other.volume - self.volume) / max(abs(self.volume), 1e-300),
            "area": abs(other.area - self.area) / max(abs(self.area), 1e-300),
            "centre": float(fv.norm(np.subtract(other.centre, self.centre))) / size,
            "box": float(
                max(
                    np.abs(np.subtract(other.lo, self.lo)).max(),
                    np.abs(np.subtract(other.hi, self.hi)).max(),
                )
            )
            / size,
        }


def properties(shape: Any) -> Properties:
    volume = GProp_GProps()
    area = GProp_GProps()
    box = Bnd_Box()
    with boundary("measuring a part"):
        BRepGProp.VolumeProperties_s(shape, volume, INTEGRATION, False)
        BRepGProp.SurfaceProperties_s(shape, area, INTEGRATION, False)
        BRepBndLib.AddOptimal_s(shape, box, False, False)
    c = volume.CentreOfMass()
    x0, y0, z0, x1, y1, z1 = box_limits(box)
    return Properties(
        float(volume.Mass()),
        float(area.Mass()),
        (c.X(), c.Y(), c.Z()),
        (x0, y0, z0),
        (x1, y1, z1),
    )


def _xyz(p: Any) -> Array:
    return np.array([p.X(), p.Y(), p.Z()], dtype=np.float64)


def _axial(points: Array, origin: Array, axis: Array) -> tuple[Array, Array]:
    """Each point's height along the axis and its distance from it."""
    rel = points - origin
    height = fv.matmul(rel, axis)
    radial = fv.norm(rel - np.outer(height, axis), axis=1)
    return height, radial


def surface_distance(face: Any, points: Array) -> Array:
    """Each point's distance from the face's surface (untrimmed)."""
    points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    surface = BRepAdaptor_Surface(face, False)
    kind = surface.GetType()
    if kind == GeomAbs_Plane:
        plane = surface.Plane()
        n = _xyz(plane.Axis().Direction())
        return np.asarray(np.abs(fv.matmul(points - _xyz(plane.Location()), n)))
    if kind == GeomAbs_Cylinder:
        cylinder = surface.Cylinder()
        _, radial = _axial(
            points, _xyz(cylinder.Location()), _xyz(cylinder.Axis().Direction())
        )
        return np.asarray(np.abs(radial - cylinder.Radius()))
    if kind == GeomAbs_Sphere:
        sphere = surface.Sphere()
        return np.asarray(
            np.abs(fv.norm(points - _xyz(sphere.Location()), axis=1) - sphere.Radius())
        )
    if kind == GeomAbs_Torus:
        torus = surface.Torus()
        height, radial = _axial(
            points, _xyz(torus.Location()), _xyz(torus.Axis().Direction())
        )
        return np.asarray(
            np.abs(fv.hypot(radial - torus.MajorRadius(), height) - torus.MinorRadius())
        )
    if kind == GeomAbs_Cone:
        cone = surface.Cone()
        # In the half-plane through the axis and the point, the cone is two half-lines from the
        # apex, (±cos a, |sin a|) in (height, distance from the axis); a point is its distance
        # from the nearer, or from the apex where its foot would fall past it.
        apex, axis = _xyz(cone.Apex()), _xyz(cone.Axis().Direction())
        height, radial = _axial(points, apex, axis)
        a = cone.SemiAngle()
        q = np.stack([height, radial], axis=1)
        to_apex = fv.norm(q, axis=1)
        best = to_apex
        for line in (
            np.array([fv.cos(a), abs(fv.sin(a))]),
            np.array([-fv.cos(a), abs(fv.sin(a))]),
        ):
            t = fv.matmul(q, line)
            best = np.minimum(
                best,
                np.where(t >= 0.0, fv.norm(q - np.outer(t, line), axis=1), to_apex),
            )
        return np.asarray(best)
    geometry = BRep_Tool.Surface_s(face)
    out = np.empty(len(points))
    with boundary("projecting points on a surface"):
        for k, p in enumerate(points):
            projection = GeomAPI_ProjectPointOnSurf(gp_Pnt(*map(float, p)), geometry)
            out[k] = projection.LowerDistance() if projection.NbPoints() else np.inf
    return out
