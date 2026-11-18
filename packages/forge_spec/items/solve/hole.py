"""How the solver places a hole: its entry in the ``solve`` registry (its branches moved from ``placement.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from forge_numeric import scalar as fs

from forge_spec.draft import (
    Counterbore,
    Countersink,
    Fit,
    Item,
)
from forge_spec.ends import Blind, end_of
from forge_spec.geometry import (
    EPS,
    disc,
)
from forge_spec.items.solve._common import degrees, mm
from forge_spec.items.solve.protocol import SolveKind
from forge_spec.problems import pointer
from forge_spec.tables import lookup_fit
from forge_spec.values import Value

if TYPE_CHECKING:
    from forge_spec.geometry import Part
    from forge_spec.placement import Layout


class Hole(SolveKind):
    key = "hole"
    on_ball = True

    round_foot = True
    on_round_side = True

    def outline_fields(
        self, item: Item, axes: tuple[str, str] | None = None, k: int | None = None
    ) -> tuple[str, ...]:
        return ("diameter", "counterbore", "countersink")

    def outline(
        self, item: Item, layout: Layout, axes: tuple[str, str]
    ) -> tuple[Part, ...]:
        d = layout.diameters.get(item.id, 0.0)
        for extra in (item.get("counterbore"), item.get("countersink")):
            if isinstance(extra, (Counterbore, Countersink)):
                d = max(d, mm(extra.diameter))
        return (disc(d / 2),)

    def resolve_diameter(self, item: Item, at: str, layout: Layout) -> None:
        diameter = item.get("diameter")
        if isinstance(diameter, Value):
            layout.diameters[item.id] = mm(diameter)
        elif isinstance(diameter, Fit):
            entry = lookup_fit(diameter.fit, diameter.for_, diameter.grade or "normal")
            if entry is None:
                layout.issue("fault", at + pointer("diameter"),
                             f"no {diameter.fit} entry for {diameter.for_!r} in Forge's tables")  # fmt: skip
            else:
                layout.diameters[item.id] = entry.size_mm

    def check_shape(self, item: Item, at: str, layout: Layout) -> None:
        end = end_of(item)
        bore, sink, depth = (
            item.get("counterbore"),
            item.get("countersink"),
            end.depth if isinstance(end, Blind) else None,
        )
        if isinstance(bore, Counterbore) and isinstance(sink, Countersink):
            layout.issue(
                "unable",
                at,
                "a hole with both a counterbore and a countersink isn't built yet",
            )
        if (
            isinstance(bore, Counterbore)
            and isinstance(depth, Value)
            and mm(bore.depth) >= mm(depth) - EPS
        ):
            layout.problem("question", at + pointer("counterbore"),
                           f"the counterbore ({mm(bore.depth):g} mm deep) is as deep as the hole ({mm(depth):g} mm): "
                           "there's no hole left below it", [bore.depth, depth])  # fmt: skip
        hole = layout.diameters.get(item.id)
        if (
            isinstance(sink, Countersink)
            and isinstance(depth, Value)
            and hole is not None
        ):
            cone = (
                (mm(sink.diameter) - hole)
                / 2
                / fs.tan(math.radians(degrees(sink.angle)) / 2)
            )
            if cone >= mm(depth) - EPS:
                layout.problem("question", at + pointer("countersink"),
                               f"the countersink ({cone:g} mm deep) is as deep as the hole ({mm(depth):g} mm): "
                               "there's no hole left below it",
                               [sink.diameter, sink.angle, item.get("diameter"), depth])  # fmt: skip


ENTRY = Hole()
