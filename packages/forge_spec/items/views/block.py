"""How the confirmation views draw a block: its entry in the ``views`` registry (its branches moved from ``render_views.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item
from forge_spec.geometry import Vec
from forge_spec.items.views._common import _AXES, box_anchor, box_body, box_inside
from forge_spec.items.views.protocol import ViewKind
from forge_spec.placement import Instance, Layout

if TYPE_CHECKING:
    from forge_spec.render_views import _Canvas, _Drawing


class Block(ViewKind):
    key = "block"

    def body(self, d: _Drawing, first: Instance, up: int | None) -> None:
        box_body(d, first, "block")
        box_anchor(d, first)

    def inside(
        self, item: Item, copy: Instance, layout: Layout, up: int
    ) -> list[tuple[Vec, Vec]]:
        return box_inside(item, copy, layout)

    def cavity(self, d: _Drawing, canvas: _Canvas, copy: Instance, cavity: tuple[Vec, Vec], style: str,
               open_faces: set[str], up: int | None) -> None:  # fmt: skip
        lo, hi = cavity
        looking_at = ("+" if canvas.frame.facing > 0 else "-") + _AXES[canvas.w]
        seen = looking_at in open_faces
        canvas.rect(canvas.at(lo), canvas.at(hi), style if seen else "hidden")


ENTRY = Block()
