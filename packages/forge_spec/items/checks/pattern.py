"""What the spec checks hold of each pattern mode: the ``checks`` role's modes (V2-stage4b-0b.md, 2), laid out as the modes of the pattern kind stage 4b.4 makes an item.

:data:`PATTERN_CHECKS` holds one entry per mode, in ``PATTERN_FIELDS``' order.
"""

from __future__ import annotations

from forge_registry import Registry

from forge_spec.draft import PATTERN_FIELDS


class PatternCheck:
    """One pattern mode, as the spec checks hold it."""

    #: The mode this entry is for.
    key = ""
    #: How many copies it makes whatever its counts say (an ``ends`` pattern's two, one at each end), or None.
    fixed_count: int | None = None


class Corners(PatternCheck):
    key = "corners"


class Rectangle(PatternCheck):
    key = "rectangle"


class Ends(PatternCheck):
    key = "ends"
    fixed_count = 2


class Row(PatternCheck):
    key = "row"


class Grid(PatternCheck):
    key = "grid"


class Circle(PatternCheck):
    key = "circle"


class Arc(PatternCheck):
    key = "arc"


PATTERN_CHECKS: Registry[PatternCheck] = Registry(
    "forge_spec.checks.pattern",
    PATTERN_FIELDS,
    [Corners(), Rectangle(), Ends(), Row(), Grid(), Circle(), Arc()],
    protocol=PatternCheck,
)
