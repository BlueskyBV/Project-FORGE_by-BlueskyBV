"""How the generator draws and places each pattern mode: the ``draw`` role's modes (V2-stage4b-0b.md, 2), laid out as the modes of the pattern kind stage 4b.4 makes an item.

:data:`PATTERN_DRAW` holds one entry per mode, in ``PATTERN_FIELDS``' order.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

from forge_numeric import scalar as fs
from forge_registry import Registry
from forge_spec.draft import PATTERN_FIELDS

from forge_eval.generator import DoesNotFitError, Pattern, _Flat


class PatternDraw:
    """One pattern mode, as the ``draw`` role holds it."""

    #: The mode this entry is for.
    key = ""
    #: Its copies are at the face's corners (a corners pattern's): the face must be a rectangle, both its axes set.
    at_the_corners = False
    #: Its copies go all round a circle (a circle's): round a side, the only way.
    round_whole = False
    #: Its counts are per axis (a grid's).
    counted_per_axis = False

    def offsets(self, pattern: Pattern, face: _Flat | None, v: Mapping[str, float], c: Mapping[str, int],
                kind: str) -> list[tuple[float, float]]:  # fmt: skip
        raise DoesNotFitError(f"no pattern {kind!r} here")

    def axis_names(self, a1: str, a2: str) -> tuple[set[str], set[str]] | None:
        """The values and counts that run along the face's axes ``a1``, ``a2`` a pattern of it must name; None where it names none."""
        return None


class Corners(PatternDraw):
    key = "corners"
    at_the_corners = True

    def axis_names(self, a1: str, a2: str) -> tuple[set[str], set[str]] | None:
        return {f"inset_{a1}", f"inset_{a2}"}, set()


class Rectangle(PatternDraw):
    key = "rectangle"

    def offsets(self, pattern: Pattern, face: _Flat | None, v: Mapping[str, float], c: Mapping[str, int],
                kind: str) -> list[tuple[float, float]]:  # fmt: skip
        assert face is not None
        a, b = v[face.axes[0]] / 2, v[face.axes[1]] / 2
        return [(-a, -b), (-a, b), (a, -b), (a, b)]

    def axis_names(self, a1: str, a2: str) -> tuple[set[str], set[str]] | None:
        return {a1, a2}, set()


class Ends(PatternDraw):
    key = "ends"


class Row(PatternDraw):
    key = "row"

    def offsets(self, pattern: Pattern, face: _Flat | None, v: Mapping[str, float], c: Mapping[str, int],
                kind: str) -> list[tuple[float, float]]:  # fmt: skip
        n, p = c["count"], v["pitch"]
        along = [(k - (n - 1) / 2) * p for k in range(n)]
        assert face is not None
        first = pattern.axis == face.axes[0]
        return [(a, 0.0) if first else (0.0, a) for a in along]


class Grid(PatternDraw):
    key = "grid"
    counted_per_axis = True

    def offsets(self, pattern: Pattern, face: _Flat | None, v: Mapping[str, float], c: Mapping[str, int],
                kind: str) -> list[tuple[float, float]]:  # fmt: skip
        assert face is not None
        a1, a2 = face.axes
        n1, n2 = c[f"count_{a1}"], c[f"count_{a2}"]
        p1, p2 = v[f"pitch_{a1}"], v[f"pitch_{a2}"]
        return [
            ((i - (n1 - 1) / 2) * p1, (j - (n2 - 1) / 2) * p2)
            for i in range(n1)
            for j in range(n2)
        ]

    def axis_names(self, a1: str, a2: str) -> tuple[set[str], set[str]] | None:
        return {f"pitch_{a1}", f"pitch_{a2}"}, {f"count_{a1}", f"count_{a2}"}


class Circle(PatternDraw):
    key = "circle"
    round_whole = True

    def offsets(self, pattern: Pattern, face: _Flat | None, v: Mapping[str, float], c: Mapping[str, int],
                kind: str) -> list[tuple[float, float]]:  # fmt: skip
        n, r, start = c["count"], v["diameter"] / 2, v.get("start", 0.0)
        return [
            (
                r * fs.cos(math.radians(start + k * 360 / n)),
                r * fs.sin(math.radians(start + k * 360 / n)),
            )
            for k in range(n)
        ]


class Arc(PatternDraw):
    key = "arc"


PATTERN_DRAW: Registry[PatternDraw] = Registry(
    "forge_eval.draw.pattern",
    PATTERN_FIELDS,
    [Corners(), Rectangle(), Ends(), Row(), Grid(), Circle(), Arc()],
    protocol=PatternDraw,
)
