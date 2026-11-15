"""The check kinds: one module per aspect of an item measured on a view (docs/V2-stage2.md, section 7).

Each kind's module holds its target (what it measures, placed by the judge's
own placement), its measurement (:func:`measure`, through a
:class:`~forge_checks.measure.Probe`), its tolerance policy, and its mutants
and near-misses (:func:`mutants`), which a test requires.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import StrEnum
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
    "CheckKind",
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


class CheckKind(StrEnum):
    """The kinds of check, which aren't item kinds even where they share a name (a thread's)."""

    DIAMETER = "diameter"
    SIZE = "size"
    DEPTH = "depth"
    POSITION = "position"
    ON = "on"
    COUNT = "count"
    PATTERN = "pattern"
    ANGLE = "angle"
    CORNER = "corner"
    ROUNDING = "rounding"
    WALL = "wall"
    CHOICE = "choice"
    THREAD = "thread"


#: Each kind's measurement: (target, nominal, tolerance, probe) to what it found. A kind that
#: judges itself (no tolerance) is given None.
MEASURES: Mapping[str, Callable[[Any, float, Any, Probe], Measurement]] = {
    CheckKind.DIAMETER: diameter.measure,
    CheckKind.SIZE: size.measure,
    CheckKind.DEPTH: depth.measure,
    CheckKind.POSITION: position.measure,
    CheckKind.ON: on.measure,
    CheckKind.COUNT: count.measure,
    CheckKind.PATTERN: pattern.measure,
    CheckKind.ANGLE: angle.measure,
    CheckKind.CORNER: corner.measure,
    CheckKind.ROUNDING: rounding.measure,
    CheckKind.WALL: wall.measure,
    CheckKind.CHOICE: choice.measure,
    CheckKind.THREAD: thread.measure,
}

#: Each kind's mutants and near-misses: (nominal, tolerance, uncertainty) to values and the verdicts they
#: must get. On and choice are told apart by the other choices themselves (their tests make each).
MUTANTS: Mapping[
    str, Callable[[float, Any, float], tuple[tuple[float, Verdict], ...]]
] = {
    CheckKind.DIAMETER: diameter.mutants,
    CheckKind.SIZE: size.mutants,
    CheckKind.DEPTH: depth.mutants,
    CheckKind.POSITION: position.mutants,
    CheckKind.COUNT: count.mutants,
    CheckKind.PATTERN: pattern.mutants,
    CheckKind.ANGLE: angle.mutants,
    CheckKind.CORNER: corner.mutants,
    CheckKind.ROUNDING: rounding.mutants,
    CheckKind.WALL: wall.mutants,
    CheckKind.THREAD: thread.mutants,
}
