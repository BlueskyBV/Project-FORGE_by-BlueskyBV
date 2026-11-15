"""What the oracle makes for a tab: its entry in the ``oracle`` registry (its branches moved from ``oracle.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np
from forge_spec.draft import Item

from forge_checks import rounds
from forge_checks.csg import Node
from forge_checks.items.oracle._shapes import (
    _axis,
    _box_edge,
    _choice,
    _frame,
    _mm,
    _on_side,
    _prism_of,
    _vec,
    box_chains,
    standing_box,
)
from forge_checks.items.oracle.protocol import OracleKind
from forge_checks.place import Copy, FlatFace, Hollow, Placed, RoundSide
from forge_checks.shapes import Prism, RoundRect

if TYPE_CHECKING:
    from forge_checks.oracle import _Making


class Tab(OracleKind):
    key = "tab"

    def node(
        self, item: Item, copy: Copy, face: FlatFace | RoundSide | None, placed: Placed
    ) -> Node:
        if _choice(item, "end") == "round":
            return _round_end_tab(copy, item, face)
        assert copy.axes is not None
        a1, a2 = copy.axes
        thin = _choice(item, "thickness_along")
        sizes = {
            thin: _mm(item.get("thickness")),
            (a2 if thin == a1 else a1): _mm(item.get("width")),
        }
        return standing_box(copy, sizes[a1], sizes[a2], _mm(item.get("length")), face)

    def rim_chains(self, target: Item, copy: Copy, which: str, pairs: tuple[tuple[str, str], ...], making: _Making,
                   whole: Node, hollow: Hollow | None) -> tuple[list[rounds.Chain], list[tuple[rounds.Chain, frozenset[str]]]]:  # fmt: skip
        if _choice(target, "end") != "round":
            return box_chains(target, copy, pairs, making, whole, hollow)
        return _round_tab_chains(_prism_of(whole), which, pairs), []


def _round_end_tab(copy: Copy, item: Item, face: FlatFace | RoundSide | None) -> Node:
    """A round-ended tab: its broad face's outline (two corners rounded), pushed across its thickness."""
    assert copy.axes is not None
    thin = _choice(item, "thickness_along")
    assert thin is not None
    wide = next(a for a in copy.axes if a != thin)
    length, width, thickness = (
        _mm(item.get("length")),
        _mm(item.get("width")),
        _mm(item.get("thickness")),
    )
    u = np.asarray(copy.direction, dtype=float)
    bottom = -face.radius if isinstance(face, RoundSide) and face.outward else 0.0
    span = length - bottom
    middle = np.asarray(copy.point) + u * (bottom + length) / 2
    r = width / 2
    # In the section, a runs across the tab (its width) and b out along it: the round end is at +b.
    frame = _frame(middle, _axis(wide), u)
    section = RoundRect(width / 2, span / 2, (r, r, 0.0, 0.0))
    prism = Prism(frame, section, -thickness / 2, thickness / 2)
    if isinstance(face, RoundSide):
        return _on_side(prism, face)
    return prism


def _round_tab_chains(
    prism: Prism, which: str, pairs: tuple[tuple[str, str], ...]
) -> list[rounds.Chain]:
    """A round-ended tab: its straight edges along its straight part, or the half-circles round its end."""
    f = prism.frame
    shape = prism.shape
    assert isinstance(shape, RoundRect)
    h1, h2, r = shape.h1, shape.h2, shape.corners[0]
    if which == "top":
        found = []
        for c, sign in ((prism.t1, 1.0), (prism.t0, -1.0)):
            centre = f.world(np.array([0.0]), np.array([h2 - r]), np.array([c]))[0]
            # Each half-circle runs on smoothly into the straight edges below it: no clean stop.
            arc = rounds.RoundEdge(_vec(centre), f.w, f.u, f.v, r, 0.0,
                                   rounds.Line2((0.0, sign)), rounds.Line2((1.0, 0.0)), 0.0, math.pi)  # fmt: skip
            found.append(rounds.Chain((arc,), clean=(False, False)))
        return found
    corners = f.world(
        np.array([-h1, h1, -h1, h1, -h1, h1, -h1, h1]),
        np.array([-h2, -h2, h2 - r, h2 - r] * 2),
        np.array([prism.t0] * 4 + [prism.t1] * 4),
    )
    lo, hi = corners.min(axis=0), corners.max(axis=0)
    # Each runs from the tab's foot, square across it, to where it runs on smoothly into the round end.
    found = []
    for f1, f2 in pairs:
        edge = _box_edge(_vec(lo), _vec(hi), f1, f2)
        rising = float(np.asarray(edge.along) @ np.asarray(f.v)) > 0
        found.append(
            rounds.Chain((edge,), clean=(True, False) if rising else (False, True))
        )
    return found


ENTRY = Tab()
