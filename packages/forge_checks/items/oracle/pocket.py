"""What the oracle makes for a pocket: its entry in the ``oracle`` registry (its branches moved from ``oracle.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

import math

import numpy as np
from forge_numeric import vector as fv
from forge_spec.draft import Item

from forge_checks import rounds
from forge_checks.csg import Inter, Node
from forge_checks.items.oracle._shapes import (
    OracleError,
    _choice,
    _frame,
    _mm,
    _together,
    _vec,
    convex_pieces_of,
    copy_axes,
    flat_cut_chains,
    flat_cut_node,
)
from forge_checks.items.oracle.protocol import OracleKind
from forge_checks.place import Copy, Face, FlatFace, Placed
from forge_checks.shapes import Disc, Halfspace, Polygon, Prism, RoundRect, Shape2D


class Pocket(OracleKind):
    key = "pocket"

    def node(
        self, item: Item, copy: Copy, face: Face | None, placed: Placed
    ) -> Node:
        assert face is not None
        if _choice(item, "shape") == "profile":
            return _profile_node(item, copy, face)
        return flat_cut_node(self, item, copy, face)

    def outline(self, item: Item, axes: tuple[str, str]) -> Shape2D:
        if _choice(item, "shape") == "circle":
            return Disc(_mm(item.get("diameter")) / 2)
        if _choice(item, "shape") == "profile":
            raise OracleError(f"{item.id}: a pocket of its own outline is its convex pieces, not one outline")
        if _choice(item, "shape") == "hexagon":  # two corners on the first axis (pocket.md), anticlockwise
            h = _mm(item.get("across_flats")) / 2
            c = 2 * h / math.sqrt(3.0)
            return Polygon(((c, 0.0), (c / 2, h), (-c / 2, h), (-c, 0.0), (-c / 2, -h), (c / 2, -h)))
        r = (
            _mm(item.get("corner_radius"))
            if item.get("corner_radius") is not None
            else 0.0
        )
        return RoundRect(
            _mm(item.get("length")) / 2, _mm(item.get("width")) / 2, (r, r, r, r)
        )

    def cut_chains(self, item: Item, copy: Copy, which: str, placed: Placed, size: float
                   ) -> tuple[list[rounds.Chain], bool, list[Node], Node | None]:  # fmt: skip
        return flat_cut_chains(self, item, copy, which, placed, size)


def _profile_node(item: Item, copy: Copy, face: Face) -> Node:
    """A pocket of its own outline (pocket.md): its convex pieces, each pushed from its mouth to its depth, and each
    bulge a disc's prism meeting the half-space on the arc's side of its chord, about its point along its face's axes
    (turned with it), as an extrusion's outline is made (docs/V2-stage4.md, 6.6)."""
    assert copy.span is not None and copy.axes is not None and isinstance(face, FlatFace)
    start, depth = copy.span
    first, second = copy_axes(copy)
    flat = _frame(copy.point, first, second)
    inward = -np.asarray(copy.direction, dtype=float)
    sign = float(fv.matmul(np.asarray(flat.w), inward))
    t0, t1 = sorted((sign * start, sign * depth))
    origin = np.asarray(copy.point, dtype=float)

    def world(p: tuple[float, float]) -> np.ndarray:
        return origin + p[0] * first + p[1] * second

    pieces = convex_pieces_of(item)
    added: list[Node] = [Prism(flat, Polygon(c), t0, t1) for c in pieces.polygons]
    taken: list[Node] = []
    for bulge in pieces.bulges:
        disc = Prism(_frame(world(bulge.arc.centre), first, second), Disc(bulge.arc.radius), t0, t1)
        n = bulge.outward
        away = -(n[0] * first + n[1] * second)  # the half-space keeps the arc's side of the chord
        (added if bulge.adds else taken).append(Inter((disc, Halfspace(_vec(world(bulge.a)), _vec(away)))))
    return _together(added, taken)


ENTRY = Pocket()
