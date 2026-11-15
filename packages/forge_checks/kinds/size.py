"""The ``size`` kind: the distance between two fitted planes the spec asks for (lengths, widths, heights, thicknesses).

**Measures** each plane's built position: the built points within the
window (the tolerance band and the view's deflection twice) of the spec's
plane, facing its way, where the spec has that face (and, for a face that
is a small part of a larger plane, a floor or a boss's top, within ``reach``
of the spec's point). The plane's offset is their mean distance along its
normal. The size is the distance between the two built planes along
``along``: for a block's length, from its -x face to its +x face along +x.

**Tolerance policy:** a linear size: the value's own tolerance, or ISO
2768-m by the nominal (docs/definitions/sizes.md).

**Uncertainty:** each plane's offset is off by at most its points' mean
deflection; the size, by the two together.

A size between two things that aren't planes (a round-ended slot's
length, from one end's fitted arc to the other's) is measured as the
``position`` kind measures, from one to the other.

**Mutants and near-misses** (:func:`mutants`): the size at each limit of
the tolerance, ``2u`` outside (it must fail) and ``2u`` inside (it must
pass).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..classes import Tolerance, bracket_mutants
from ..measure import FEWEST, Measurement, Probe
from .position import Position
from .position import measure as measure_position
from .surfaces import Plane, plane_offset, width_for

__all__ = ["Between", "measure", "mutants"]

Vec = tuple[float, float, float]


@dataclass(frozen=True)
class Between:
    """The distance from plane ``b`` to plane ``a`` along ``along``: ``(a - b) . along``."""

    a: Plane
    b: Plane
    along: Vec


def measure(
    target: Between | Position, nominal: float, tolerance: Tolerance, probe: Probe
) -> Measurement:
    """Two planes' distance; or, between two located things (a round-ended slot's ends), as ``position`` measures it."""
    if isinstance(target, Position):
        return measure_position(target, nominal, tolerance, probe)
    width = width_for(tolerance, float(probe.deflection.max(initial=0.0)))
    along = np.asarray(target.along, dtype=np.float64)
    along /= float(np.linalg.norm(along))
    found = 0
    value = float(np.dot(np.subtract(target.a.point, target.b.point), along))
    uncertainty = 0.0
    # Both faces looked at before either is judged missing: a measurement taken again finer
    # where it looked looks at both again (generated part 2010: a wall's outer face all but
    # covered, its inner one not).
    windows = [plane_offset(plane, width, probe) for plane in (target.a, target.b)]
    for plane, sign, (window, offset, u) in zip(
        (target.a, target.b), (1.0, -1.0), windows, strict=True
    ):
        if len(window) < FEWEST:
            return Measurement(
                None,
                found,
                f"no built face within {width:.3g} mm of the spec's plane through {plane.point}",
            )
        found += len(window)
        normal = np.asarray(plane.normal, dtype=np.float64)
        normal /= float(np.linalg.norm(normal))
        value += sign * offset * float(normal @ along)
        uncertainty += u * abs(float(normal @ along))
    return Measurement.of(
        value, uncertainty, found, f"two planes fitted to {found} built points"
    )


#: The value at each limit of the tolerance, ``2u`` inside (it must pass) and outside (it must fail).
mutants = bracket_mutants
