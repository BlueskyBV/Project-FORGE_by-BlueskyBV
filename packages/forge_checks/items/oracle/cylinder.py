"""What the oracle makes for a cylinder: its entry in the ``oracle`` registry (its branches moved from ``oracle.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

import numpy as np
from forge_spec.draft import Item

from forge_checks import rounds
from forge_checks.csg import Node
from forge_checks.items.oracle._shapes import (
    _mm,
    _rim_chains,
    _vec,
    rod_node,
    round_footprint,
)
from forge_checks.items.oracle.protocol import OracleKind
from forge_checks.place import Copy, FlatFace, Hollow, Placed, RoundSide
from forge_checks.shapes import Complement, Disc, Frame, Halfspace, Prism, Round

if TYPE_CHECKING:
    from forge_checks.oracle import _Making


class Cylinder(OracleKind):
    key = "cylinder"

    threadable = True

    def node(
        self, item: Item, copy: Copy, face: FlatFace | RoundSide | None, placed: Placed
    ) -> Node:
        return rod_node(
            copy, face, _mm(item.get("diameter")) / 2, _mm(item.get("length"))
        )

    def hollow(self, item: Item, copy: Copy, placed: Placed) -> Node:
        hollow = placed.hollows[(item.id, copy.index)]
        u = np.asarray(copy.direction, dtype=float)
        k = int(np.argmax(np.abs(u)))
        lo, hi = hollow.lo, hollow.hi
        radius = (hi[(k + 1) % 3] - lo[(k + 1) % 3]) / 2
        middle = np.array([(lo[i] + hi[i]) / 2 for i in range(3)])
        start = middle.copy()
        start[k] = lo[k] if u[k] > 0 else hi[k]
        return Prism(Frame.along(start, u), Disc(radius), 0.0, hi[k] - lo[k])

    def wall_bands(self, body: Item, copy: Copy, placed: Placed) -> dict[str, Node]:
        hollow = placed.hollows[(body.id, copy.index)]
        lo, hi = hollow.lo, hollow.hi
        found: dict[str, Node] = {}
        u = np.asarray(copy.direction, dtype=float)
        k = int(np.argmax(np.abs(u)))
        radius = (hi[(k + 1) % 3] - lo[(k + 1) % 3]) / 2
        middle = np.array([(lo[i] + hi[i]) / 2 for i in range(3)])
        near, far = middle.copy(), middle.copy()
        near[k], far[k] = (lo[k], hi[k]) if u[k] > 0 else (hi[k], lo[k])
        found["side"] = Complement(Round(Frame.along(middle, u), radius))
        if "+end" in hollow.walls:
            found["+end"] = Halfspace(_vec(far), _vec(-u))
        if "-end" in hollow.walls:
            found["-end"] = Halfspace(_vec(near), _vec(u))
        return found

    def rim_chains(self, target: Item, copy: Copy, which: str, pairs: tuple[tuple[str, str], ...], making: _Making,
                   whole: Node, hollow: Hollow | None) -> tuple[list[rounds.Chain], list[tuple[rounds.Chain, frozenset[str]]]]:  # fmt: skip
        return _rim_chains(
            target,
            copy,
            pairs,
            hollow,
            making.placed,
            _mm(target.get("diameter")) / 2,
            _mm(target.get("diameter")) / 2,
            _mm(target.get("length")),
        ), []

    def footprint_chain(
        self,
        item: Item,
        copy: Copy,
        corners: Mapping[frozenset[str], tuple[str, float]],
    ) -> rounds.Chain:
        return round_footprint(
            copy, _mm(item.get("diameter")) / 2, rounds.Line2((-1.0, 0.0))
        )


ENTRY = Cylinder()
