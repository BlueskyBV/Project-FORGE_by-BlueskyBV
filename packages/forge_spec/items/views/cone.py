"""How the confirmation views draw a cone: its entry in the ``views`` registry (its branches moved from ``render_views.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item
from forge_spec.geometry import Vec
from forge_spec.items.views._common import (
    _length,
    _value,
    rod_body,
    round_inside,
    round_outline,
)
from forge_spec.items.views.protocol import ViewKind
from forge_spec.placement import Instance, Layout

if TYPE_CHECKING:
    from forge_spec.render_views import _Canvas, _Drawing


class Cone(ViewKind):
    key = "cone"

    def homed_down_axis(self, item: Item) -> bool:
        return True

    def body(self, d: _Drawing, first: Instance, up: int | None) -> None:
        item = d.item
        rod_body(d, first, up, "length", (f"cone Ø{_value(item.get('base_diameter'))} at the base to "
                                          f"Ø{_value(item.get('top_diameter'))} at the top", "base_diameter", "top_diameter"))  # fmt: skip

    def outline(
        self, d: _Drawing, canvas: _Canvas, copy: Instance, style: str, up: int | None
    ) -> None:
        if up is None:
            super().outline(d, canvas, copy, style, up)
            return
        item = d.item
        lo, hi = copy.lo, copy.hi
        assert lo is not None and hi is not None
        # A cone's ends are as its fields give them: its bounds are as wide as the wider end.
        r0 = _length(item, "base_diameter") / 2
        r1 = _length(item, "top_diameter") / 2
        round_outline(canvas, copy, style, up, r0, r1)

    def inside(
        self, item: Item, copy: Instance, layout: Layout, up: int
    ) -> list[tuple[Vec, Vec]]:
        if (
            layout.cavities.get((item.id, copy.index)) is not None
            or item.id in layout.shells
        ):
            return []
        # the square in its narrower end, all its length
        across = min(_length(item, "base_diameter"), _length(item, "top_diameter")) / 2
        return round_inside(copy, up, across)


ENTRY = Cone()
