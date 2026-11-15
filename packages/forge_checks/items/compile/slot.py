"""What the check compiler holds for a slot: its entry in the ``compile`` registry (its branches moved from ``compiler.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item

from forge_checks.items.compile._common import _STRAIGHT, _mm, _t, _v
from forge_checks.items.compile.protocol import CompileKind
from forge_checks.kinds.position import Position, RoundEdge
from forge_checks.kinds.size import Between
from forge_checks.kinds.surfaces import Plane, Round
from forge_checks.place import Copy, unit

if TYPE_CHECKING:
    from forge_checks.items.compile._context import CompileContext


class Slot(CompileKind):
    key = "slot"

    def checks(self, c: CompileContext, item: Item) -> None:
        width, length = _mm(item.get("width")), _mm(item.get("length"))
        along = c._choice_value(item, "along")
        assert along is not None, "a slot runs along an axis"
        round_ends = c._choice_value(item, "ends") == "round"
        c.size(item, width / 2)
        for copy in c.copies(item):
            assert copy.axes is not None and copy.span is not None
            a, n = _v(unit("+" + along)), _v(copy.direction)
            across_axis = copy.axes[1] if along == copy.axes[0] else copy.axes[0]
            across = _v(unit("+" + across_axis))
            depth = copy.span[1]
            straight = (length - width) / 2 if round_ends else length / 2
            circle = c._round_ends(item, copy, across_axis)
            breadth: Between | Position
            if circle is None:
                walls = [
                    c.cut_wall(copy, s * across, width / 2, a, straight)
                    for s in (1, -1)
                ]
                breadth = Between(walls[0], walls[1], _t(across))
            else:
                # About as long as it is wide, a round-ended slot's sides are all arc.
                breadth = Position(
                    _t(across), RoundEdge(circle[0], -1), RoundEdge(circle[1], 1)
                )
            c.check(item, "width", "size", width, c.tol(item.get("width")), breadth, copy.index)  # fmt: skip
            if round_ends:
                ends = [Round(_t(_v(copy.point) + s * (length - width) / 2 * a), _t(-n), width / 2, 0.0, depth, True)
                        for s in (-1, 1)]  # fmt: skip
                span = Position(_t(a), RoundEdge(ends[0], -1), RoundEdge(ends[1], 1))
                c.check(
                    item,
                    "length",
                    "size",
                    length,
                    c.tol(item.get("length")),
                    span,
                    copy.index,
                )
            else:
                ends_planes = [
                    c.cut_wall(copy, s * a, length / 2, across, width / 2)
                    for s in (1, -1)
                ]
                c.check(item, "length", "size", length, c.tol(item.get("length")),
                           Between(ends_planes[0], ends_planes[1], _t(a)), copy.index)  # fmt: skip
            c._cut_depth(
                item, copy, width / 2, width / 2, depth, (along, length / 2, width / 2)
            )
        c._choice(item, "along")
        c._choice(item, "ends")
        c._cut_fields(item)

    def sides(
        self, c: CompileContext, item: Item, copy: Copy, axis: str
    ) -> tuple[Plane, Plane] | None:
        if copy.span is None or copy.axes is None:
            return None
        if c._round_ends(item, copy, axis) is not None:
            return None
        a = _v(unit("+" + axis))
        across = _v(
            unit("+" + (copy.axes[1] if axis == copy.axes[0] else copy.axes[0]))
        )
        along = c._choice_value(item, "along")
        half = _mm(item.get("length" if axis == along else "width")) / 2
        other = _mm(item.get("width" if axis == along else "length")) / 2
        if axis != along and c._choice_value(item, "ends") == "round":
            other -= _mm(item.get("width")) / 2
        return (
            c.cut_wall(copy, a, half, across, other),
            c.cut_wall(copy, -a, half, across, other),
        )

    def round_ends(
        self, c: CompileContext, item: Item, copy: Copy, axis: str
    ) -> tuple[Round, Round] | None:
        """A round-ended slot's ends, along it; across it too, when it is about as long as it is wide."""
        if copy.span is None:
            return None
        n = _v(copy.direction)
        if c._choice_value(item, "ends") != "round":
            return None
        along = c._choice_value(item, "along")
        width, length = _mm(item.get("width")), _mm(item.get("length"))
        if axis != along and length - width >= _STRAIGHT:
            return None
        ahead = _v(unit("+" + str(along)))
        ends = [Round(_t(_v(copy.point) + s * (length - width) / 2 * ahead), _t(-n), width / 2, 0.0,
                      copy.span[1], True) for s in (-1, 1)]  # fmt: skip
        return ends[0], ends[1]


ENTRY = Slot()
