"""How the solver places a rib: its entry in the ``solve`` registry (its branches moved from ``placement.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import (
    Item,
)
from forge_spec.geometry import (
    Vec,
    rect,
)
from forge_spec.items.solve._common import (
    _bounds_box,
    _box_faces,
    _choice_of,
    _oriented,
    _size,
)
from forge_spec.items.solve.protocol import SolveKind

if TYPE_CHECKING:
    from forge_spec.geometry import Part
    from forge_spec.placement import Layout


class Rib(SolveKind):
    key = "rib"

    def outline_fields(
        self, item: Item, axes: tuple[str, str] | None = None, k: int | None = None
    ) -> tuple[str, ...]:
        if k is None or axes is None:
            return ("length", "thickness")
        along = _choice_of(item, "along") == axes[k]
        return ("length",) if along else ("thickness",)

    def outline(
        self, item: Item, layout: Layout, axes: tuple[str, str]
    ) -> tuple[Part, ...]:
        return (rect(*_oriented(axes, _choice_of(item, "along"), _size(item, "length") / 2,
                                _size(item, "thickness") / 2)),)  # fmt: skip

    def turnable(
        self, item: Item, layout: Layout, axes: tuple[str, str]
    ) -> tuple[float, float, float] | None:
        h1, h2 = _oriented(
            axes,
            _choice_of(item, "along"),
            _size(item, "length") / 2,
            _size(item, "thickness") / 2,
        )
        return h1, h2, 0.0

    def stand(self, item: Item, base: Vec, up: str, axes: tuple[str, str], key: tuple[str, int], layout: Layout,
              host: str | None, joined: str) -> tuple[Vec, Vec, str, dict[str, str]]:  # fmt: skip
        a1, a2 = axes
        along = _choice_of(item, "along") or a1
        other = a2 if along == a1 else a1
        sizes = {along: _size(item, "length"), other: _size(item, "thickness")}
        lo, hi = _bounds_box(base, up, sizes, _size(item, "height"))
        fields = {along: "length", other: "thickness", up[1]: "height"}
        layout.faces[key] = _box_faces(lo, hi, item.id, fields)
        return lo, hi, up, fields


ENTRY = Rib()
