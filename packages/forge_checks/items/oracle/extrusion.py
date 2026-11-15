"""What the oracle makes for a extrusion: its entry in the ``oracle`` registry (its branches moved from ``oracle.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

import numpy as np
from forge_spec.draft import Item

from forge_checks.csg import Inter, Node
from forge_checks.items.oracle._shapes import (
    Array,
    _axis,
    _frame,
    _mm,
    _standing_prism,
    _together,
    _vec,
    convex_pieces_of,
)
from forge_checks.items.oracle.protocol import OracleKind
from forge_checks.place import Copy, FlatFace, Placed, RoundSide
from forge_checks.shapes import Disc, Halfspace, Polygon, Prism


class Extrusion(OracleKind):
    key = "extrusion"

    outline_rounded = True

    def node(
        self, item: Item, copy: Copy, face: FlatFace | RoundSide | None, placed: Placed
    ) -> Node:
        return _extrusion_node(item, copy, face)


def _extrusion_node(item: Item, copy: Copy, face: FlatFace | RoundSide | None) -> Node:
    """An extrusion: its outline's convex pieces pushed ``length`` along it (docs/V2-stage4.md, 6.6).

    Each polygon a :class:`Prism`; each bulge a disc's prism meeting the
    half-space on the arc's side of its chord.
    """
    assert copy.axes is not None
    pieces = convex_pieces_of(item)
    length = _mm(item.get("length"))
    first, second = _axis(copy.axes[0]), _axis(copy.axes[1])
    u = np.asarray(copy.direction, dtype=float)
    frame = _frame(copy.point, first, second)
    t0, t1 = sorted((0.0, float(np.asarray(frame.w) @ u) * length))
    origin = np.asarray(copy.point, dtype=float)

    def world(p: tuple[float, float]) -> Array:
        return origin + p[0] * first + p[1] * second

    added: list[Node] = [
        _standing_prism(copy, Polygon(c), length, face) for c in pieces.polygons
    ]
    taken: list[Node] = []
    for bulge in pieces.bulges:
        disc = Prism(
            _frame(world(bulge.arc.centre), first, second),
            Disc(bulge.arc.radius),
            t0,
            t1,
        )
        n = bulge.outward
        away = -(
            n[0] * first + n[1] * second
        )  # the half-space keeps the arc's side of the chord
        node = Inter((disc, Halfspace(_vec(world(bulge.a)), _vec(away))))
        (added if bulge.adds else taken).append(node)
    return _together(added, taken)


ENTRY = Extrusion()
