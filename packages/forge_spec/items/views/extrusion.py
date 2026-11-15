"""How the confirmation views draw an extrusion: its entry in the ``views`` registry (its branches moved from ``render_views.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item
from forge_spec.geometry import Vec
from forge_spec.items.views._common import (
    _HOME,
    _length,
    _value,
    outlined_body,
    profile_frame,
)
from forge_spec.items.views.protocol import ViewKind
from forge_spec.placement import Instance

if TYPE_CHECKING:
    from forge_spec.render_views import _Canvas, _Drawing


class Extrusion(ViewKind):
    key = "extrusion"

    def homed_down_axis(self, item: Item) -> bool:
        return True

    def body(self, d: _Drawing, first: Instance, up: int | None) -> None:
        """Its length as a dimension line along its axis, and its outline in words."""
        item, home = d.item, d.home
        assert first.lo is not None and first.hi is not None and home is not None
        assert up is not None, "the solver stands every body along a frame axis"
        lo, hi = first.lo, first.hi
        canvas, along = d.canvases[_HOME[up][0]], _HOME[up][1]
        side = canvas.v if along == "u" else canvas.u
        d.line(
            canvas,
            along,
            lo[up],
            hi[up],
            (lo[side], lo[side]),
            _value(item.get("length")),
            "length",
        )
        outlined_body(d, first, up, "")

    def outline(
        self, d: _Drawing, canvas: _Canvas, copy: Instance, style: str, up: int | None
    ) -> None:
        """Looking down its axis, its outline; from the side, its box with a line along the axis at each corner."""
        if up is None:
            super().outline(d, canvas, copy, style, up)
            return
        item = d.item
        frame = profile_frame(item, copy, up)
        if frame is None:
            return
        chain, corners, o, n, k1, k2 = frame

        def placed(p: tuple[float, float], height: float = 0.0) -> Vec:
            found = list(o)
            found[k1] += p[0]
            found[k2] += p[1]
            found[up] += n[up] * height
            return (found[0], found[1], found[2])

        length = _length(item, "length")
        if canvas.w == up:
            canvas.path([canvas.at(placed(p)) for p in chain], style, closed=True)
            return
        lo, hi = copy.lo, copy.hi
        assert lo is not None and hi is not None
        canvas.rect(canvas.at(lo), canvas.at(hi), style)
        for p in corners:
            canvas.path(
                [canvas.at(placed(p)), canvas.at(placed(p, length))],
                style,
                closed=False,
            )


ENTRY = Extrusion()
