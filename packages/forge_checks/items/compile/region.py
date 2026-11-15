"""What the check compiler holds for a region: its entry in the ``compile`` registry (its branches moved from ``compiler.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item

from forge_checks.items.compile.protocol import CompileKind

if TYPE_CHECKING:
    from forge_checks.items.compile._context import CompileContext


class Region(CompileKind):
    key = "region"

    def checks(self, c: CompileContext, item: Item) -> None:
        c._not_placed(
            item,
            "a region is designed later, within its envelope: its constraints are checked then",
        )

    implicit = False


ENTRY = Region()
