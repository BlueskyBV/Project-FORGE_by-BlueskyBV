"""How the confirmation views draw a boss: its entry in the ``views`` registry (its branches moved from ``render_views.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item
from forge_spec.items.views._common import _value, rod_body, round_outline
from forge_spec.items.views.protocol import ViewKind
from forge_spec.placement import Instance

if TYPE_CHECKING:
    from forge_spec.render_views import _Canvas, _Drawing


class Boss(ViewKind):
    key = "boss"

    def homed_down_axis(self, item: Item) -> bool:
        return True

    def body(self, d: _Drawing, first: Instance, up: int | None) -> None:
        rod_body(
            d,
            first,
            up,
            "height",
            (f"boss Ø{_value(d.item.get('diameter'))}", "diameter"),
        )

    def outline(
        self, d: _Drawing, canvas: _Canvas, copy: Instance, style: str, up: int | None
    ) -> None:
        if up is None:
            super().outline(d, canvas, copy, style, up)
            return
        lo, hi = copy.lo, copy.hi
        assert lo is not None and hi is not None
        across = (up + 1) % 3
        r = (hi[across] - lo[across]) / 2
        round_outline(canvas, copy, style, up, r, r)


ENTRY = Boss()
