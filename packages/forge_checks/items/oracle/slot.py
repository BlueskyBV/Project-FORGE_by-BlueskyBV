"""What the oracle makes for a slot: its entry in the ``oracle`` registry (its branches moved from ``oracle.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.draft import Item

from forge_checks import rounds
from forge_checks.csg import Node
from forge_checks.items.oracle._shapes import (
    _choice,
    _mm,
    flat_cut_chains,
    flat_cut_node,
)
from forge_checks.items.oracle.protocol import OracleKind
from forge_checks.place import Copy, FlatFace, Placed, RoundSide
from forge_checks.shapes import RoundRect, Shape2D


class Slot(OracleKind):
    key = "slot"

    def node(
        self, item: Item, copy: Copy, face: FlatFace | RoundSide | None, placed: Placed
    ) -> Node:
        assert face is not None
        return flat_cut_node(self, item, copy, face)

    def outline(self, item: Item, axes: tuple[str, str]) -> Shape2D:
        length, width = _mm(item.get("length")), _mm(item.get("width"))
        along_first = _choice(item, "along") == axes[0]
        h1, h2 = (length / 2, width / 2) if along_first else (width / 2, length / 2)
        r = width / 2 if _choice(item, "ends") == "round" else 0.0
        return RoundRect(h1, h2, (r, r, r, r))

    def cut_chains(self, item: Item, copy: Copy, which: str, placed: Placed, size: float
                   ) -> tuple[list[rounds.Chain], bool, list[Node], Node | None]:  # fmt: skip
        return flat_cut_chains(self, item, copy, which, placed, size)


ENTRY = Slot()
