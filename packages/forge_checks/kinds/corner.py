"""The ``corner`` kind: the radius of a rounded corner seen along a face's normal (a pocket's corners, a slot's or a tab's round end).

**Measures** a circle fitted, across the corner's axis, to the built
points near the spec's round surface there, as the ``diameter`` kind does,
but over the corner's arc only (a quarter of a circle, or half for a round
end): its radius.

**Tolerance policy:** a radius: the value's own tolerance, or ISO 2768-m's
radii column by the nominal radius (docs/definitions/sizes.md).

**Uncertainty:** the fit's on that arc: several times the view's deflection
on a quarter circle (the centre is less fixed than on a whole one).

**Mutants and near-misses:** the radius at each limit of the tolerance,
``2u`` outside (it must fail) and ``2u`` inside (it must pass).
"""

from __future__ import annotations

from ..classes import Tolerance, bracket_mutants
from ..measure import Measurement, Probe
from .surfaces import Round, fitted_round, width_for

__all__ = ["measure", "mutants"]


def measure(
    target: Round, nominal: float, tolerance: Tolerance, probe: Probe
) -> Measurement:
    width = width_for(tolerance, float(probe.deflection.max(initial=0.0)))
    found = fitted_round(target, width, probe)
    if isinstance(found, str):
        return Measurement(None, 0, found, missing=found.startswith("no built"))
    return Measurement.of(
        found.fit.radius,
        found.fit.u_radius,
        found.found,
        f"an arc fitted to {found.found} built points, worst {found.fit.worst:.2g} mm off it",
    )


#: The radius at each limit of the tolerance, ``2u`` inside (it must pass) and outside (it must fail).
mutants = bracket_mutants
