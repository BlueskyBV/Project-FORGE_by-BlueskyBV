"""How the confirmation views draw a tab: its entry in the ``views`` registry (its branches moved from ``render_views.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from forge_numeric import scalar as fs

from forge_spec.draft import Item
from forge_spec.geometry import EPS, Vec
from forge_spec.items.views._common import (
    _choice,
    _length,
    box_anchor,
    box_body,
    box_inside,
)
from forge_spec.items.views.protocol import ViewKind
from forge_spec.placement import Instance, Layout

if TYPE_CHECKING:
    from forge_spec.render_views import _Canvas, _Drawing


class Tab(ViewKind):
    key = "tab"

    def body(self, d: _Drawing, first: Instance, up: int | None) -> None:
        box_body(
            d, first, "tab (round end)" if _choice(d.item, "end") == "round" else "tab"
        )
        box_anchor(d, first)

    def box_fields(self, item: Item, a1: str, a2: str, up: int) -> dict[int, str]:
        i = "xyz".index
        thin = _choice(item, "thickness_along") or a2
        wide = a1 if thin == a2 else a2
        return {i(thin): "thickness", i(wide): "width", up: "length"}

    def outline(
        self, d: _Drawing, canvas: _Canvas, copy: Instance, style: str, up: int | None
    ) -> None:
        item = d.item
        if not (_choice(item, "end") == "round" and up is not None):
            super().outline(d, canvas, copy, style, up)
            return
        thin = next(k for k, name in d._box_fields(copy).items() if name == "thickness")
        r = _length(item, "width") / 2
        # All round end, it is a half disc.
        straight = max(_length(item, "length") - r, 0.0)
        if canvas.w == thin:
            b = canvas.at(copy.origin)
            du, dv = copy.normal[canvas.u], copy.normal[canvas.v]
            pu, pv = -dv, du
            bend = (b[0] + du * straight, b[1] + dv * straight)
            arc = [(bend[0] + r * (-fs.cos(t) * pu + fs.sin(t) * du),
                    bend[1] + r * (-fs.cos(t) * pv + fs.sin(t) * dv))
                   for t in (math.pi * s / 32 for s in range(33))]  # fmt: skip
            canvas.path(
                [
                    (b[0] - r * pu, b[1] - r * pv),
                    *arc,
                    (b[0] + r * pu, b[1] + r * pv),
                ],
                style,
                closed=True,
            )
            return
        super().outline(d, canvas, copy, style, up)

    def inside(
        self, item: Item, copy: Instance, layout: Layout, up: int
    ) -> list[tuple[Vec, Vec]]:
        if _choice(item, "end") != "round":
            return box_inside(item, copy, layout)
        if (
            layout.cavities.get((item.id, copy.index)) is not None
            or item.id in layout.shells
        ):
            return []
        lo, hi = copy.lo, copy.hi
        assert lo is not None and hi is not None
        base, direction = copy.origin, copy.normal
        # its square part, short of the round end
        straight = _length(item, "length") - _length(item, "width") / 2
        if straight <= EPS:
            return []
        blo, bhi = list(lo), list(hi)
        far = base[up] + direction[up] * straight
        blo[up], bhi[up] = min(base[up], far), max(base[up], far)
        return [((blo[0], blo[1], blo[2]), (bhi[0], bhi[1], bhi[2]))]


ENTRY = Tab()
