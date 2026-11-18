"""What the oracle makes for a pocket: its entry in the ``oracle`` registry (its branches moved from ``oracle.py`` at stage 4b.0b's step 3)."""

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
from forge_checks.place import Copy, Face, Placed
from forge_checks.shapes import Disc, RoundRect, Shape2D


class Pocket(OracleKind):
    key = "pocket"

    def node(
        self, item: Item, copy: Copy, face: Face | None, placed: Placed
    ) -> Node:
        assert face is not None
        return flat_cut_node(self, item, copy, face)

    def outline(self, item: Item, axes: tuple[str, str]) -> Shape2D:
        if _choice(item, "shape") == "circle":
            return Disc(_mm(item.get("diameter")) / 2)
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


ENTRY = Pocket()
