"""The ``diameter`` kind: a circle fitted to a round surface the spec asks for (bores, bosses, rods, counterbores).

**Measures** the diameter of the built surface near the spec's round
surface ``target`` (:mod:`forge_checks.kinds.surfaces`): its points within the window (the tolerance band, both
ways, and the view's deflection twice) of the spec's radius, between the
surface's ends less a margin, facing the spec surface's way, where the spec
has that surface. A circle is fitted to them across the spec's axis.

**Tolerance policy:** a linear size: the value's own tolerance, or ISO
2768-m by the nominal diameter (docs/definitions/sizes.md).

**Uncertainty:** the circle fit's, doubled: the view's deflection on a
full circle, more on an arc (a hole broken by an edge).

**Mutants and near-misses** (:func:`mutants`): the diameter at each limit
of the tolerance, ``2u`` outside (it must fail) and ``2u`` inside (it must
pass), ``u`` the uncertainty on the correct part.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..classes import Tolerance, bracket_mutants
from ..measure import Measurement, Probe
from .surfaces import (
    Ball,
    Cone,
    Round,
    fitted_ball,
    fitted_cone,
    fitted_round,
    width_for,
)

__all__ = ["Across", "measure", "mutants"]


@dataclass(frozen=True)
class Across:
    """A cone's diameter ``at`` a place along its axis (a cone body's base or top)."""

    cone: Cone
    at: float


def measure(
    target: Round | Cone | Across | Ball,
    nominal: float,
    tolerance: Tolerance,
    probe: Probe,
) -> Measurement:
    """The diameter of a round surface or a ball; of a cone where it meets the face it is cut into (its first end), or where ``Across`` says."""
    width = width_for(tolerance, float(probe.deflection.max(initial=0.0)))
    if isinstance(target, Ball):
        ball = fitted_ball(target, width, probe)
        if isinstance(ball, str):
            return Measurement(None, 0, ball, missing=ball.startswith("no built"))
        return Measurement.of(2 * ball.fit.radius, 2 * ball.fit.u_radius, ball.found,
                              f"a sphere fitted to {ball.found} built points, worst {ball.fit.worst:.2g} mm off it")  # fmt: skip
    if isinstance(target, Cone | Across):
        cone_target, at = (
            (target, target.ends[0])
            if isinstance(target, Cone)
            else (target.cone, target.at)
        )
        cone = fitted_cone(cone_target, width, probe)
        if isinstance(cone, str):
            return Measurement(None, 0, cone, missing=cone.startswith("no built"))
        radius, u = cone.fit.radius_at(at)
        return Measurement.of(2 * radius, 2 * u, cone.found,
                              f"a cone fitted to {cone.found} built points, worst {cone.fit.worst:.2g} mm off it")  # fmt: skip
    found = fitted_round(target, width, probe)
    if isinstance(found, str):
        return Measurement(None, 0, found, missing=found.startswith("no built"))
    return Measurement.of(
        2 * found.fit.radius,
        2 * found.fit.u_radius,
        found.found,
        f"a circle fitted to {found.found} built points, worst {found.fit.worst:.2g} mm off it",
    )


#: The value at each limit of the tolerance, ``2u`` inside (it must pass) and outside (it must fail).
mutants = bracket_mutants
