"""What the check compiler holds for a cone: its entry in the ``compile`` registry (its branches moved from ``compiler.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_numeric import scalar as fs
from forge_spec.draft import Item

from forge_checks.items.compile._common import Buried, _mm, _t, _v
from forge_checks.items.compile.protocol import CompileKind
from forge_checks.kinds.diameter import Across
from forge_checks.kinds.position import ConeRim, Ref
from forge_checks.kinds.surfaces import Cone as Surface
from forge_checks.kinds.surfaces import Plane
from forge_checks.kinds.wall import Annulus
from forge_checks.place import Copy, FlatFace, Hollow

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
            # Its top's plane: its +end's, or, where a shell leaves it open and nothing stands there, the rim's, the
            # plane its top end lies in all the same.
            top_plane = (c.face_plane(end, top / 2) if isinstance(end, FlatFace)
                         else _end_plane(copy, length, top / 2) if top > 0.0 and (item.id, copy.index) in c.placed.hollows
                         else None)  # fmt: skip
            if top_plane is not None and not c.seen(top_plane):
                c.skip(
                    item, "length", Buried("its top is nowhere on the part's surface")
                )
            elif top_plane is not None:
                bottom = (
                    c.face_plane(low, base / 2)
                    if copy.host is None and isinstance(low, FlatFace)
                    else _end_plane(copy, 0.0, base / 2, -1.0)
                    if copy.host is None and (item.id, copy.index) in c.placed.hollows
                    else None
                )
                c._height(
                    item,
                    "length",
                    copy,
                    top_plane,
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

    def hollow_side(self, c: CompileContext, body: Item, copy: Copy, hollow: Hollow) -> Annulus | None:
        """Its side wall (shell.md, "cone"): its side, and the hollow's cone behind it, over the hollow's length; its
        radius there the cone's less the wall times the side's slant over its length."""
        base, top, length = (_mm(body.get(n)) / (1.0 if n == "length" else 2.0)
                             for n in ("base_diameter", "top_diameter", "length"))  # fmt: skip
        t = hollow.walls["side"]
        start, end = hollow.walls.get("-end", 0.0), length - hollow.walls.get("+end", 0.0)
        taper, slant = (top - base) / length, fs.hypot(length, top - base) / length

        def radius(s: float, less: float) -> float:
            return base + taper * s - less * slant

        outer = Surface(copy.point, copy.direction, (radius(start, 0.0), radius(end, 0.0)), (start, end), False)
        inner = Surface(copy.point, copy.direction, (radius(start, t), radius(end, t)), (start, end), True)
        return Annulus(outer, inner)

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


def _end_plane(copy: Copy, at: float, reach: float, sign: float = 1.0) -> Plane:
    """The plane an end lies in, ``at`` along its axis from its -end, facing out of it (``sign`` -1: its -end's),
    within ``reach`` of its axis: an open end's rim lies in it."""
    way = _v(copy.direction)
    return Plane(_t(_v(copy.point) + at * way), _t(sign * way), reach)


ENTRY = Cone()
