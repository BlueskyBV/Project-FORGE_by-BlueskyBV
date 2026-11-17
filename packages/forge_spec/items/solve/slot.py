"""How the solver places a slot: its entry in the ``solve`` registry (its branches moved from ``placement.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import (
    Item,
)
from forge_spec.geometry import (
    EPS,
    rect,
    slot_outline,
)
from forge_spec.items.solve._common import _choice_of, _item_values, _oriented, _size
from forge_spec.items.solve.protocol import SolveKind
from forge_spec.problems import pointer

if TYPE_CHECKING:
    from forge_spec.geometry import Part
    from forge_spec.placement import Layout


class Slot(SolveKind):
    key = "slot"

    def outline_fields(
        self, item: Item, axes: tuple[str, str] | None = None, k: int | None = None
    ) -> tuple[str, ...]:
        if k is None or axes is None:
            return ("length", "width")
        along = _choice_of(item, "along") == axes[k]
        return ("length",) if along else ("width",)

    def outline(
        self, item: Item, layout: Layout, axes: tuple[str, str]
    ) -> tuple[Part, ...]:
        length, width = _size(item, "length"), _size(item, "width")
        along_first = _choice_of(item, "along") == axes[0]
        if _choice_of(item, "ends") != "round" or length < width:
            return (
                rect(
                    *_oriented(axes, _choice_of(item, "along"), length / 2, width / 2)
                ),
            )
        return slot_outline(length, width, along_first=along_first)

    def turnable(
        self, item: Item, layout: Layout, axes: tuple[str, str]
    ) -> tuple[float, float, float] | None:
        length, width = _size(item, "length"), _size(item, "width")
        h1, h2 = _oriented(axes, _choice_of(item, "along"), length / 2, width / 2)
        round_ends = _choice_of(item, "ends") == "round" and length >= width
        return h1, h2, width / 2 if round_ends else 0.0

    def check_shape(self, item: Item, at: str, layout: Layout) -> None:
        length, width = _size(item, "length"), _size(item, "width")
        if length < width - EPS:
            layout.problem("cant", at + pointer("length"),
                           f"a slot's overall length ({length:g} mm) can't be less than its width ({width:g} mm)",
                           _item_values(item, "length", "width"))  # fmt: skip


ENTRY = Slot()
