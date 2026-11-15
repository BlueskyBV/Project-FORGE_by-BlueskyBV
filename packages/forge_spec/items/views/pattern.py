"""How the confirmation views draw each pattern mode: the ``views`` role's modes (V2-stage4b-0b.md, 2), laid out as the modes of the pattern kind stage 4b.4 makes an item.

:data:`PATTERN_VIEWS` holds one entry per mode, in ``PATTERN_FIELDS``' order. Moved from ``render_views.py``'s
``_Drawing._on_flat``, ``_on_side`` and ``_pattern_words`` at stage 4b.0b's step 5.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING

from forge_registry import Registry

from forge_spec.draft import PATTERN_FIELDS, Pattern
from forge_spec.geometry import Face, FlatFace
from forge_spec.items.views._common import _value
from forge_spec.placement import Instance, mm
from forge_spec.values import Count, Value

if TYPE_CHECKING:
    from forge_spec.render_views import _Canvas, _Drawing


class PatternView:
    """One pattern mode, as the confirmation views draw it."""

    #: The mode this entry is for.
    key = ""
    #: Its copies are placed by its circle's centre, and spread round it (a circle's, an arc's).
    round = False
    #: Its copies are equally spaced round a side (a circle's).
    equally_spaced = False
    #: The place is measured to its centre, marked (not a corners pattern's: its copies are at the face's corners).
    measured_to_centre = True

    def inset(self, pattern: Pattern, axis: str) -> str | None:
        """The value its copies are inset from the face's edges by along ``axis``, if any (a corners or an ends pattern's)."""
        return None

    def steps(self, pattern: Pattern, face: FlatFace, local: Sequence[Instance], middle: tuple[float, float],
              canvas: _Canvas, between: Callable[[int, int, str, str], None]) -> None:  # fmt: skip
        """The lines from its first copy to the next that show its pitches, along the face's axes."""

    def words(
        self,
        d: _Drawing,
        face: Face | None,
        values: Mapping[str, Value],
        counts: Mapping[str, Count],
    ) -> None:
        """What its lines don't show: its counts, its circle, its first angle and its step."""


class RoundView(PatternView):
    """A circle's or an arc's copies."""

    round = True

    def steps(self, pattern: Pattern, face: FlatFace, local: Sequence[Instance], middle: tuple[float, float],
              canvas: _Canvas, between: Callable[[int, int, str, str], None]) -> None:  # fmt: skip
        values = pattern.values
        if "diameter" in values:
            canvas.circle(middle, mm(values["diameter"]) / 2, "centre")

    def words(
        self,
        d: _Drawing,
        face: Face | None,
        values: Mapping[str, Value],
        counts: Mapping[str, Count],
    ) -> None:
        if "diameter" in values:
            d.say(
                f"on a Ø{_value(values['diameter'])} circle",
                "place.pattern.diameter",
            )
        if "step" in values:
            d.say(f"{_value(values['step'])} apart", "place.pattern.step")
        if "start" in values:
            d.say(f"the first at {_value(values['start'])}", "place.pattern.start")
        elif isinstance(face, FlatFace):
            d.say(f"the first at 0°, on +{face.axes[0].upper()} (assumed)")


class Corners(PatternView):
    key = "corners"

    measured_to_centre = False

    def inset(self, pattern: Pattern, axis: str) -> str | None:
        return f"inset_{axis}"


class Rectangle(PatternView):
    key = "rectangle"

    def steps(self, pattern: Pattern, face: FlatFace, local: Sequence[Instance], middle: tuple[float, float],
              canvas: _Canvas, between: Callable[[int, int, str, str], None]) -> None:  # fmt: skip
        values = pattern.values
        for k, step in ((0, 2), (1, 1)):
            if face.axes[k] in values:
                between(step, k, face.axes[k], _value(values[face.axes[k]]))


class Ends(PatternView):
    key = "ends"

    def inset(self, pattern: Pattern, axis: str) -> str | None:
        return "inset" if pattern.axis == axis else None


class Row(PatternView):
    key = "row"

    def steps(self, pattern: Pattern, face: FlatFace, local: Sequence[Instance], middle: tuple[float, float],
              canvas: _Canvas, between: Callable[[int, int, str, str], None]) -> None:  # fmt: skip
        values = pattern.values
        if pattern.axis in face.axes and "pitch" in values and len(local) > 1:
            between(
                1,
                face.axes.index(pattern.axis),
                "pitch",
                _value(values["pitch"]) + " apart",
            )


class Grid(PatternView):
    key = "grid"

    def steps(self, pattern: Pattern, face: FlatFace, local: Sequence[Instance], middle: tuple[float, float],
              canvas: _Canvas, between: Callable[[int, int, str, str], None]) -> None:  # fmt: skip
        values, counts = pattern.values, pattern.counts
        n1, n2 = (
            counts[f"count_{a}"].n if f"count_{a}" in counts else 1 for a in face.axes
        )
        for k, (step, n) in enumerate(((n2, n1), (1, n2))):
            name = f"pitch_{face.axes[k]}"
            if n >= 2 and name in values:
                between(step, k, name, _value(values[name]) + " apart")

    def words(
        self,
        d: _Drawing,
        face: Face | None,
        values: Mapping[str, Value],
        counts: Mapping[str, Count],
    ) -> None:
        names = sorted(n for n in counts if n.startswith("count_"))
        if names:
            d.say("a grid of " + " x ".join(_value(counts[n]) for n in names),
                     *(f"place.pattern.{n}" for n in names))  # fmt: skip


class Circle(RoundView):
    key = "circle"

    equally_spaced = True


class Arc(RoundView):
    key = "arc"


PATTERN_VIEWS: Registry[PatternView] = Registry(
    "forge_spec.views.pattern",
    PATTERN_FIELDS,
    [Corners(), Rectangle(), Ends(), Row(), Grid(), Circle(), Arc()],
    protocol=PatternView,
)
