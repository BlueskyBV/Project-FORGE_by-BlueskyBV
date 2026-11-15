"""What the oracle makes for a block: its entry in the ``oracle`` registry (its branches moved from ``oracle.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item

from forge_checks import rounds
from forge_checks.csg import Node
from forge_checks.items.oracle._shapes import _mm, _vec, box_chains, standing_box
from forge_checks.items.oracle.protocol import OracleKind
from forge_checks.place import Copy, FlatFace, Hollow, Placed, RoundSide
from forge_checks.shapes import Halfspace, Prism

if TYPE_CHECKING:
    from forge_checks.oracle import _Making


class Block(OracleKind):
    key = "block"

    def node(
        self, item: Item, copy: Copy, face: FlatFace | RoundSide | None, placed: Placed
    ) -> Node:
        assert copy.axes is not None
        a1, a2 = copy.axes
        sizes = {a1: _mm(item.get("length")), a2: _mm(item.get("width"))}
        return standing_box(copy, sizes[a1], sizes[a2], _mm(item.get("height")), face)

    def hollow(self, item: Item, copy: Copy, placed: Placed) -> Node:
        hollow = placed.hollows[(item.id, copy.index)]
        return Prism.box(hollow.lo, hollow.hi)

    def wall_bands(self, body: Item, copy: Copy, placed: Placed) -> dict[str, Node]:
        hollow = placed.hollows[(body.id, copy.index)]
        lo, hi = hollow.lo, hollow.hi
        found: dict[str, Node] = {}
        for face in hollow.walls:
            k = "xyz".index(face[1])
            n = [0.0, 0.0, 0.0]
            point = [0.0, 0.0, 0.0]
            if face[0] == "+":
                n[k], point[k] = -1.0, hi[k]
            else:
                n[k], point[k] = 1.0, lo[k]
            found[face] = Halfspace(_vec(point), _vec(n))
        return found

    def rim_chains(self, target: Item, copy: Copy, which: str, pairs: tuple[tuple[str, str], ...], making: _Making,
                   whole: Node, hollow: Hollow | None) -> tuple[list[rounds.Chain], list[tuple[rounds.Chain, frozenset[str]]]]:  # fmt: skip
        return box_chains(target, copy, pairs, making, whole, hollow)


ENTRY = Block()
