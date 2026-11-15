"""How the confirmation views draw a rib: its entry in the ``views`` registry (its branches moved from ``render_views.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item
from forge_spec.geometry import Vec
from forge_spec.items.views._common import _choice, box_anchor, box_body, box_inside
from forge_spec.items.views.protocol import ViewKind
from forge_spec.placement import Instance, Layout

if TYPE_CHECKING:
    from forge_spec.render_views import _Drawing


class Rib(ViewKind):
    key = "rib"

    def body(self, d: _Drawing, first: Instance, up: int | None) -> None:
        box_body(d, first, "rib")
        box_anchor(d, first)

    def inside(
        self, item: Item, copy: Instance, layout: Layout, up: int
    ) -> list[tuple[Vec, Vec]]:
        return box_inside(item, copy, layout)

    def box_fields(self, item: Item, a1: str, a2: str, up: int) -> dict[int, str]:
        i = "xyz".index
        along = _choice(item, "along") or a1
        other = a2 if along == a1 else a1
        return {i(along): "length", i(other): "thickness", up: "height"}


ENTRY = Rib()
