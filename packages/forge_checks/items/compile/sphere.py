"""What the check compiler holds for a sphere: its entry in the ``compile`` registry (its branches moved from ``compiler.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item

from forge_checks.items.compile._common import _mm, _t, _v, main_face_refs
from forge_checks.items.compile.protocol import CompileKind
from forge_checks.kinds.position import BallCentre, Ref
from forge_checks.kinds.surfaces import Ball
from forge_checks.place import Copy

if TYPE_CHECKING:
    from forge_checks.items.compile._context import CompileContext


class Sphere(CompileKind):
    key = "sphere"

    def checks(self, c: CompileContext, item: Item) -> None:
        for copy in c.copies(item):
            radius = _mm(item.get("diameter")) / 2
            dome = c._choice_value(item, "portion") == "upper_half"
            centre = (
                copy.point
                if dome or copy.host is not None
                else _t(_v(copy.point) + radius * _v(copy.direction))
            )
            c.check(
                item,
                "diameter",
                "diameter",
                2 * radius,
                c.tol(item.get("diameter")),
                Ball(centre, radius),
                copy.index,
            )
            c.size(item, radius)
        c._choice(item, "portion")
        c._standing_fields(item)

    def main(self, c: CompileContext, item: Item, copy: Copy) -> Ref | None:
        radius = _mm(item.get("diameter")) / 2
        dome = c._choice_value(item, "portion") == "upper_half"
        centre = (
            copy.point
            if dome or copy.host is not None
            else _t(_v(copy.point) + radius * _v(copy.direction))
        )
        return BallCentre(Ball(centre, radius))

    def face_refs(
        self, c: CompileContext, owner: Item, copy: Copy, face: str
    ) -> tuple[Ref, Ref, Ref] | None:
        return main_face_refs(c, owner, copy)


ENTRY = Sphere()
