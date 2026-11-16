"""What the oracle makes for a hole: its entry in the ``oracle`` registry (its branches moved from ``oracle.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

import math

import numpy as np
from forge_numeric import scalar as fs
from forge_spec.draft import Counterbore, Countersink, Item

from forge_checks import rounds
from forge_checks.csg import Node, Union
from forge_checks.items.oracle._shapes import _circle, _mm, _unit2, round_rim
from forge_checks.items.oracle.protocol import OracleKind
from forge_checks.place import Copy, FlatFace, Placed, RoundSide
from forge_checks.shapes import Disc, Frame, Frustum, Prism


class Hole(OracleKind):
    key = "hole"

    def node(
        self, item: Item, copy: Copy, face: FlatFace | RoundSide | None, placed: Placed
    ) -> Node:
        assert copy.span is not None
        start, depth = copy.span
        inward = -np.asarray(copy.direction, dtype=float)
        frame = Frame.along(copy.point, inward)
        radius = placed.diameters[item.id] / 2
        parts: list[Node] = [Prism(frame, Disc(radius), start, depth)]
        bore, sink = item.get("counterbore"), item.get("countersink")
        if isinstance(bore, Counterbore):
            parts.append(
                Prism(frame, Disc(_mm(bore.diameter) / 2), start, _mm(bore.depth))
            )
        if isinstance(sink, Countersink):
            wide = _mm(sink.diameter) / 2
            angle = sink.angle.made_in("deg")
            deep = (wide - radius) / fs.tan(math.radians(angle) / 2)
            parts.append(Frustum(frame, 0.0, deep, wide, radius))
            if (
                start < 0
            ):  # inside a bore, from the side's axis to the plane that touches the side (hole.md)
                parts.append(Prism(frame, Disc(wide), start, 0.0))
        return parts[0] if len(parts) == 1 else Union(tuple(parts))

    def cut_chains(self, item: Item, copy: Copy, which: str, placed: Placed, size: float
                   ) -> tuple[list[rounds.Chain], bool, list[Node], Node | None]:  # fmt: skip
        found = round_rim(item, copy, which, placed, size)
        if found is not None:
            return found
        assert copy.span is not None
        n_f = np.asarray(copy.direction, dtype=float)
        radius = placed.diameters[item.id] / 2
        wall: rounds.Boundary = rounds.Line2((-1.0, 0.0))
        bore, sink = item.get("counterbore"), item.get("countersink")
        if isinstance(bore, Counterbore):
            radius = _mm(bore.diameter) / 2
        if isinstance(sink, Countersink):
            wide = _mm(sink.diameter) / 2
            deep = (wide - placed.diameters[item.id] / 2) / fs.tan(
                math.radians(sink.angle.made_in("deg")) / 2
            )
            wall = rounds.Line2(_unit2(-deep, wide - placed.diameters[item.id] / 2))
            radius = wide
        frame = Frame.along(copy.point, n_f)
        return (
            [_circle(frame, radius, 0.0, rounds.Line2((0.0, 1.0)), wall)],
            False,
            [],
            None,
        )


ENTRY = Hole()
