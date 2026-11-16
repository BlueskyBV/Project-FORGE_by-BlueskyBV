"""How the confirmation views draw a sphere: its entry in the ``views`` registry (its branches moved from ``render_views.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from forge_numeric import scalar as fs

from forge_spec.draft import Item
from forge_spec.geometry import Vec
from forge_spec.items.views._common import _choice, _mid, _value, round_spans
from forge_spec.items.views.protocol import ViewKind
from forge_spec.placement import Instance, Layout

if TYPE_CHECKING:
    from forge_spec.render_views import _Canvas, _Drawing


class Sphere(ViewKind):
    key = "sphere"

    def homed_down_axis(self, item: Item) -> bool:
        return _choice(item, "portion") == "upper_half"

    def body(self, d: _Drawing, first: Instance, up: int | None) -> None:
        item, home = d.item, d.home
        assert first.lo is not None and first.hi is not None and home is not None
        lo, hi = first.lo, first.hi
        r = round_spans(d, first, up, whole=_choice(item, "portion") != "upper_half")
        whole = _choice(item, "portion") != "upper_half"
        d.say(
            f"{'ball' if whole else 'dome'} Ø{_value(item.get('diameter'))}",
            "diameter",
        )
        centre = home.at(_mid(lo, hi) if whole or home.w != up else first.origin)
        d.anchor = (
            centre[0] + r * math.sqrt(0.5),
            centre[1] + r * math.sqrt(0.5),
        )

    def outline(
        self, d: _Drawing, canvas: _Canvas, copy: Instance, style: str, up: int | None
    ) -> None:
        item = d.item
        lo, hi = copy.lo, copy.hi
        assert lo is not None and hi is not None
        r = max(hi[k] - lo[k] for k in range(3)) / 2
        if _choice(item, "portion") != "upper_half" or up is None:
            canvas.circle(canvas.at(_mid(lo, hi)), r, style)
        elif canvas.w == up:
            canvas.circle(canvas.at(copy.origin), r, style)
        else:
            b = canvas.at(copy.origin)
            du, dv = copy.normal[canvas.u], copy.normal[canvas.v]
            pu, pv = -dv, du
            arc = [(b[0] + r * (fs.cos(t) * pu + fs.sin(t) * du), b[1] + r * (fs.cos(t) * pv + fs.sin(t) * dv))
                   for t in (math.pi * s / 32 for s in range(33))]  # fmt: skip
            canvas.path(arc, style, closed=True)

    def inside(
        self, item: Item, copy: Instance, layout: Layout, up: int
    ) -> list[tuple[Vec, Vec]]:
        if (
            layout.cavities.get((item.id, copy.index)) is not None
            or item.id in layout.shells
        ):
            return []
        lo, hi = copy.lo, copy.hi
        assert lo is not None and hi is not None
        base, direction = copy.origin, copy.normal
        r = (hi[(up + 1) % 3] - lo[(up + 1) % 3]) / 2
        if _choice(item, "portion") != "upper_half":
            half = r / math.sqrt(3)
            c = _mid(lo, hi)
            return [
                (
                    (c[0] - half, c[1] - half, c[2] - half),
                    (c[0] + half, c[1] + half, c[2] + half),
                )
            ]
        blo, bhi = (
            [base[k] - r / 2 for k in range(3)],
            [base[k] + r / 2 for k in range(3)],
        )
        far = base[up] + direction[up] * r / math.sqrt(2)
        blo[up], bhi[up] = min(base[up], far), max(base[up], far)
        return [((blo[0], blo[1], blo[2]), (bhi[0], bhi[1], bhi[2]))]


ENTRY = Sphere()
