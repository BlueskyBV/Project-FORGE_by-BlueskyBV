"""What the check compiler holds for a pocket: its entry in the ``compile`` registry (its branches moved from ``compiler.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item

from forge_checks.classes import RADIUS
from forge_checks.items.compile._common import _STRAIGHT, _mm, _t, _v, main_face_refs
from forge_checks.items.compile.protocol import CompileKind
from forge_checks.kinds.position import Centre, Position, Ref, RoundEdge
from forge_checks.kinds.size import Between
from forge_checks.kinds.surfaces import Plane, Round
from forge_checks.place import Copy, unit

if TYPE_CHECKING:
    from forge_checks.items.compile._context import CompileContext


class Pocket(CompileKind):
    key = "pocket"

    def checks(self, c: CompileContext, item: Item) -> None:
        shape = c._choice_value(item, "shape")
        for copy in c.copies(item):
            assert copy.axes is not None and copy.span is not None
            n = _v(copy.direction)
            depth = copy.span[1]
            if shape == "circle":
                r = _mm(item.get("diameter")) / 2
                c.check(item, "diameter", "diameter", 2 * r, c.tol(item.get("diameter")),
                           Round(copy.point, _t(-n), r, 0.0, depth, True), copy.index)  # fmt: skip
                c.size(item, r)
                c._cut_depth(item, copy, r, r, depth)
                continue
            sizes = {"length": copy.axes[0], "width": copy.axes[1]}
            half = {name: _mm(item.get(name)) / 2 for name in sizes}
            corner = (
                _mm(item.get("corner_radius"))
                if item.get("corner_radius") is not None
                else 0.0
            )
            for name, axis in sizes.items():
                a = _v(unit("+" + axis))
                other_axis = copy.axes[1] if axis == copy.axes[0] else copy.axes[0]
                other = half["width" if name == "length" else "length"]
                ends = c._round_ends(item, copy, axis)
                span: Between | Position
                if ends is None:
                    across = _v(unit("+" + other_axis))
                    walls = [
                        c.cut_wall(copy, s * a, half[name], across, other - corner)
                        for s in (1, -1)
                    ]
                    span = Between(walls[0], walls[1], _t(a))
                else:
                    # Ends rounded (all but) all across by its corners: from one's fitted arc to the other's.
                    span = Position(
                        _t(a), RoundEdge(ends[0], -1), RoundEdge(ends[1], 1)
                    )
                c.check(item, name, "size", 2 * half[name], c.tol(item.get(name)), span, copy.index)  # fmt: skip
                c.size(item, half[name])
            if corner > 0:
                e1, e2 = _v(unit("+" + copy.axes[0])), _v(unit("+" + copy.axes[1]))
                for k, (s1, s2) in enumerate(((1, 1), (-1, 1), (-1, -1), (1, -1))):
                    centre = (
                        _v(copy.point)
                        + s1 * (half["length"] - corner) * e1
                        + s2 * (half["width"] - corner) * e2
                    )
                    c.check(item, "corner_radius", "corner", corner, c.tol(item.get("corner_radius"), RADIUS),
                               Round(_t(centre), _t(-n), corner, 0.0, depth, True), copy.index * 4 + k)  # fmt: skip
                c.size(item, corner)
            c._cut_depth(item, copy, min(half.values()), min(half.values()), depth,
                            (copy.axes[0], half["length"], half["width"]))  # fmt: skip
        c._choice(item, "shape")
        c._cut_fields(item)

    def main(self, c: CompileContext, item: Item, copy: Copy) -> Ref | None:
        if c._choice_value(item, "shape") != "circle":
            return None
        assert copy.span is not None
        r = _mm(item.get("diameter")) / 2
        return Centre(
            Round(copy.point, _t(-_v(copy.direction)), r, 0.0, copy.span[1], True)
        )

    def sides(
        self, c: CompileContext, item: Item, copy: Copy, axis: str
    ) -> tuple[Plane, Plane] | None:
        if copy.span is None or copy.axes is None:
            return None
        if c._choice_value(item, "shape") == "circle":
            return None
        if c._round_ends(item, copy, axis) is not None:
            return None
        a = _v(unit("+" + axis))
        across = _v(
            unit("+" + (copy.axes[1] if axis == copy.axes[0] else copy.axes[0]))
        )
        first = axis == copy.axes[0]
        half = _mm(item.get("length" if first else "width")) / 2
        other = _mm(item.get("width" if first else "length")) / 2
        corner = item.get("corner_radius")
        other -= _mm(corner) if corner is not None else 0.0
        return (
            c.cut_wall(copy, a, half, across, other),
            c.cut_wall(copy, -a, half, across, other),
        )

    def round_ends(
        self, c: CompileContext, item: Item, copy: Copy, axis: str
    ) -> tuple[Round, Round] | None:
        """A rectangular pocket's ends where its corners are rounded to (about) half its size across them: an end's corner on the other axis's + side."""
        if copy.span is None:
            return None
        assert copy.axes is not None
        n = _v(copy.direction)
        a = _v(unit("+" + axis))
        corner = item.get("corner_radius")
        if c._choice_value(item, "shape") == "circle" or corner is None:
            return None
        r = _mm(corner)
        first = axis == copy.axes[0]
        half = _mm(item.get("length" if first else "width")) / 2
        other = _mm(item.get("width" if first else "length")) / 2
        if r <= 0 or 2 * (other - r) >= _STRAIGHT:
            return None
        # Each end's corner on the +other side (both reach the end alike).
        b = _v(unit("+" + (copy.axes[1] if first else copy.axes[0])))
        ends = [Round(_t(_v(copy.point) + s * (half - r) * a + (other - r) * b), _t(-n), r, 0.0, copy.span[1],
                      True) for s in (-1, 1)]  # fmt: skip
        return ends[0], ends[1]

    def face_refs(
        self, c: CompileContext, owner: Item, copy: Copy, face: str
    ) -> tuple[Ref, Ref, Ref] | None:
        if c._choice_value(owner, "shape") != "circle":
            return None
        return main_face_refs(c, owner, copy)


ENTRY = Pocket()
