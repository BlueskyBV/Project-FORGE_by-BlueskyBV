"""What the check compiler holds for a block: its entry in the ``compile`` registry (its branches moved from ``compiler.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item

from forge_checks.items.compile._common import (
    box_checks,
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


class Block(CompileKind):
    key = "block"
    boxed = True

    def checks(self, c: CompileContext, item: Item) -> None:
        box_checks(c, item)

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


ENTRY = Block()
