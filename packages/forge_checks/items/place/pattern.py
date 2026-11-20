"""Where the judge places each pattern mode's copies on a flat face: the ``place`` role's modes (V2-stage4b-0b.md, 2), laid out as the modes of the pattern kind stage 4b.4 makes an item.

:data:`PATTERN_PLACE` holds one entry per mode, in ``PATTERN_FIELDS``' order.
"""

from __future__ import annotations

from collections.abc import Mapping

from forge_registry import Registry
from forge_spec.draft import PATTERN_FIELDS, Item, Pattern

from forge_checks.place import PlaceError, Point, _needs, turn


class PatternPlace:
    """One pattern mode, as the ``place`` role holds it."""

    #: The mode this entry is for.
    key = ""
    #: It needs a rectangular face (a corners or an ends pattern).
    rect_only = False
    #: Its copies are at the face's corners: its offsets are their places, no anchor (a corners pattern's).
    at_the_corners = False
    #: It runs along its own axis, which the face must have (an ends pattern, a row).
    along_its_axis = False
    #: Its copies are placed round its circle's centre (a circle's, an arc's).
    round = False
    #: Round a side, or round its circle, it takes a step too (an arc's).
    steps_round = False
    #: Its copies keep their place along its axis (an ends pattern's).
    pinned_along_axis = False
    #: From an edge it is measured to its nearest copy (a rectangle, a row, a grid).
    nearest_from_edge = False
    #: Round a side it runs along the side's axis, ``pitch`` apart (a row's: place.md, "On a round side").
    along_a_side = False

    def fixed_axes(self, pattern: Pattern, a1: str, a2: str) -> set[str]:
        """The face's axes its copies' places are set along by the pattern itself."""
        return set()

    def round_step(
        self, values: Mapping[str, float], counts: Mapping[str, int]
    ) -> float:
        """The angle from one copy to the next round its circle (degrees): a round mode's."""
        raise NotImplementedError(self.key)

    def offsets(self, item: Item, pattern: Pattern, values: Mapping[str, float], counts: Mapping[str, int],
                half: tuple[float, float], a1: str, a2: str) -> list[Point]:  # fmt: skip
        """Its copies' offsets from where it is placed, in the face's axes (``half`` the face's half sizes)."""
        raise PlaceError(item.id, f"an unknown pattern {pattern.kind!r}")


class Corners(PatternPlace):
    key = "corners"
    rect_only = True
    at_the_corners = True

    def fixed_axes(self, pattern: Pattern, a1: str, a2: str) -> set[str]:
        return {a1, a2}

    def offsets(self, item: Item, pattern: Pattern, values: Mapping[str, float], counts: Mapping[str, int],
                half: tuple[float, float], a1: str, a2: str) -> list[Point]:  # fmt: skip
        _needs(item, pattern, values, f"inset_{a1}", f"inset_{a2}")
        c1, c2 = half[0] - values[f"inset_{a1}"], half[1] - values[f"inset_{a2}"]
        return [(s1 * c1, s2 * c2) for s1 in (-1, 1) for s2 in (-1, 1)]


class Rectangle(PatternPlace):
    key = "rectangle"
    nearest_from_edge = True

    def offsets(self, item: Item, pattern: Pattern, values: Mapping[str, float], counts: Mapping[str, int],
                half: tuple[float, float], a1: str, a2: str) -> list[Point]:  # fmt: skip
        _needs(item, pattern, values, a1, a2)
        offsets = [
            (s1 * values[a1] / 2, s2 * values[a2] / 2)
            for s1 in (-1, 1)
            for s2 in (-1, 1)
        ]
        return offsets


class Ends(PatternPlace):
    key = "ends"
    rect_only = True
    along_its_axis = True
    pinned_along_axis = True

    def fixed_axes(self, pattern: Pattern, a1: str, a2: str) -> set[str]:
        return {pattern.axis} if pattern.axis is not None else set()

    def offsets(self, item: Item, pattern: Pattern, values: Mapping[str, float], counts: Mapping[str, int],
                half: tuple[float, float], a1: str, a2: str) -> list[Point]:  # fmt: skip
        _needs(item, pattern, values, "inset")
        k = 0 if pattern.axis == a1 else 1
        c = half[k] - values["inset"]
        offsets = [(-c, 0.0), (c, 0.0)] if k == 0 else [(0.0, -c), (0.0, c)]
        return offsets


class Row(PatternPlace):
    key = "row"
    along_its_axis = True
    nearest_from_edge = True
    along_a_side = True

    def offsets(self, item: Item, pattern: Pattern, values: Mapping[str, float], counts: Mapping[str, int],
                half: tuple[float, float], a1: str, a2: str) -> list[Point]:  # fmt: skip
        _needs(item, pattern, {**values, **counts}, "pitch", "count")
        steps = [
            (k - (counts["count"] - 1) / 2) * values["pitch"]
            for k in range(counts["count"])
        ]
        offsets = (
            [(s, 0.0) for s in steps]
            if pattern.axis == a1
            else [(0.0, s) for s in steps]
        )
        return offsets


class Grid(PatternPlace):
    key = "grid"
    nearest_from_edge = True

    def offsets(self, item: Item, pattern: Pattern, values: Mapping[str, float], counts: Mapping[str, int],
                half: tuple[float, float], a1: str, a2: str) -> list[Point]:  # fmt: skip
        _needs(
            item,
            pattern,
            {**values, **counts},
            f"pitch_{a1}",
            f"pitch_{a2}",
            f"count_{a1}",
            f"count_{a2}",
        )
        n1, n2 = counts[f"count_{a1}"], counts[f"count_{a2}"]
        p1, p2 = values[f"pitch_{a1}"], values[f"pitch_{a2}"]
        offsets = [
            ((i - (n1 - 1) / 2) * p1, (j - (n2 - 1) / 2) * p2)
            for i in range(n1)
            for j in range(n2)
        ]
        return offsets


class RoundPlace(PatternPlace):
    """A circle's or an arc's copies, round its centre."""

    round = True

    def offsets(self, item: Item, pattern: Pattern, values: Mapping[str, float], counts: Mapping[str, int],
                half: tuple[float, float], a1: str, a2: str) -> list[Point]:  # fmt: skip
        _needs(
            item,
            pattern,
            {**values, **counts},
            "diameter",
            "count",
            *(("step",) if self.steps_round else ()),
        )
        n, radius, start = (
            counts["count"],
            values["diameter"] / 2,
            values.get("start", 0.0),
        )
        step = self.round_step(values, counts)
        offsets = [
            (radius * c, radius * s)
            for c, s in (turn(start + k * step) for k in range(n))
        ]
        return offsets


class Circle(RoundPlace):
    key = "circle"

    def round_step(
        self, values: Mapping[str, float], counts: Mapping[str, int]
    ) -> float:
        return 360.0 / counts["count"]


class Arc(RoundPlace):
    key = "arc"
    steps_round = True

    def round_step(
        self, values: Mapping[str, float], counts: Mapping[str, int]
    ) -> float:
        return values["step"]


PATTERN_PLACE: Registry[PatternPlace] = Registry(
    "forge_checks.place.pattern",
    PATTERN_FIELDS,
    [Corners(), Rectangle(), Ends(), Row(), Grid(), Circle(), Arc()],
    protocol=PatternPlace,
)
