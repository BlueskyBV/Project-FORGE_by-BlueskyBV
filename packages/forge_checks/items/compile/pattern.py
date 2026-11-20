"""What the check compiler holds of each pattern mode: the ``compile`` role's modes (V2-stage4b-0b.md, 2), laid out as the modes of the pattern kind stage 4b.4 makes an item.

:data:`PATTERN_COMPILE` holds one entry per mode, in ``PATTERN_FIELDS``' order.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_registry import Registry
from forge_spec.draft import Item, Pattern
from forge_spec.values import Value

from forge_checks.items.compile._common import _deg
from forge_checks.place import Copy, FlatFace

if TYPE_CHECKING:
    from forge_checks.items.compile._context import CompileContext

from forge_spec.draft import PATTERN_FIELDS


class PatternCompile:
    """One pattern mode, as the ``compile`` role holds it."""

    #: The mode this entry is for.
    key = ""
    #: Its copies are round its circle's centre (a circle's, an arc's).
    round = False
    #: Its centre is the circle's through its copies (an arc's), not their mean.
    centre_from_circle = False
    #: Its copies are in a line, each pitch between neighbours (a row's).
    in_a_line = False

    def fixed_axes(self, pattern: Pattern, axes: tuple[str, str]) -> set[str]:
        """The face's axes its copies' places are set along by the pattern itself."""
        return set()

    def value_checks(self, c: CompileContext, item: Item, at: str, pattern: Pattern, name: str, value: Value,
                     group: list[Copy], face: FlatFace) -> None:  # fmt: skip
        """One of its values' checks: a pitch's (a row's, a grid's, a rectangle's)."""
        c._pitches(item, at, pattern, name, value, group)

    def pitch_axis(self, pattern: Pattern, name: str) -> str:
        """The axis its pitch ``name`` runs along: the value's own (a rectangle's)."""
        return name

    def round_step(self, pattern: Pattern, count: int) -> float:
        """The angle from one copy to the next round its circle (degrees), of ``count``."""
        raise NotImplementedError(self.key)

    def told(self, count: int) -> tuple[int, ...]:
        """Which of ``count`` copies its angles are told by: the first (an arc's), each (a circle's)."""
        return (0,)


class Corners(PatternCompile):
    key = "corners"

    def fixed_axes(self, pattern: Pattern, axes: tuple[str, str]) -> set[str]:
        return set(axes)

    def value_checks(self, c: CompileContext, item: Item, at: str, pattern: Pattern, name: str, value: Value,
                     group: list[Copy], face: FlatFace) -> None:  # fmt: skip
        c._insets(item, at, name, value, group, face, pattern)


class Rectangle(PatternCompile):
    key = "rectangle"


class Ends(PatternCompile):
    key = "ends"

    def fixed_axes(self, pattern: Pattern, axes: tuple[str, str]) -> set[str]:
        return {str(pattern.axis)}

    def value_checks(self, c: CompileContext, item: Item, at: str, pattern: Pattern, name: str, value: Value,
                     group: list[Copy], face: FlatFace) -> None:  # fmt: skip
        c._insets(item, at, name, value, group, face, pattern)


class Row(PatternCompile):
    key = "row"
    in_a_line = True

    def pitch_axis(self, pattern: Pattern, name: str) -> str:
        return str(pattern.axis)

    def round_step(self, pattern: Pattern, count: int) -> float:
        return 0.0  # round a side, all along it at one angle (place.md, "On a round side")

    def told(self, count: int) -> tuple[int, ...]:
        return tuple(range(count))


class Grid(PatternCompile):
    key = "grid"

    def pitch_axis(self, pattern: Pattern, name: str) -> str:
        return name[len("pitch_") :]


class RoundCompile(PatternCompile):
    """A circle's or an arc's copies."""

    round = True

    def value_checks(self, c: CompileContext, item: Item, at: str, pattern: Pattern, name: str, value: Value,
                     group: list[Copy], face: FlatFace) -> None:  # fmt: skip
        c._circle(item, at, pattern, name, value, group, face)


class Circle(RoundCompile):
    key = "circle"

    def round_step(self, pattern: Pattern, count: int) -> float:
        return 360.0 / count

    def told(self, count: int) -> tuple[int, ...]:
        return tuple(range(count))


class Arc(RoundCompile):
    key = "arc"
    centre_from_circle = True

    def round_step(self, pattern: Pattern, count: int) -> float:
        return _deg(pattern.values["step"])


PATTERN_COMPILE: Registry[PatternCompile] = Registry(
    "forge_checks.compile.pattern",
    PATTERN_FIELDS,
    [Corners(), Rectangle(), Ends(), Row(), Grid(), Circle(), Arc()],
    protocol=PatternCompile,
)
