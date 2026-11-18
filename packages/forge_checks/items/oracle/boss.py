"""What the oracle makes for a boss: its entry in the ``oracle`` registry (its branches moved from ``oracle.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from forge_spec.draft import Item

from forge_checks import rounds
from forge_checks.csg import Node
from forge_checks.items.oracle._shapes import (
    _mm,
    _rim_chains,
    rod_node,
    round_footprint,
)
from forge_checks.items.oracle.protocol import OracleKind
from forge_checks.place import Copy, Face, Hollow, Placed

if TYPE_CHECKING:
    from forge_checks.oracle import _Making


class Boss(OracleKind):
    key = "boss"

    threadable = True
    rod_length = "height"

    def node(
        self, item: Item, copy: Copy, face: Face | None, placed: Placed
    ) -> Node:
        return rod_node(
            copy, face, _mm(item.get("diameter")) / 2, _mm(item.get("height"))
        )

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
            _mm(target.get("height")),
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


ENTRY = Boss()
