"""How the confirmation views draw a revolution: its entry in the ``views`` registry (its branches moved from ``render_views.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item
from forge_spec.geometry import EPS, Vec
from forge_spec.items.views._common import outlined_body, profile_frame
from forge_spec.items.views.protocol import ViewKind
from forge_spec.placement import Instance

if TYPE_CHECKING:
    from forge_spec.render_views import _Canvas, _Drawing


class Revolution(ViewKind):
    key = "revolution"

    def homed_down_axis(self, item: Item) -> bool:
        return True

    def body(self, d: _Drawing, first: Instance, up: int | None) -> None:
        """Its outline in words, turned about its axis."""
        assert first.lo is not None and first.hi is not None and d.home is not None
        assert up is not None, "the solver stands every body along a frame axis"
        outlined_body(d, first, up, ", turned about its axis")

    def outline(
        self, d: _Drawing, canvas: _Canvas, copy: Instance, style: str, up: int | None
    ) -> None:
        """Looking down its axis, a circle at each distance from it where its outline has a corner (or an arc reaches furthest
        out or in); from the side, its half outline and that half mirrored across the axis, in the plane through the axis
        square to the line of sight."""
        if up is None:
            super().outline(d, canvas, copy, style, up)
            return
        frame = profile_frame(d.item, copy, up)
        if frame is None:
            return
        chain, corners, o, n, _, _ = frame

        def placed(p: tuple[float, float], across: int, sign: float) -> Vec:
            found = list(o)
            found[across] += sign * p[0]
            found[up] += n[up] * p[1]
            return (found[0], found[1], found[2])

        if canvas.w == up:
            centre = canvas.at(o)
            for r in sorted({round(p[0], 9) for p in corners if p[0] > EPS}):
                canvas.circle(centre, r, style)
            return
        across = canvas.u if canvas.u != up else canvas.v
        for sign in (1.0, -1.0):
            canvas.path(
                [canvas.at(placed(p, across, sign)) for p in chain],
                style,
                closed=True,
            )


ENTRY = Revolution()
