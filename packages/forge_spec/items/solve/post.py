"""How the solver places a post: its entry in the ``solve`` registry (its branches moved from ``placement.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import (
    Item,
)
from forge_spec.geometry import (
    Vec,
    rect,
)
from forge_spec.items.solve._common import _bounds_box, _box_faces, _size
from forge_spec.items.solve.protocol import SolveKind

if TYPE_CHECKING:
    from forge_spec.geometry import Part
    from forge_spec.placement import Layout


class Post(SolveKind):
    key = "post"

    def outline_fields(
        self, item: Item, axes: tuple[str, str] | None = None, k: int | None = None
    ) -> tuple[str, ...]:
        if k is None or axes is None:
            return ("length", "width")
        return ("length",) if k == 0 else ("width",)

    def outline(
        self, item: Item, layout: Layout, axes: tuple[str, str]
    ) -> tuple[Part, ...]:
        return (rect(_size(item, "length") / 2, _size(item, "width") / 2),)

    def stand(self, item: Item, base: Vec, up: str, axes: tuple[str, str], key: tuple[str, int], layout: Layout,
              host: str | None, joined: str) -> tuple[Vec, Vec, str, dict[str, str]]:  # fmt: skip
        a1, a2 = axes
        sizes = {a1: _size(item, "length"), a2: _size(item, "width")}
        lo, hi = _bounds_box(base, up, sizes, _size(item, "height"))
        fields = {a1: "length", a2: "width", up[1]: "height"}
        layout.faces[key] = _box_faces(lo, hi, item.id, fields)
        return lo, hi, up, fields


ENTRY = Post()
