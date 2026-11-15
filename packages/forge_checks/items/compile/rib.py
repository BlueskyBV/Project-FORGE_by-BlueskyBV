"""What the check compiler holds for a rib: its entry in the ``compile`` registry (its branches moved from ``compiler.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item

from forge_checks.items.compile._common import (
    _mm,
    box_no_centre,
    box_round_copy,
    box_sides_along,
)
from forge_checks.items.compile.protocol import CompileKind
from forge_checks.kinds.position import Middle
from forge_checks.kinds.surfaces import Plane
from forge_checks.place import Copy, RoundSide

if TYPE_CHECKING:
    from forge_checks.items.compile._context import CompileContext


class Rib(CompileKind):
    key = "rib"
    boxed = True

    def checks(self, c: CompileContext, item: Item) -> None:
        copy = c.copies(item)[0]
        assert copy.axes is not None
        along = c._choice_value(item, "along")
        assert along is not None, "a rib runs along an axis"
        other = copy.axes[1] if along == copy.axes[0] else copy.axes[0]
        c._box_body(item, lambda _: {"length": (along, _mm(item.get("length"))),
                                        "thickness": (other, _mm(item.get("thickness")))}, "height")  # fmt: skip
        c._choice(item, "along")
        c._standing_fields(item)

    def sides(
        self, c: CompileContext, item: Item, copy: Copy, axis: str
    ) -> tuple[Plane, Plane] | None:
        return box_sides_along(c, item, copy, axis)

    def no_centre(
        self, c: CompileContext, item: Item, group: list[Copy], axis: str
    ) -> str:
        return box_no_centre(c, item, group, axis)

    def round_copy(
        self, c: CompileContext, item: Item, copy: Copy, side: RoundSide
    ) -> tuple[Middle, float, float] | None:
        return box_round_copy(c, item, copy, side)


ENTRY = Rib()
