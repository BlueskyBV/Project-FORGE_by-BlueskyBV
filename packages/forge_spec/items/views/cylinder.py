"""How the confirmation views draw a cylinder: its entry in the ``views`` registry (its branches moved from ``render_views.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item
from forge_spec.geometry import Vec
from forge_spec.items.views._common import _mid, _value, rod_body, round_outline
from forge_spec.items.views.protocol import ViewKind
from forge_spec.placement import Instance

if TYPE_CHECKING:
    from forge_spec.render_views import _Canvas, _Drawing


class Cylinder(ViewKind):
    key = "cylinder"

    def homed_down_axis(self, item: Item) -> bool:
        return True

    def body(self, d: _Drawing, first: Instance, up: int | None) -> None:
        rod_body(
            d,
            first,
            up,
            "length",
            (f"cylinder Ø{_value(d.item.get('diameter'))}", "diameter"),
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

    def cavity(self, d: _Drawing, canvas: _Canvas, copy: Instance, cavity: tuple[Vec, Vec], style: str,
               open_faces: set[str], up: int | None) -> None:  # fmt: skip
        if up is None or canvas.w != up:
            super().cavity(d, canvas, copy, cavity, style, open_faces, up)
            return
        lo, hi = cavity
        end = "+end" if copy.normal[up] * canvas.frame.facing > 0 else "-end"
        r = (hi[(up + 1) % 3] - lo[(up + 1) % 3]) / 2
        canvas.circle(
            canvas.at(_mid(lo, hi)), r, style if end in open_faces else "hidden"
        )


ENTRY = Cylinder()
