"""The ``pattern`` kind: the spacing of a pattern's copies, measured between the copies as built.

**Pitches** (:class:`Pitches`): the distance between each pair of copies
the pitch runs between (neighbours in a row, a grid's rows and columns, a
rectangle's sides), along the pitch's direction, from one copy's built
centre to the other's (a fitted axis, or the middle of two fitted sides:
:func:`~forge_checks.kinds.position.locate`); every pair must be within the
tolerance, so the measurement is all of them at once (from the least to the
greatest).

**A circle** (:class:`Circle`): a circle fitted through the copies' built
centres in the face's plane (:func:`~forge_checks.kinds.position.ring`,
which the angles round it and its centre's position use too); its
diameter.

**Tolerance policy:** a linear size: the value's own tolerance, or ISO
2768-m by the nominal pitch or diameter.

**Uncertainty:** each pair's: both copies' uncertainties along the way the
pitch is measured; the circle's, from each axis's (as far as it may be off
along the circle's radius, whichever way that runs: the sum of how far it
may be off along each of the plane's two axes).

**Mutants and near-misses:** the pitch or diameter at each limit of the
tolerance, ``2u`` outside (it must fail) and ``2u`` inside (it must pass).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from forge_numeric import vector as fv

from ..classes import Tolerance, bracket_mutants
from ..measure import Measurement, Probe
from .position import Centre, Ref, Spot, locate, ring
from .surfaces import width_for

__all__ = ["Circle", "Pitches", "measure", "mutants"]

Vec = tuple[float, float, float]


@dataclass(frozen=True)
class Pitches:
    """The distance from ``copies[i]`` to ``copies[j]`` along ``along``, for each pair: each copy's built centre."""

    copies: tuple[Ref, ...]
    pairs: tuple[tuple[int, int], ...]
    along: Vec


@dataclass(frozen=True)
class Circle:
    """The circle through the copies' built centres, in the plane of the two axes ``plane``."""

    copies: tuple[Spot, ...]
    plane: tuple[Vec, Vec]


def _round_copies(spots: tuple[Spot, ...]) -> list[float]:
    """The radii of the round copies among the spots (a quarter of the least widens their windows)."""
    return [s.first.round.radius for s in spots if isinstance(s.first, Centre)]


def measure(
    target: Pitches | Circle, nominal: float, tolerance: Tolerance, probe: Probe
) -> Measurement:
    deflection = float(probe.deflection.max(initial=0.0))
    if isinstance(target, Circle):
        width = width_for(tolerance, deflection)
        width += min(_round_copies(target.copies), default=0.0) / 4
        built = ring(target.copies, target.plane, width, probe)
        if isinstance(built, str):
            return Measurement(None, 0, built, missing=": no built" in built)
        if built.circle is None:
            return Measurement(
                None,
                built.found,
                "the copies' centres don't fix a circle",
                missing=False,
            )
        return Measurement.of(
            2 * built.circle.radius,
            2 * built.circle.u_radius,
            built.found,
            f"a circle through {len(target.copies)} built centres",
        )
    # A pitch off by the tolerance moves the copies farthest from the middle by it that many times over.
    width = width_for(tolerance, deflection) * max(1.0, (len(target.copies) - 1) / 2)
    width += (
        min(
            (c.round.radius for c in target.copies if isinstance(c, Centre)),
            default=0.0,
        )
        / 4
    )
    way = np.asarray(target.along, dtype=np.float64)
    way /= float(fv.norm(way))
    located: list[tuple[float, float, int]] = []
    for k, copy in enumerate(target.copies):
        at = locate(copy, way, width, probe)
        if isinstance(at, str):
            return Measurement(None, sum(f[2] for f in located), f"copy {k}: {at}",
                               missing=at.startswith("no built"))  # fmt: skip
        located.append(at)
    lo, hi = np.inf, -np.inf
    for i, j in target.pairs:
        length = located[j][0] - located[i][0]
        u = located[i][1] + located[j][1]
        lo, hi = min(lo, length - u), max(hi, length + u)
    middle, half = (lo + hi) / 2, (hi - lo) / 2
    return Measurement.of(
        middle,
        half,
        sum(f[2] for f in located),
        f"{len(target.pairs)} pitches between built copies",
    )


#: The pitch or diameter at each limit of the tolerance, ``2u`` inside (it must pass) and outside (it must fail).
mutants = bracket_mutants
