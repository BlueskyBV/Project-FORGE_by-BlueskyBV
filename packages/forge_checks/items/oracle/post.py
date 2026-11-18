"""What the oracle makes for a post: its entry in the ``oracle`` registry (its branches moved from ``oracle.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item

from forge_checks import rounds
from forge_checks.csg import Node
from forge_checks.items.oracle._shapes import _mm, box_chains, standing_box
from forge_checks.items.oracle.protocol import OracleKind
from forge_checks.place import Copy, Face, Hollow, Placed

if TYPE_CHECKING:
    from forge_checks.oracle import _Making


class Post(OracleKind):
    key = "post"

    def node(
        self, item: Item, copy: Copy, face: Face | None, placed: Placed
    ) -> Node:
        assert copy.axes is not None
        a1, a2 = copy.axes
        sizes = {a1: _mm(item.get("length")), a2: _mm(item.get("width"))}
        return standing_box(copy, sizes[a1], sizes[a2], _mm(item.get("height")), face)

    def rim_chains(self, target: Item, copy: Copy, which: str, pairs: tuple[tuple[str, str], ...], making: _Making,
                   whole: Node, hollow: Hollow | None) -> tuple[list[rounds.Chain], list[tuple[rounds.Chain, frozenset[str]]]]:  # fmt: skip
        return box_chains(target, copy, pairs, making, whole, hollow)


ENTRY = Post()
