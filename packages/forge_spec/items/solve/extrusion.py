"""How the solver places an extrusion: its entry in the ``solve`` registry (its branches moved from ``placement.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from forge_spec.draft import (
    Item,
)
from forge_spec.geometry import (
    FlatFace,
    Vec,
)
from forge_spec.items.solve._common import Ends, Face, _profile_shape, _size, profiled
from forge_spec.items.solve.protocol import SolveKind
from forge_spec.outline import Shape
from forge_spec.schema import FACE_AXES

if TYPE_CHECKING:
    from forge_spec.geometry import FlatFace
    from forge_spec.placement import Layout


class Extrusion(SolveKind):
    key = "extrusion"

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
            (l1, l2), (h1, h2) = lows, highs
            length = _size(item, "length")
            c1, c2 = (l1 + h1) / 2, (l2 + h2) / 2
            outline = shape.moved(-c1, -c2)
            half = ((h1 - l1) / 2, (h2 - l2) / 2)
            lengths = ((item.id, "length"),)
            for name, height, normal in (("+end", length, up), ("-end", 0.0, down)):
                faces[name] = FlatFace(name, point(c1, c2, height), normal, FACE_AXES[normal], "profile", half, 0.0,
                                       length, axis_sources=(sources, sources), depth_sources=lengths,
                                       profile=outline, drawn_about=(c1, c2))  # fmt: skip
            return (point(l1, l2, 0.0), point(h1, h2, length))

        return ends

    def reaches(
        self, item: Item
    ) -> tuple[tuple[float, float], tuple[float, float]] | None:
        shape = _profile_shape(item)
        if shape is None:
            return None
        (l1, l2), (h1, h2) = shape.box()
        return (l1, h1), (l2, h2)

    def footing(self, item: Item) -> Shape | None:
        return _profile_shape(item)


ENTRY = Extrusion()
