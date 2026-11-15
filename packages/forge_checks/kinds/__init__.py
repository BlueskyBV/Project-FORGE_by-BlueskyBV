"""The check kinds: one module per aspect of an item measured on a view (docs/V2-stage2.md, section 7).

Each kind's module holds its target (what it measures, placed by the judge's
own placement), its measurement (:func:`measure`, through a
:class:`~forge_checks.measure.Probe`), its tolerance policy, and its mutants
and near-misses (:func:`mutants`), which a test requires.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from ..classes import Verdict
from ..measure import Measurement, Probe
from . import (
    angle,
    choice,
    corner,
    count,
    depth,
    diameter,
    on,
    pattern,
    position,
    rounding,
    size,
    thread,
    wall,
)

__all__ = [
    "MEASURES",
    "MUTANTS",
    "angle",
    "choice",
    "corner",
    "count",
    "depth",
    "diameter",
    "on",
    "pattern",
    "position",
    "rounding",
    "size",
    "thread",
    "wall",
]

#: Each kind's measurement: (target, nominal, tolerance, probe) to what it found. A kind that
#: judges itself (no tolerance) is given None.
MEASURES: Mapping[str, Callable[[Any, float, Any, Probe], Measurement]] = {
    "diameter": diameter.measure,
    "size": size.measure,
    "depth": depth.measure,
    "position": position.measure,
    "on": on.measure,
    "count": count.measure,
    "pattern": pattern.measure,
    "angle": angle.measure,
    "corner": corner.measure,
    "rounding": rounding.measure,
    "wall": wall.measure,
    "choice": choice.measure,
    "thread": thread.measure,
}

#: Each kind's mutants and near-misses: (nominal, tolerance, uncertainty) to values and the verdicts they
#: must get. On and choice are told apart by the other choices themselves (their tests make each).
MUTANTS: Mapping[
    str, Callable[[float, Any, float], tuple[tuple[float, Verdict], ...]]
] = {
    "diameter": diameter.mutants,
    "size": size.mutants,
    "depth": depth.mutants,
    "position": position.mutants,
    "count": count.mutants,
    "pattern": pattern.mutants,
    "angle": angle.mutants,
    "corner": corner.mutants,
    "rounding": rounding.mutants,
    "wall": wall.mutants,
    "thread": thread.mutants,
}
