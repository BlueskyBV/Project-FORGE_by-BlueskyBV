"""How the solver places each pattern mode's copies: the ``solve`` role's modes (V2-stage4b-0b.md, 2), laid out as the modes of the pattern kind stage 4b.4 makes an item.

:data:`PATTERN_SOLVE` holds one entry per mode, in ``PATTERN_FIELDS``' order.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from forge_registry import Registry

from forge_spec.draft import PATTERN_FIELDS, Item, Pattern
from forge_spec.geometry import EPS, FlatFace
from forge_spec.items.solve._common import _turn
from forge_spec.problems import pointer

if TYPE_CHECKING:
    from forge_spec.placement import Layout


class PatternSolve:
    """One pattern mode, as the ``solve`` role holds it."""

    #: The mode this entry is for.
    key = ""
    #: The templates of its values and counts that run along a face's axis (``pitch_{}``: ``pitch_x`` along x).
    axis_names: tuple[str, ...] = ()
    #: Its pitch, inset and count run along its own axis (a row's, an ends pattern's).
    along_its_axis = False
    #: Its copies are placed round its circle's centre (a circle's, an arc's).
    round = False
    #: Round a side it runs along the side's axis, ``pitch`` apart (a row's: place.md, "On a round side").
    along_a_side = False
    #: Round a side it takes a step too (an arc's).
    steps_round = False
    #: Its offsets are its copies' places as they stand: at the face's corners (a corners pattern's).
    at_the_corners = False
    #: Its copies keep their place along its axis and take the anchor across it (an ends pattern's).
    pinned_along_axis = False

    def fixed_axes(self, pattern: Pattern, a1: str, a2: str) -> set[str]:
        """The face's axes its copies' places are set along by the pattern itself (where place may say nothing)."""
        return set()

    def offsets(self, pattern: Pattern, face: FlatFace, item: Item, layout: Layout, here: str, v: dict[str, float],
                n: dict[str, int], need: Callable[..., bool], a1: str, a2: str) -> list[tuple[float, float]] | None:  # fmt: skip
        layout.issue(
            "fault", here, f"unknown pattern {pattern.kind}"
        )  # pragma: no cover
        return None


class Corners(PatternSolve):
    key = "corners"
    axis_names = ("inset_{}",)
    at_the_corners = True

    def fixed_axes(self, pattern: Pattern, a1: str, a2: str) -> set[str]:
        return {a1, a2}

    def offsets(self, pattern: Pattern, face: FlatFace, item: Item, layout: Layout, here: str, v: dict[str, float],
                n: dict[str, int], need: Callable[..., bool], a1: str, a2: str) -> list[tuple[float, float]] | None:  # fmt: skip
        if face.shape != "rect":
            layout.issue("fault", here,
                         f"a {pattern.kind} pattern needs a rectangular face; {face.name} is round")  # fmt: skip
            return None
        if not need(f"inset_{a1}", f"inset_{a2}"):
            return None
        c1, c2 = face.half[0] - v[f"inset_{a1}"], face.half[1] - v[f"inset_{a2}"]
        for k, (axis, c) in enumerate(((a1, c1), (a2, c2))):
            if c <= EPS:
                layout.problem("question", here + pointer(f"inset_{axis}"),
                               f"{v[f'inset_{axis}']:g} mm in from the edges is half the face ({face.half[k]:g} mm) or "
                               "more: the corner copies would meet or cross",
                               [pattern.values[f"inset_{axis}"], *layout.values_of(face.axis_sources[k])])  # fmt: skip
        return [(s1 * c1, s2 * c2) for s1 in (-1, 1) for s2 in (-1, 1)]


class Rectangle(PatternSolve):
    key = "rectangle"
    axis_names = ("{}",)

    def offsets(self, pattern: Pattern, face: FlatFace, item: Item, layout: Layout, here: str, v: dict[str, float],
                n: dict[str, int], need: Callable[..., bool], a1: str, a2: str) -> list[tuple[float, float]] | None:  # fmt: skip
        if not need(a1, a2):
            return None
        return [(s1 * v[a1] / 2, s2 * v[a2] / 2) for s1 in (-1, 1) for s2 in (-1, 1)]


class Ends(PatternSolve):
    key = "ends"
    along_its_axis = True
    pinned_along_axis = True

    def fixed_axes(self, pattern: Pattern, a1: str, a2: str) -> set[str]:
        return {pattern.axis} if pattern.axis else set()

    def offsets(self, pattern: Pattern, face: FlatFace, item: Item, layout: Layout, here: str, v: dict[str, float],
                n: dict[str, int], need: Callable[..., bool], a1: str, a2: str) -> list[tuple[float, float]] | None:  # fmt: skip
        if face.shape != "rect":
            layout.issue("fault", here,
                         f"a {pattern.kind} pattern needs a rectangular face; {face.name} is round")  # fmt: skip
            return None
        if pattern.axis not in face.axes:
            layout.issue("fault", here + pointer("axis"),
                         f"{pattern.axis} doesn't lie in face {face.name}; it has {a1} and {a2}")  # fmt: skip
            return None
        k = 0 if pattern.axis == a1 else 1
        c = face.half[k] - v["inset"]
        if c <= EPS:
            layout.problem("question", here + pointer("inset"),
                           f"{v['inset']:g} mm in from the ends is half the face ({face.half[k]:g} mm) or more: "
                           "the two copies would meet or cross",
                           [pattern.values["inset"], *layout.values_of(face.axis_sources[k])])  # fmt: skip
        return [(-c, 0.0), (c, 0.0)] if k == 0 else [(0.0, -c), (0.0, c)]


class Row(PatternSolve):
    key = "row"
    along_its_axis = True
    along_a_side = True

    def offsets(self, pattern: Pattern, face: FlatFace, item: Item, layout: Layout, here: str, v: dict[str, float],
                n: dict[str, int], need: Callable[..., bool], a1: str, a2: str) -> list[tuple[float, float]] | None:  # fmt: skip
        if pattern.axis not in face.axes:
            layout.issue("fault", here + pointer("axis"),
                         f"{pattern.axis} doesn't lie in face {face.name}; it has {a1} and {a2}")  # fmt: skip
            return None
        count, pitch = n["count"], v["pitch"]
        steps = [(k - (count - 1) / 2) * pitch for k in range(count)]
        return (
            [(s, 0.0) for s in steps]
            if pattern.axis == a1
            else [(0.0, s) for s in steps]
        )


class Grid(PatternSolve):
    key = "grid"
    axis_names = ("pitch_{}", "count_{}")

    def offsets(self, pattern: Pattern, face: FlatFace, item: Item, layout: Layout, here: str, v: dict[str, float],
                n: dict[str, int], need: Callable[..., bool], a1: str, a2: str) -> list[tuple[float, float]] | None:  # fmt: skip
        if not need(f"count_{a1}", f"pitch_{a1}", f"count_{a2}", f"pitch_{a2}"):
            return None
        n1, n2 = n[f"count_{a1}"], n[f"count_{a2}"]
        p1, p2 = v[f"pitch_{a1}"], v[f"pitch_{a2}"]
        return [
            ((i - (n1 - 1) / 2) * p1, (j - (n2 - 1) / 2) * p2)
            for i in range(n1)
            for j in range(n2)
        ]


class Circle(PatternSolve):
    key = "circle"
    round = True

    def offsets(self, pattern: Pattern, face: FlatFace, item: Item, layout: Layout, here: str, v: dict[str, float],
                n: dict[str, int], need: Callable[..., bool], a1: str, a2: str) -> list[tuple[float, float]] | None:  # fmt: skip
        if not need("diameter"):
            return None
        count, radius = n["count"], v["diameter"] / 2
        if "start" not in v:
            layout.assume(
                here,
                f"{item.id}: the first of the {count} starts at 0 degrees, on +{a1}",
            )
        start = v.get("start", 0.0)
        step = 360 / count
        turns = [_turn(start + step * k) for k in range(count)]
        return [(radius * cos, radius * sin) for cos, sin in turns]


class Arc(PatternSolve):
    key = "arc"
    round = True
    steps_round = True

    def offsets(self, pattern: Pattern, face: FlatFace, item: Item, layout: Layout, here: str, v: dict[str, float],
                n: dict[str, int], need: Callable[..., bool], a1: str, a2: str) -> list[tuple[float, float]] | None:  # fmt: skip
        if not need("diameter"):
            return None
        count, radius = n["count"], v["diameter"] / 2
        if "start" not in v:
            layout.assume(
                here,
                f"{item.id}: the first of the {count} starts at 0 degrees, on +{a1}",
            )
        start = v.get("start", 0.0)
        step = v["step"]
        turns = [_turn(start + step * k) for k in range(count)]
        return [(radius * cos, radius * sin) for cos, sin in turns]


PATTERN_SOLVE: Registry[PatternSolve] = Registry(
    "forge_spec.solve.pattern",
    PATTERN_FIELDS,
    [Corners(), Rectangle(), Ends(), Row(), Grid(), Circle(), Arc()],
    protocol=PatternSolve,
)
