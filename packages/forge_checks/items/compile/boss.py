"""What the check compiler holds for a boss: its entry in the ``compile`` registry (its branches moved from ``compiler.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from forge_spec.draft import Item

from forge_checks.items.compile._common import _PLAIN, _mm, main_face_refs
from forge_checks.items.compile.protocol import CompileKind
from forge_checks.kinds.position import Centre, Ref
from forge_checks.kinds.surfaces import Round
from forge_checks.place import Copy

if TYPE_CHECKING:
    from forge_checks.items.compile._context import CompileContext


class Boss(CompileKind):
    key = "boss"
    threadable = True
    rod_length = "height"

    def checks(self, c: CompileContext, item: Item) -> None:
        c._round_body(item, "diameter", "height")
        c._standing_fields(item)

    def main(self, c: CompileContext, item: Item, copy: Copy) -> Ref | None:
        r = _mm(item.get("diameter")) / 2
        if copy.lean is not None:  # leaning: its axis, where all of its side stands out of the face
            cos = float(sum(copy.lean[k] * copy.direction[k] for k in range(3)))
            start = r * math.sqrt(max(1.0 - cos * cos, 0.0)) / cos
            if c._plain(item) - start < _PLAIN:
                return None
            return Centre(Round(copy.point, copy.lean, r, start, c._plain(item), False))
        return Centre(Round(copy.point, copy.direction, r, 0.0, c._plain(item), False))

    def face_refs(
        self, c: CompileContext, owner: Item, copy: Copy, face: str
    ) -> tuple[Ref, Ref, Ref] | None:
        return main_face_refs(c, owner, copy)


ENTRY = Boss()
