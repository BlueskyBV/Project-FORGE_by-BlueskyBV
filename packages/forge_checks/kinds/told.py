"""Shapes told apart by points: what the ``on`` and ``choice`` kinds measure.

A choice (round or square ends, a rectangle or a circle, cut in or standing
out, which face an item is on) makes one shape where another choice would
make another. Where the two differ by more than the part may (each surface
off by its tolerance and the view's deflection), a point is in one and out
of the other: the spec's choice must have it on its own side. The check
compiler finds such points from the spec's shape and each other choice's
(the oracle of the spec with that field changed), so a part built with the
other choice fails, and one built with the spec's passes.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..classes import Verdict
from ..measure import Measurement, Probe
from ..view import Side

__all__ = ["Tells", "Told", "measure"]

Vec = tuple[float, float, float]


@dataclass(frozen=True)
class Tells:
    """Points the spec's shape has on ``sides`` (IN or OUT) and the shape ``other`` makes has on the other side."""

    other: str
    points: tuple[Vec, ...]
    sides: tuple[int, ...]


@dataclass(frozen=True)
class Told:
    """The spec's choice, told from each other choice by its points. None of them telling: the other choices make the same shape."""

    tells: tuple[Tells, ...]


def measure(
    target: Told, nominal: float, tolerance: object, probe: Probe
) -> Measurement:
    """PASS when every point is on the spec's side; FAIL when one is surely on the other; INCONCLUSIVE when the view can't say."""
    asked = [
        (t, p, s) for t in target.tells for p, s in zip(t.points, t.sides, strict=True)
    ]
    if not asked:
        return Measurement(
            None, 0, "no other choice makes a different shape", verdict=Verdict.PASS
        )
    points = np.array([p for _, p, _ in asked], dtype=np.float64)
    expected = np.array([s for _, _, s in asked], dtype=np.int8)
    found = probe.view.classify(points)
    clear = (found == Side.IN) | (found == Side.OUT)
    wrong = np.flatnonzero(clear & (found != expected))
    if len(wrong):
        tells = asked[int(wrong[0])][0]
        point = tuple(round(float(x), 4) for x in points[wrong[0]])
        return Measurement(None, len(points), f"built as {tells.other}: {point} is on its side",
                           verdict=Verdict.FAIL)  # fmt: skip
    if not clear.all():
        return Measurement(None, len(points), "the view can't say which side some points are on",
                           missing=False, verdict=Verdict.INCONCLUSIVE)  # fmt: skip
    others = ", ".join(t.other for t in target.tells)
    return Measurement(
        None,
        len(points),
        f"{len(points)} points tell it from {others}",
        verdict=Verdict.PASS,
    )
