"""What the check compiler holds for a tube: its entry in the ``compile`` registry (its branches moved from ``compiler.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item

from forge_checks.items.compile._common import _mm, main_face_refs
from forge_checks.items.compile.protocol import CompileKind
from forge_checks.kinds.position import Centre, Ref
from forge_checks.kinds.surfaces import Round
from forge_checks.place import Copy

if TYPE_CHECKING:
    from forge_checks.items.compile._context import CompileContext


class Tube(CompileKind):
    key = "tube"

    def checks(self, c: CompileContext, item: Item) -> None:
        c._round_body(item, "outer_diameter", "length", "inner_diameter")
        c._axis(item)
        c._standing_fields(item)

    def main(self, c: CompileContext, item: Item, copy: Copy) -> Ref | None:
        r = _mm(item.get("outer_diameter")) / 2
        length = _mm(item.get("length"))
        return Centre(Round(copy.point, copy.direction, r, 0.0, length, False))

    def face_refs(
        self, c: CompileContext, owner: Item, copy: Copy, face: str
    ) -> tuple[Ref, Ref, Ref] | None:
        return main_face_refs(c, owner, copy)


ENTRY = Tube()
