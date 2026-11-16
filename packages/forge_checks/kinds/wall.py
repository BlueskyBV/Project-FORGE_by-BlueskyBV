"""The ``wall`` kind: a hollowed body's wall or floor, from its outer face to the hollow's face behind it.

**A flat wall** (:class:`~forge_checks.kinds.size.Between`): the two faces'
fitted planes, as the ``size`` kind measures them: the body's face, facing
out of the material, and the hollow's face behind it, facing into the
hollow, each within ``reach`` of its point; the wall is the distance between
them across it.

**A round wall** (:class:`Annulus`): a hollowed rod's side, or a hollowed
ball's: the body's round surface and the hollow's behind it. Every part of
the wall must be within the tolerance, so the measurement is all of it at
once, measured from one line or point: the outside's fitted axis, or its
fitted centre. Each built point's distance from it is within its
deflection of its surface's in its own direction (a little more where the
surface's own axis or centre may be off the line or point, and its normal
leans from the direction). The outside lies between the least and the
greatest of its points' distances, and the hollow between its own; the
wall is from the outside's least less the hollow's greatest to the
outside's greatest less the hollow's least. An off-centre hollow is thin on
one side and thick on the other, and found so on its own points, where two
centres each fitted to within a few times the deflection would only bound
it. Between its points a face is as round as face accounting holds it.

**Tolerance policy:** a linear size: the thickness's own tolerance, or ISO
2768-m by the nominal (docs/definitions/sizes.md).

**Uncertainty:** a flat wall's, each face's mean deflection, added; a round
wall's, half the spread of the wall from its thinnest to its thickest,
each point's deflection in it.

**Mutants and near-misses:** the wall at each limit of the tolerance,
``2u`` outside (it must fail) and ``2u`` inside (it must pass).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from forge_numeric import vector as fv
from numpy.typing import NDArray

from ..classes import Tolerance, bracket_mutants
from ..measure import Measurement, Probe, Window
from .size import Between
from .size import measure as measure_between
from .surfaces import Ball, Round, fitted_ball, fitted_round, width_for

__all__ = ["Annulus", "measure", "mutants"]

Array = NDArray[np.float64]


@dataclass(frozen=True)
class Annulus:
    """A round wall: between the body's round surface ``outer`` and the hollow's ``inner`` behind it (two coaxial round surfaces, or two concentric balls)."""

    outer: Round | Ball
    inner: Round | Ball


def _band(window: Window, distance: Array, lean: float) -> tuple[float, float]:
    """The least and greatest distance a surface may be from the line or point, given its built points' (``distance``): each within its deflection, over the cosine of the most its normal may lean from the way the distance is measured (``lean``, a sine)."""
    off = window.deflection / math.sqrt(1 - fv.sq(min(lean, 0.5)))
    return float((distance - off).min()), float((distance + off).max())


def _across(
    outside: tuple[float, float],
    hollow: tuple[float, float],
    apart: float,
    radius: float,
    found: int,
    said: str,
) -> Measurement:
    """The wall from its thinnest to its thickest: the outside's least distance less the hollow's greatest, and the other way round; thinner square to its faces than along the distance by no more than the square of how far apart the surfaces' axes or centres may be (``apart``) over the hollow's ``radius``."""
    thinnest = outside[0] - hollow[1] - apart * apart / radius
    thickest = outside[1] - hollow[0]
    return Measurement.of(
        (thinnest + thickest) / 2,
        (thickest - thinnest) / 2,
        found,
        f"{said}, on {found} built points",
    )


def _rounds(outer: Round, inner: Round, width: float, probe: Probe) -> Measurement:
    # Both fitted before either is judged missing, so a measurement taken again finer looks at both.
    a = fitted_round(outer, width, probe)
    b = fitted_round(inner, width, probe)
    if isinstance(a, str):
        return Measurement(
            None, 0, f"its outside: {a}", missing=a.startswith("no built")
        )
    if isinstance(b, str):
        return Measurement(
            None, a.found, f"its inside: {b}", missing=b.startswith("no built")
        )

    def distance(window: Window) -> Array:
        d = window.points - a.centre
        return np.asarray(
            fv.norm(d - np.outer(fv.matmul(d, a.axis), a.axis), axis=1),
            dtype=np.float64,
        )

    # How far each surface's own axis may be from the outside's fitted one, any way across it.
    off_a = math.hypot(a.fit.u_centre[0], a.fit.u_centre[1])
    gap = b.centre - a.centre
    off_b = float(fv.norm(gap - (fv.matmul(gap, a.axis)) * a.axis)) + math.hypot(
        b.fit.u_centre[0], b.fit.u_centre[1]
    )
    outside = _band(a.window, distance(a.window), off_a / a.fit.radius)
    hollow = _band(b.window, distance(b.window), off_b / b.fit.radius)
    return _across(outside, hollow, off_a + off_b, b.fit.radius, a.found + b.found,
                   "the wall from the outside's fitted axis")  # fmt: skip


def _balls(outer: Ball, inner: Ball, width: float, probe: Probe) -> Measurement:
    a = fitted_ball(outer, width, probe)
    b = fitted_ball(inner, width, probe)
    if isinstance(a, str):
        return Measurement(
            None, 0, f"its outside: {a}", missing=a.startswith("no built")
        )
    if isinstance(b, str):
        return Measurement(
            None, a.found, f"its inside: {b}", missing=b.startswith("no built")
        )
    centre = np.asarray(a.fit.centre, dtype=np.float64)

    def distance(window: Window) -> Array:
        return np.asarray(fv.norm(window.points - centre, axis=1), dtype=np.float64)

    # How far each surface's own centre may be from the outside's fitted one.
    off_a = float(fv.norm(a.fit.u_centre))
    off_b = float(fv.norm(np.asarray(b.fit.centre) - centre)) + float(
        fv.norm(b.fit.u_centre)
    )
    outside = _band(a.window, distance(a.window), off_a / a.fit.radius)
    hollow = _band(b.window, distance(b.window), off_b / b.fit.radius)
    return _across(outside, hollow, off_a + off_b, b.fit.radius, a.found + b.found,
                   "the wall from the outside's fitted centre")  # fmt: skip


def measure(
    target: Between | Annulus, nominal: float, tolerance: Tolerance, probe: Probe
) -> Measurement:
    if isinstance(target, Between):
        return measure_between(target, nominal, tolerance, probe)
    width = width_for(tolerance, float(probe.deflection.max(initial=0.0)))
    outer, inner = target.outer, target.inner
    if isinstance(outer, Round) and isinstance(inner, Round):
        return _rounds(outer, inner, width, probe)
    if isinstance(outer, Ball) and isinstance(inner, Ball):
        return _balls(outer, inner, width, probe)
    raise TypeError(
        f"a round wall is two round surfaces or two balls, not {outer!r} and {inner!r}"
    )


#: The wall at each limit of the tolerance, ``2u`` inside (it must pass) and outside (it must fail).
mutants = bracket_mutants
