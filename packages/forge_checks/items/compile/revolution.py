"""What the check compiler holds for a revolution: its entry in the ``compile`` registry (its branches moved from ``compiler.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item

from forge_checks.items.compile.protocol import CompileKind
from forge_checks.kinds.position import Ref
from forge_checks.place import Copy

if TYPE_CHECKING:
    from forge_checks.items.compile._context import CompileContext


class Revolution(CompileKind):
    key = "revolution"

    def checks(self, c: CompileContext, item: Item) -> None:
        """A revolution's outline is held by face accounting (docs/V2-stage4.md, 6.6): it has no single size."""
        c._profile(item)
        c._axis(item)
        c._standing_fields(item)

    def main(self, c: CompileContext, item: Item, copy: Copy) -> Ref | None:
        return c._turned_axis(item, copy)

    def edge_ref(
        self, c: CompileContext, item: Item, copy: Copy, axis: str, sign: float
    ) -> Ref | None:
        return c._turned_edge(item, copy)

    def face_refs(
        self, c: CompileContext, owner: Item, copy: Copy, face: str
    ) -> tuple[Ref | str, Ref | str, Ref | str] | str | None:
        if face not in ("+end", "-end"):
            return None
        return c._turned_rim(owner, copy, face)


ENTRY = Revolution()
