"""How the confirmation views draw a tube: its entry in the ``views`` registry (its branches moved from ``render_views.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item
from forge_spec.geometry import Vec
from forge_spec.items.views._common import (
    _length,
    _round,
    _value,
    rod_body,
    round_outline,
)
from forge_spec.items.views.protocol import ViewKind
from forge_spec.placement import Instance, Layout

if TYPE_CHECKING:
    from forge_spec.render_views import _Canvas, _Drawing


class Tube(ViewKind):
    key = "tube"

    def homed_down_axis(self, item: Item) -> bool:
        return True

    def body(self, d: _Drawing, first: Instance, up: int | None) -> None:
        item = d.item
        rod_body(d, first, up, "length", (f"tube Ø{_value(item.get('outer_diameter'))} outside, "
                                          f"Ø{_value(item.get('inner_diameter'))} bore", "outer_diameter", "inner_diameter"))  # fmt: skip

    def outline(
        self, d: _Drawing, canvas: _Canvas, copy: Instance, style: str, up: int | None
    ) -> None:
        if up is None:
            super().outline(d, canvas, copy, style, up)
            return
        item = d.item
        lo, hi = copy.lo, copy.hi
        assert lo is not None and hi is not None
        across = (up + 1) % 3
        r = (hi[across] - lo[across]) / 2
        axial = round_outline(canvas, copy, style, up, r, r)
        length = hi[up] - lo[up]
        inner = _length(item, "inner_diameter") / 2
        _round(canvas, copy.origin, copy.normal, length, inner, inner, start_style=style if axial else None,
               side_style=None if axial else "hidden", end_style=None)  # fmt: skip

    def inside(
        self, item: Item, copy: Instance, layout: Layout, up: int
    ) -> list[tuple[Vec, Vec]]:
        return []


ENTRY = Tube()
