"""What the check compiler holds for a fillet: its entry in the ``compile`` registry (its branches moved from ``compiler.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item

from forge_checks.items.compile.protocol import CompileKind

if TYPE_CHECKING:
    from forge_checks.items.compile._context import CompileContext


class Fillet(CompileKind):
    key = "fillet"

    def checks(self, c: CompileContext, item: Item) -> None:
        c._rounding(item, "radius")

    implicit = False


ENTRY = Fillet()
