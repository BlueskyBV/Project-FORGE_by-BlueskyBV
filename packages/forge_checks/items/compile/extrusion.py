"""What the check compiler holds for a extrusion: its entry in the ``compile`` registry (its branches moved from ``compiler.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from forge_spec.draft import Item

from forge_checks.items.compile._common import Buried, _mm, _t, _v
from forge_checks.items.compile.protocol import CompileKind
from forge_checks.kinds.position import Ref
from forge_checks.kinds.surfaces import Plane
from forge_checks.place import Copy, FlatFace

if TYPE_CHECKING:
    from forge_checks.items.compile._context import CompileContext


class Extrusion(CompileKind):
    key = "extrusion"

    def checks(self, c: CompileContext, item: Item) -> None:
        """An extrusion's length between its two ends; its outline is held by face accounting (docs/V2-stage4.md, 6.6)."""
        length = _mm(item.get("length"))
        c.size(item, length)
        c._profile(item)
        for copy in c.copies(item):
            faces = c.faces(item.id, copy.index)
            top, foot = faces.get("+end"), faces.get("-end")
            if not isinstance(top, FlatFace) or (
                copy.host is None and not isinstance(foot, FlatFace)
            ):
                c.skip(item, "length", "it has no flat ends")
                continue
            half = (
                top.outline.half
            )  # its box's, along the face's axes in frame order (FLAT_AXES)
            up = _v(copy.direction)
            top_plane = Plane(top.centre, copy.direction)
            if not c.seen(top_plane, half):
                c.skip(
                    item,
                    "length",
                    Buried("its far end is nowhere on the part's surface"),
                )
                continue
            bottom = None
            if copy.host is None:
                assert isinstance(foot, FlatFace)
                bottom = Plane(foot.centre, _t(-up))
                if not c.seen(bottom, half):
                    c.skip(
                        item,
                        "length",
                        Buried("its base is nowhere on the part's surface"),
                    )
                    continue
            k1, k2 = ("xyz".index(a) for a in top.axes)
            (c1, c2), point = top.outline.centre, copy.point
            reach = math.hypot(
                abs(c1 - point[k1]) + half[0], abs(c2 - point[k2]) + half[1]
            )
            c._height(item, "length", copy, top_plane, bottom, length, reach)
        c._axis(item)
        c._standing_fields(item)

    def shift(self, c: CompileContext, item: Item, copy: Copy, axis: str) -> float:
        """An extrusion's box's middle is off its point (0, 0)."""
        face = c.faces(item.id, copy.index).get("+end")
        if not isinstance(face, FlatFace) or axis not in face.axes:
            return 0.0
        k = face.axes.index(axis)
        return float(face.outline.centre[k] - copy.point["xyz".index(axis)])

    def centre_ref(
        self, c: CompileContext, item: Item, copy: Copy, axis: str
    ) -> Ref | None:
        """An extrusion's is the middle of its box's edges, which is :meth:`shift` from its point along ``axis``."""
        refs = c._own_outline(item, copy, axis)
        return refs[2] if refs is not None else None

    def edge_ref(
        self, c: CompileContext, item: Item, copy: Copy, axis: str, sign: float
    ) -> Ref | None:
        refs = c._own_outline(item, copy, axis)
        return (refs[1] if sign > 0 else refs[0]) if refs is not None else None


ENTRY = Extrusion()
