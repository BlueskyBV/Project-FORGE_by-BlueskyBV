"""The ``depth`` kind: how deep a cut goes, to its floor, or right through.

**A floor** (:class:`~forge_checks.kinds.size.Between`): from the host
face's fitted plane round the mouth to the floor's fitted plane, along the
face's normal: two planes, measured as the ``size`` kind measures them. In a
round side (:class:`~forge_checks.kinds.position.Position`), from the side's
fitted axis to the floor's fitted plane, less the side's radius: the depth
is from the side's surface at the cut's centre (hole.md).

**Right through** (:class:`Open`): lines along the cut's axis, from just
outside its mouth, must meet no material for the whole depth of the material
under the face (``span``, the judge's placement worked it out). One near
the axis and four round it, half way out: a skin left across the far end,
or a blind hole for a through one, is met. A line that grazes an edge is cast
again a little turned.

**Tolerance policy:** a floor's depth is a linear size (its own tolerance,
or ISO 2768-m). Right through has none: no material may be met before the
material ends; material met within the view's deflection of where it ends
can't be told from its far face (INCONCLUSIVE).

**Mutants and near-misses:** a floor, as ``size``'s; right through, a skin
twice the deflection thick at the far end (it must fail), and none (it must
pass) (:func:`mutants`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from forge_numeric import scalar as fs

from ..classes import Tolerance, Verdict, bracket_mutants
from ..measure import Measurement, Probe, basis
from . import size
from .position import Position

__all__ = ["Open", "measure", "mutants"]

Vec = tuple[float, float, float]

#: Turns tried, a little each, for lines that graze an edge.
_TURNS = 8


@dataclass(frozen=True)
class Open:
    """A cut right through: from ``mouth`` along ``axis`` (into the material), air for at least ``span``; ``radius`` how far it reaches round the axis."""

    mouth: Vec
    axis: Vec
    span: float
    radius: float


def measure(
    target: size.Between | Position | Open,
    nominal: float,
    tolerance: Tolerance | None,
    probe: Probe,
) -> Measurement:
    if isinstance(target, (size.Between, Position)):
        assert tolerance is not None, "a floor's depth has a tolerance"
        return size.measure(target, nominal, tolerance, probe)
    return _open(target, probe)


def _open(target: Open, probe: Probe) -> Measurement:
    w, e1, e2 = basis(target.axis)
    d = float(probe.deflection.max(initial=0.0))
    lead = 2 * d + 1e-3  # start in the air just outside the mouth
    mouth = np.asarray(target.mouth, dtype=np.float64)
    first = math.inf
    for turn in range(_TURNS):
        angle = turn * 2 * math.pi / (4 * _TURNS)
        # One near the axis (not on it: a cap's triangles meet there) and four half way out.
        ways = [
            target.radius
            * scale
            * (
                fs.cos(angle + k * math.pi / 2) * e1
                + fs.sin(angle + k * math.pi / 2) * e2
            )
            for scale, k in ((0.1, 0.5), (0.5, 0), (0.5, 1), (0.5, 2), (0.5, 3))
        ]
        origins = np.array([mouth - lead * w + v for v in ways])
        found = probe.view.crossings(origins, np.tile(w, (len(origins), 1)))
        if found.grazed.any():
            continue
        entering = found.entering
        if entering.any():
            first = float((found.t[entering] - lead).min())
        break
    else:
        return Measurement(None, 0, "every line along the cut grazed an edge", missing=False,
                           verdict=Verdict.INCONCLUSIVE)  # fmt: skip
    if math.isinf(first) or first > target.span:
        return Measurement(None, 5, f"air from the mouth through all {target.span:g} mm of material",
                           verdict=Verdict.PASS)  # fmt: skip
    if first < target.span - d:
        return Measurement.of(first, d, 5, f"material met {first:.4g} mm in, of {target.span:g}"
                              ).with_verdict(Verdict.FAIL)  # fmt: skip
    return Measurement.of(first, d, 5, f"material met {first:.4g} mm in, within the deflection of the far face at {target.span:g}"
                          ).with_verdict(Verdict.INCONCLUSIVE)  # fmt: skip


def mutants(
    nominal: float, tolerance: Tolerance | None, uncertainty: float
) -> tuple[tuple[float, Verdict], ...]:
    """A floor's depth at its brackets; right through, where material is first met: a skin ``2u`` thick at the far end (it must fail), or none (inf: it must pass)."""
    if tolerance is not None:
        return bracket_mutants(nominal, tolerance, uncertainty)
    return ((nominal - 2 * uncertainty, Verdict.FAIL), (math.inf, Verdict.PASS))
