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
from forge_checks.place import Copy, Face, Placed, RoundSide, in_axes
from forge_checks.shapes import Frame, Prism, RoundRect, Shape2D


class Slot(OracleKind):
    key = "slot"

    def node(
        self, item: Item, copy: Copy, face: Face | None, placed: Placed
    ) -> Node:
        assert face is not None
        if isinstance(face, RoundSide):
            return _keyway(item, copy, face)
        return flat_cut_node(self, item, copy, face)

    def outline(self, item: Item, axes: tuple[str, str]) -> Shape2D:
        length, width = _mm(item.get("length")), _mm(item.get("width"))
        along_first = in_axes(_choice(item, "along") or "", axes) == axes[0]
        h1, h2 = (length / 2, width / 2) if along_first else (width / 2, length / 2)
        r = width / 2 if _choice(item, "ends") == "round" else 0.0
        return RoundRect(h1, h2, (r, r, r, r))

    def cut_chains(self, item: Item, copy: Copy, which: str, placed: Placed, size: float
                   ) -> tuple[list[rounds.Chain], bool, list[Node], Node | None]:  # fmt: skip
        return flat_cut_chains(self, item, copy, which, placed, size)


def _keyway(item: Item, copy: Copy, side: RoundSide) -> Node:
    """A slot round a side (slot.md, "Round a side"): its outline on the plane touching the side along the line through
    its point, its width round the side and its length along its axis, from that plane in square to it to its depth."""
    assert copy.span is not None
    start, depth = copy.span
    a = side.placed_frame.n
    w = (-copy.direction[0] + 0.0, -copy.direction[1] + 0.0, -copy.direction[2] + 0.0)
    u = (a[1] * w[2] - a[2] * w[1], a[2] * w[0] - a[0] * w[2], a[0] * w[1] - a[1] * w[0])
    length, width = _mm(item.get("length")), _mm(item.get("width"))
    r = width / 2 if _choice(item, "ends") == "round" else 0.0
    return Prism(Frame(copy.point, u, a, w), RoundRect(width / 2, length / 2, (r, r, r, r)), start, depth)


ENTRY = Slot()
