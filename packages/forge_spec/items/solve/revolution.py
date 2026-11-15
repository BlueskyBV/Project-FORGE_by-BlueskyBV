"""How the solver places a revolution: its entry in the ``solve`` registry (its branches moved from ``placement.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from forge_spec.draft import (
    Item,
    On,
)
from forge_spec.geometry import (
    EPS,
    FlatFace,
    Turned,
    Vec,
)
from forge_spec.items.solve._common import Ends, Face, _profile_shape, profiled
from forge_spec.items.solve.protocol import SolveKind
from forge_spec.outline import Shape, turned_depth, turned_extremes
from forge_spec.problems import pointer
from forge_spec.schema import FACE_AXES

if TYPE_CHECKING:
    from forge_spec.geometry import FlatFace
    from forge_spec.placement import Layout


class Revolution(SolveKind):
    key = "revolution"

    profiled = True
    axial = True

    def stand(self, item: Item, base: Vec, up: str, axes: tuple[str, str], key: tuple[str, int], layout: Layout,
              host: str | None, joined: str) -> tuple[Vec, Vec, str, dict[str, str]]:  # fmt: skip
        lo, hi = profiled(
            item, base, up, axes, key, layout, self._ends(item, up, key, layout)
        )
        return lo, hi, "+end", {}

    def _ends(self, item: Item, up: str, key: tuple[str, int], layout: Layout) -> Ends:
        def ends(shape: Shape, point: Callable[[float, float, float], Vec], faces: dict[str, Face],
                 sources: tuple[tuple[str, str], ...], down: str, lows: tuple[float, float],
                 highs: tuple[float, float]) -> tuple[Vec, Vec]:  # fmt: skip
            (_, l2), (h1, h2) = lows, highs
            for name, top in (("+end", True), ("-end", False)):
                end = turned_extremes(shape, top)
                if end is None:
                    layout.close(key, name, "fault", f"{item.id}'s outline doesn't run straight across its axis at its "
                                 f"{'greatest' if top else 'least'} height: it has no flat {name}")  # fmt: skip
                    continue
                height, inner, outer = end
                normal = up if top else down
                ring = inner > EPS
                faces[name] = FlatFace(name, point(0.0, 0.0, height), normal, FACE_AXES[normal],
                                       "annulus" if ring else "disc", (outer, outer), inner if ring else 0.0,
                                       turned_depth(shape, top, inner, outer)[1], depth_model=Turned(shape, top),
                                       axis_sources=(sources, sources), depth_sources=sources)  # fmt: skip
            return (point(-h1, -h1, l2), point(h1, h1, h2))

        return ends

    def reaches(
        self, item: Item
    ) -> tuple[tuple[float, float], tuple[float, float]] | None:
        shape = _profile_shape(item)
        if shape is None:
            return None
        _, (h1, _) = shape.box()
        return (-h1, h1), (-h1, h1)

    def footing(self, item: Item) -> Shape | None:
        shape = _profile_shape(item)
        if shape is None:
            return None
        end = turned_extremes(shape, False)
        if end is None or abs(end[0]) > EPS:
            return None
        return Shape.disc((0.0, 0.0), end[2])

    def check_shape(self, item: Item, at: str, layout: Layout) -> None:
        shape = _profile_shape(item)
        if shape is not None:
            (lo, _hi) = shape.box()
            if lo[0] < -EPS:
                layout.issue("fault", at + pointer("profile"),
                             f"a revolution's outline is a half outline: its first coordinate, the distance from the axis, is "
                             f"never below 0, but it reaches {-lo[0]:g} mm across the axis")  # fmt: skip
            elif isinstance(item.get("on"), On):
                if lo[1] < -EPS:
                    layout.issue("fault", at + pointer("profile"), f"standing on a face, {item.id}'s outline reaches "
                                 f"{-lo[1]:g} mm below it: nothing reaches behind the face it stands on")  # fmt: skip
                elif self.footing(item) is None:
                    layout.issue("fault", at + pointer("profile"), f"standing on a face, {item.id} must meet it: its "
                                 "outline runs straight across the axis at height 0")  # fmt: skip


ENTRY = Revolution()
