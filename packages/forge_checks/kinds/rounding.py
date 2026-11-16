"""The ``rounding`` kind: a fillet's radius or a chamfer's size, measured across its edge.

**A fillet along a straight edge** (:class:`~forge_checks.kinds.surfaces.Round`,
its axis along the edge): an arc fitted across it, its radius.
**Round a round edge** (:class:`~forge_checks.kinds.surfaces.Tube`): an arc
fitted in the half-plane round the body's axis, its radius.

**A chamfer of a straight edge** (:class:`Bevel`): the bevel's fitted
plane; how far it is from where the spec's is gives each leg, along each
face from the edge. **Round a round edge** (:class:`RoundBevel`): the
bevel's fitted cone; where its side crosses each face's line from the
edge, in the half-plane round the axis, gives each leg. Each
leg must be within the tolerance, so the measurement is both at once.

**Tolerance policy:** a radius or a chamfer height: its own tolerance, or
ISO 2768-m's radii column by the nominal (docs/definitions/sizes.md).

**Uncertainty:** the arc's fit (several times the view's deflection on a
quarter circle); a bevel's offset, as each leg.

**Mutants and near-misses:** the radius or size at each limit of the
tolerance, ``2u`` outside (it must fail) and ``2u`` inside (it must pass).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from forge_numeric import vector as fv

from ..classes import Tolerance, bracket_mutants
from ..measure import FEWEST, Measurement, Probe
from .surfaces import (
    Cone,
    Plane,
    Round,
    Tube,
    fitted_cone,
    fitted_round,
    fitted_tube,
    plane_offset,
    width_for,
)

__all__ = ["Bevel", "RoundBevel", "measure", "mutants"]

Vec = tuple[float, float, float]


@dataclass(frozen=True)
class Bevel:
    """A flat chamfer: its plane (facing out of the material), and each face's way from the edge across it (``legs``)."""

    plane: Plane
    legs: tuple[Vec, Vec]


@dataclass(frozen=True)
class RoundBevel:
    """A chamfer round a round edge: its cone; the edge's ``corner`` in the half-plane round the cone's axis (distance from it, height along it from the cone's centre); and each face's way from the corner (``legs``, unit, in that half-plane)."""

    cone: Cone
    corner: tuple[float, float]
    legs: tuple[tuple[float, float], tuple[float, float]]


def measure(
    target: Round | Tube | Bevel | RoundBevel,
    nominal: float,
    tolerance: Tolerance,
    probe: Probe,
) -> Measurement:
    width = width_for(tolerance, float(probe.deflection.max(initial=0.0)))
    if isinstance(target, Round | Tube):
        found = (
            fitted_round(target, width, probe)
            if isinstance(target, Round)
            else fitted_tube(target, width, probe)
        )
        if isinstance(found, str):
            return Measurement(None, 0, found, missing=found.startswith("no built"))
        return Measurement.of(found.fit.radius, found.fit.u_radius, found.found,
                              f"an arc fitted to {found.found} built points, worst {found.fit.worst:.2g} mm off it")  # fmt: skip
    if isinstance(target, Bevel):
        window, offset, u = plane_offset(target.plane, width, probe)
        if len(window) < FEWEST:
            return Measurement(
                None, len(window), f"no built bevel within {width:.3g} mm of the spec's"
            )
        m = np.asarray(target.plane.normal, dtype=np.float64)
        m /= float(fv.norm(m))
        legs = []
        for way in target.legs:
            v = np.asarray(way, dtype=np.float64)
            v /= float(fv.norm(v))
            # How far the bevel's offset moves along the face, per unit: one way on an outside edge, the other
            # on an inside one (its plane faces into the corner's air); how far a leg may be off, either way.
            slope = -float(fv.matmul(v, m))
            legs.append((nominal - offset / slope, u / abs(slope)))
        return _both(legs, len(window), "the bevel's plane fitted")
    cone = fitted_cone(target.cone, width, probe)
    if isinstance(cone, str):
        return Measurement(None, 0, cone, missing=cone.startswith("no built"))
    fit = cone.fit
    k_rho, k_z = target.corner
    legs = []
    for d_rho, d_z in target.legs:
        # Where the fitted cone's side crosses the face's line from the corner: t along it, the radius
        # read where it crosses (radius_at, near the bevel's points, where it is known best).
        across = d_rho - fit.b * d_z
        if abs(across) < 1e-9:
            return Measurement(
                None, cone.found, "the built bevel runs along a face", missing=False
            )
        rho, _ = fit.radius_at(k_z)
        t = (rho - k_rho) / across
        _, u = fit.radius_at(k_z + t * d_z)
        legs.append((t, u / abs(across)))
    return _both(legs, cone.found, "the bevel's cone fitted")


def _both(legs: list[tuple[float, float]], found: int, how: str) -> Measurement:
    lo = min(value - u for value, u in legs)
    hi = max(value + u for value, u in legs)
    if not (math.isfinite(lo) and math.isfinite(hi)):
        return Measurement(
            None, found, f"{how}, but its legs can't be worked out", missing=False
        )
    return Measurement.of(
        (lo + hi) / 2, (hi - lo) / 2, found, f"{how} to {found} built points: both legs"
    )


#: The radius or size at each limit of the tolerance, ``2u`` inside (it must pass) and outside (it must fail).
mutants = bracket_mutants
