"""The ``count`` kind: how many copies of an item are built.

**Measures** each copy's own surface where the judge's placement puts it
(its round surface, its ball's, or a face it must have), found as the
``diameter`` and ``size`` kinds find them, with the window of the general tolerance: the
count is how many are found. Copies built where the spec has none are face
accounting's to find.

**Tolerance policy:** none: the count is the spec's, or it isn't.

**Mutants and near-misses:** a copy left out (it must fail), and all of
them (it must pass).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..classes import Verdict, general
from ..measure import FEWEST, Measurement, Probe
from .surfaces import Ball, Plane, Round, fitted_ball, fitted_round, width_for

__all__ = ["Copies", "measure", "mutants"]


@dataclass(frozen=True)
class Copies:
    """Each copy's own surface: a round one, a ball's, or a face."""

    each: tuple[Round | Ball | Plane, ...]


def _found(surface: Round | Ball | Plane, probe: Probe, deflection: float) -> bool:
    if isinstance(surface, Round):
        width = width_for(general(2 * surface.radius), deflection)
        return not isinstance(fitted_round(surface, width, probe), str)
    if isinstance(surface, Ball):
        width = width_for(general(2 * surface.radius), deflection)
        return not isinstance(fitted_ball(surface, width, probe), str)
    window = probe.flat(
        surface.point,
        surface.normal,
        width=4 * deflection + 1e-3,
        reach=surface.reach,
        box=surface.box(),
    )
    return len(window) >= FEWEST


def measure(
    target: Copies, nominal: float, tolerance: object, probe: Probe
) -> Measurement:
    deflection = float(probe.deflection.max(initial=0.0))
    found = [_found(surface, probe, deflection) for surface in target.each]
    count = sum(found)
    missing = [k for k, there in enumerate(found) if not there]
    verdict = Verdict.PASS if count == int(nominal) else Verdict.FAIL
    reason = f"{count} of {len(found)} copies built"
    if missing:
        reason += f"; not built: copies {missing[:10]}"
    return Measurement.of(float(count), 0.0, count, reason).with_verdict(verdict)


def mutants(
    nominal: float, tolerance: object, uncertainty: float
) -> tuple[tuple[float, Verdict], ...]:
    """A copy left out (it must fail), and all of them (it must pass)."""
    return ((nominal - 1, Verdict.FAIL), (nominal, Verdict.PASS))
