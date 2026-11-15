"""What the check compiler holds for a cone: its entry in the ``compile`` registry (its branches moved from ``compiler.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item

from forge_checks.items.compile._common import Buried, _mm
from forge_checks.items.compile.protocol import CompileKind
from forge_checks.kinds.diameter import Across
from forge_checks.kinds.position import ConeRim, Ref
from forge_checks.kinds.surfaces import Cone as Surface
from forge_checks.place import Copy, FlatFace

if TYPE_CHECKING:
    from forge_checks.items.compile._context import CompileContext


class Cone(CompileKind):
    key = "cone"

    def checks(self, c: CompileContext, item: Item) -> None:
        for copy in c.copies(item):
            base, top, length = (
                _mm(item.get(n)) for n in ("base_diameter", "top_diameter", "length")
            )
            cone = Surface(
                copy.point, copy.direction, (base / 2, top / 2), (0.0, length), False
            )
            for name, at, value in (
                ("base_diameter", 0.0, base),
                ("top_diameter", length, top),
            ):
                c.check(
                    item,
                    name,
                    "diameter",
                    value,
                    c.tol(item.get(name)),
                    Across(cone, at),
                    copy.index,
                )
            faces = c.faces(item.id, copy.index)
            end = faces.get("+end")
            low = faces.get("-end")
            if isinstance(end, FlatFace) and not c.seen(c.face_plane(end, top / 2)):
                c.skip(
                    item, "length", Buried("its top is nowhere on the part's surface")
                )
            elif isinstance(end, FlatFace):
                bottom = (
                    c.face_plane(low, base / 2)
                    if copy.host is None and isinstance(low, FlatFace)
                    else None
                )
                c._height(
                    item,
                    "length",
                    copy,
                    c.face_plane(end, top / 2),
                    bottom,
                    length,
                    base / 2,
                )
            else:
                c.skip(
                    item,
                    "length",
                    "it comes to a point: its length shows in its top diameter (0) and its side",
                    "its top diameter's and its side's checks",
                )
            c.size(item, min(base, top) / 2 if top > 0 else base / 2)
        c._axis(item)
        c._standing_fields(item)

    def main(self, c: CompileContext, item: Item, copy: Copy) -> Ref | None:
        base, top, length = (
            _mm(item.get(n)) for n in ("base_diameter", "top_diameter", "length")
        )
        cone = Surface(copy.point, copy.direction, (base / 2, top / 2), (0.0, length), False)  # fmt: skip
        return ConeRim(cone, 0.0, 0.0)

    def face_refs(
        self, c: CompileContext, owner: Item, copy: Copy, face: str
    ) -> tuple[Ref, Ref, Ref] | None:
        if face not in ("+end", "-end"):
            return None
        base, top, length = (
            _mm(owner.get(n)) for n in ("base_diameter", "top_diameter", "length")
        )
        cone = Surface(copy.point, copy.direction, (base / 2, top / 2), (0.0, length), False)  # fmt: skip
        at = length if face == "+end" else 0.0
        # Each edge measured from it into the face: behind the way it is measured (sign -1).
        edge = ConeRim(cone, at, -1.0)
        return edge, edge, ConeRim(cone, at, 0.0)


ENTRY = Cone()
