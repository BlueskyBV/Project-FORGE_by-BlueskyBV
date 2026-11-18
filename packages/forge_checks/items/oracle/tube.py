"""What the oracle makes for a tube: its entry in the ``oracle`` registry (its branches moved from ``oracle.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from forge_spec.draft import Item

from forge_checks import rounds
from forge_checks.csg import Minus, Node
from forge_checks.items.oracle._shapes import _mm, _rim_chains
from forge_checks.items.oracle.protocol import OracleKind
from forge_checks.place import Copy, Face, Hollow, Placed
from forge_checks.shapes import Disc, Frame, Prism

if TYPE_CHECKING:
    from forge_checks.oracle import _Making


class Tube(OracleKind):
    key = "tube"

    def node(
        self, item: Item, copy: Copy, face: Face | None, placed: Placed
    ) -> Node:
        u = np.asarray(copy.direction, dtype=float)
        frame = Frame.along(copy.point, u)
        length = _mm(item.get("length"))
        outer = Prism(frame, Disc(_mm(item.get("outer_diameter")) / 2), 0.0, length)
        return Minus(
            outer, Prism(frame, Disc(_mm(item.get("inner_diameter")) / 2), 0.0, length)
        )

    def rim_chains(self, target: Item, copy: Copy, which: str, pairs: tuple[tuple[str, str], ...], making: _Making,
                   whole: Node, hollow: Hollow | None) -> tuple[list[rounds.Chain], list[tuple[rounds.Chain, frozenset[str]]]]:  # fmt: skip
        return _rim_chains(
            target,
            copy,
            pairs,
            hollow,
            making.placed,
            _mm(target.get("outer_diameter")) / 2,
            _mm(target.get("outer_diameter")) / 2,
            _mm(target.get("length")),
        ), []


ENTRY = Tube()
