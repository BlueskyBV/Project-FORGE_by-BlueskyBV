"""``ImplicitView``: the implicit kernel's own view of what it built (docs/V2-stage3.md, 13.1).

| Question | How |
|---|---|
| ``classify`` | the sign of the field: exact for the implicit shape; ON where the field is within 1e-9 |
| ``volume`` | V1's rigorous measurement: an interval sure to hold the implicit shape's volume |
| ``bounds`` | the field's refined extents: a box sure to hold it |
| ``distance``, ``crossings``, ``coverage``, ``topology`` | a mesh of the field (V1's own extraction), answered by the stage-2 mesh view, with the mesh's measured distance from the field as its deflection |

And, for the second-kernel agreement, :meth:`ImplicitView.surface`: points
on the field's zero set, each with its outward normal (the field's gradient),
from V1's own surface sampling.
"""

from __future__ import annotations

from functools import cached_property

import numpy as np
from forge_checks.mesh import Mesh, MeshView
from forge_checks.view import Box, Capability, Coverage, Crossings, Side, Topology
from forge_geom import (
    SDF,
    extract_manifold_surface,
    measure_mass_properties,
    refine_extents,
    surface_samples,
)
from forge_units import Interval
from numpy.typing import NDArray

__all__ = ["ON", "ImplicitView"]

Array = NDArray[np.float64]

#: A point where the field is this close to zero is on the implicit surface.
ON = 1e-9


class ImplicitView:
    """The implicit kernel's part, as the checks may see it."""

    capabilities = frozenset({Capability.CLASSIFY, Capability.VOLUME, Capability.DISTANCE, Capability.CROSSINGS,
                              Capability.COVERAGE, Capability.TOPOLOGY})  # fmt: skip
    source = "implicit"

    def __init__(self, solid: SDF, *, resolution: int = 96) -> None:
        self.solid = solid
        self.resolution = int(resolution)

    # --- the field itself ---------------------------------------------------------------
    def field(self, points: Array) -> Array:
        return np.asarray(
            self.solid(np.asarray(points, dtype=np.float64).reshape(-1, 3)),
            dtype=np.float64,
        )

    def classify(self, points: Array) -> NDArray[np.int8]:
        f = self.field(points)
        sides = np.full(len(f), Side.UNKNOWN, dtype=np.int8)
        sides[f < -ON] = Side.IN
        sides[f > ON] = Side.OUT
        sides[np.abs(f) <= ON] = Side.ON
        return sides

    @cached_property
    def _measured(self) -> object:
        return measure_mass_properties(self.solid)

    def volume(self) -> Interval:
        found = self._measured.volume.magnitude  # type: ignore[attr-defined]
        return Interval(float(found.lo), float(found.hi))

    def bounds(self) -> Box:
        return self._bounds

    @cached_property
    def _bounds(self) -> Box:
        refined = refine_extents(self.solid, self._measured)  # type: ignore[arg-type]
        lo = tuple(float(q.magnitude.lo) for q in refined.bounding_box_lo)
        hi = tuple(float(q.magnitude.hi) for q in refined.bounding_box_hi)
        return Box(lo, hi)  # type: ignore[arg-type]

    def surface(self, *, resolution: int | None = None) -> tuple[Array, Array]:
        """Points on the field's zero set (V1's sampling, projected onto it), and the unit outward normal at each."""
        points = np.asarray(
            surface_samples(self.solid, resolution=resolution or self.resolution),
            dtype=np.float64,
        )
        if not len(points):
            return points.reshape(0, 3), points.reshape(0, 3)
        gradient = self.solid.gradient(points)
        length = np.linalg.norm(gradient, axis=1)
        keep = length > 1e-9
        return points[keep], gradient[keep] / length[keep, None]

    # --- from a mesh of the field --------------------------------------------------------
    @cached_property
    def mesh_view(self) -> MeshView:
        extracted = extract_manifold_surface(self.solid, resolution=self.resolution)
        mesh = Mesh(
            np.asarray(extracted.vertices, dtype=np.float64),
            np.asarray(extracted.faces, dtype=np.int64),
        )
        corners = mesh.vertices[mesh.faces]
        samples = np.concatenate([mesh.vertices, corners.mean(axis=1), (corners[:, 0] + corners[:, 1]) / 2.0,
                                  (corners[:, 1] + corners[:, 2]) / 2.0, (corners[:, 2] + corners[:, 0]) / 2.0])  # fmt: skip
        # Near its surface the field is a distance: its size there is how far the mesh strays.
        deflection = float(np.abs(self.field(samples)).max()) if len(samples) else 0.0
        return MeshView(mesh, source=self.source, deflection=deflection)

    def distance(self, points: Array) -> Array:
        return self.mesh_view.distance(points)

    def crossings(self, origins: Array, directions: Array) -> Crossings:
        return self.mesh_view.crossings(origins, directions)

    def coverage(self, radius: float, within: Box | None = None) -> Coverage:
        return self.mesh_view.coverage(radius, within)

    def topology(self) -> Topology:
        return self.mesh_view.topology()
