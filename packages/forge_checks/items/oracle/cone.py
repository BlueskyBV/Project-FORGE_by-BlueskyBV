"""What the oracle makes for a cone: its entry in the ``oracle`` registry (its branches moved from ``oracle.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

import numpy as np
from forge_spec.draft import Item

from forge_checks import rounds
from forge_checks.csg import Node
from forge_checks.items.oracle._shapes import _mm, _rim_chains, _unit2, round_footprint
from forge_checks.items.oracle.protocol import OracleKind
from forge_checks.place import Copy, Face, Hollow, Placed
from forge_checks.shapes import Frame, Frustum

if TYPE_CHECKING:
    from forge_checks.oracle import _Making


class Cone(OracleKind):
    key = "cone"

    def node(
        self, item: Item, copy: Copy, face: Face | None, placed: Placed
    ) -> Node:
        u = np.asarray(copy.direction, dtype=float)
        frame = Frame.along(copy.point, u)
        base, top = (
            _mm(item.get("base_diameter")) / 2,
            _mm(item.get("top_diameter")) / 2,
        )
        return Frustum(frame, 0.0, _mm(item.get("length")), base, top)

    def rim_chains(self, target: Item, copy: Copy, which: str, pairs: tuple[tuple[str, str], ...], making: _Making,
                   whole: Node, hollow: Hollow | None) -> tuple[list[rounds.Chain], list[tuple[rounds.Chain, frozenset[str]]]]:  # fmt: skip
        return _rim_chains(
            target,
            copy,
            pairs,
            hollow,
            making.placed,
            _mm(target.get("base_diameter")) / 2,
            _mm(target.get("top_diameter")) / 2,
            _mm(target.get("length")),
        ), []

    def footprint_chain(
        self,
        item: Item,
        copy: Copy,
        corners: Mapping[frozenset[str], tuple[str, float]],
    ) -> rounds.Chain:
        r0, r1 = (
            _mm(item.get("base_diameter")) / 2,
            _mm(item.get("top_diameter")) / 2,
        )
        length = _mm(item.get("length"))
        slope = _unit2(length, -(r1 - r0))
        return round_footprint(copy, r0, rounds.Line2((-slope[0], -slope[1])))


ENTRY = Cone()
