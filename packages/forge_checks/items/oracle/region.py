"""What the oracle makes for a region: its entry in the ``oracle`` registry (its branches moved from ``oracle.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item

from forge_checks.csg import Node
from forge_checks.items.oracle._shapes import _mm, standing_box
from forge_checks.items.oracle.protocol import OracleKind
from forge_checks.place import Copy, Face, Placed

if TYPE_CHECKING:
    from forge_checks.oracle import Step, _Making


class Region(OracleKind):
    key = "region"

    def node(
        self, item: Item, copy: Copy, face: Face | None, placed: Placed
    ) -> Node:
        assert copy.axes is not None
        a1, a2 = copy.axes
        sizes = {a1: _mm(item.get("length")), a2: _mm(item.get("width"))}
        return standing_box(copy, sizes[a1], sizes[a2], _mm(item.get("height")), face)

    def copy_steps(
        self, item: Item, copy: Copy, face: Face | None, making: _Making
    ) -> list[Step]:
        """A region's envelope, in the outer form alone: it is designed later, within it."""
        return [
            making.step(
                item,
                copy,
                True,
                self.node(item, copy, face, making.placed),
                envelope=True,
            )
        ]

    def left_unchecked(self, item: Item) -> str | None:
        return "a region is designed later, within its envelope"


ENTRY = Region()
