"""What the oracle makes for a sphere: its entry in the ``oracle`` registry (its branches moved from ``oracle.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

import numpy as np
from forge_spec.draft import Item

from forge_checks import rounds
from forge_checks.csg import Inter, Node
from forge_checks.items.oracle._shapes import (
    _choice,
    _circle,
    _mm,
    _vec,
    round_footprint,
)
from forge_checks.items.oracle.protocol import OracleKind
from forge_checks.place import Copy, FlatFace, Hollow, Placed, RoundSide
from forge_checks.shapes import Ball, Complement, Frame, Halfspace

if TYPE_CHECKING:
    from forge_checks.oracle import _Making


class Sphere(OracleKind):
    key = "sphere"

    def node(
        self, item: Item, copy: Copy, face: FlatFace | RoundSide | None, placed: Placed
    ) -> Node:
        u = np.asarray(copy.direction, dtype=float)
        radius = _mm(item.get("diameter")) / 2
        if _choice(item, "portion") == "upper_half":
            return Inter(
                (Ball(_vec(copy.point), radius), Halfspace(_vec(copy.point), _vec(-u)))
            )
        centre = (
            copy.point
            if copy.host is not None
            else _vec(np.asarray(copy.point) + radius * u)
        )
        return Ball(centre, radius)

    def hollow(self, item: Item, copy: Copy, placed: Placed) -> Node:
        hollow = placed.hollows[(item.id, copy.index)]
        u = np.asarray(copy.direction, dtype=float)
        radius = _mm(item.get("diameter")) / 2 - hollow.walls["surface"]
        if _choice(item, "portion") == "upper_half":
            floor = hollow.walls.get("-end", 0.0)
            ball = Ball(_vec(copy.point), radius)
            return Inter(
                (ball, Halfspace(_vec(np.asarray(copy.point) + floor * u), _vec(-u)))
            )
        centre = (
            copy.point
            if copy.host is not None
            else _vec(np.asarray(copy.point) + (radius + hollow.walls["surface"]) * u)
        )
        return Ball(_vec(centre), radius)

    def wall_bands(self, body: Item, copy: Copy, placed: Placed) -> dict[str, Node]:
        hollow = placed.hollows[(body.id, copy.index)]
        found: dict[str, Node] = {}
        u = np.asarray(copy.direction, dtype=float)
        radius = _mm(body.get("diameter")) / 2 - hollow.walls["surface"]
        if _choice(body, "portion") == "upper_half":
            found["surface"] = Complement(Ball(_vec(copy.point), radius))
            if "-end" in hollow.walls:
                floor = hollow.walls["-end"]
                found["-end"] = Halfspace(
                    _vec(np.asarray(copy.point) + floor * u), _vec(u)
                )
            return found
        centre = (
            copy.point
            if copy.host is not None
            else _vec(np.asarray(copy.point) + (radius + hollow.walls["surface"]) * u)
        )
        found["surface"] = Complement(Ball(_vec(centre), radius))
        return found

    def rim_chains(self, target: Item, copy: Copy, which: str, pairs: tuple[tuple[str, str], ...], making: _Making,
                   whole: Node, hollow: Hollow | None) -> tuple[list[rounds.Chain], list[tuple[rounds.Chain, frozenset[str]]]]:  # fmt: skip
        return _dome_chains(target, copy, hollow), []

    def footprint_chain(
        self,
        item: Item,
        copy: Copy,
        corners: Mapping[frozenset[str], tuple[str, float]],
    ) -> rounds.Chain:
        radius = _mm(item.get("diameter")) / 2
        return round_footprint(copy, radius, rounds.Circle2((0.0, 0.0), radius, False))


def _dome_chains(target: Item, copy: Copy, hollow: Hollow | None) -> list[rounds.Chain]:
    """A dome's rim, where its round surface meets its flat face (and the hollow's, when that face is open)."""
    radius = _mm(target.get("diameter")) / 2
    frame = Frame.along(copy.point, np.asarray(copy.direction, dtype=float))
    flat = rounds.Line2((0.0, -1.0))
    found = [
        _circle(frame, radius, 0.0, flat, rounds.Circle2((0.0, 0.0), radius, True))
    ]
    if hollow is not None and "-end" in hollow.open:
        inner = radius - hollow.walls["surface"]
        found.append(
            _circle(frame, inner, 0.0, flat, rounds.Circle2((0.0, 0.0), inner, False))
        )
    return found


ENTRY = Sphere()
