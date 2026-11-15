"""What the check compiler holds for a tab: its entry in the ``compile`` registry (its branches moved from ``compiler.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from forge_spec.draft import Item

from forge_checks.items.compile._common import (
    _STRAIGHT,
    _mm,
    _v,
    box_no_centre,
    box_round_copy,
    box_sides_along,
)
from forge_checks.items.compile.protocol import CompileKind
from forge_checks.kinds.position import Centre, Middle, Ref
from forge_checks.kinds.surfaces import Plane, Round
from forge_checks.place import Copy, RoundSide

if TYPE_CHECKING:
    from forge_checks.items.compile._context import CompileContext


class Tab(CompileKind):
    key = "tab"
    boxed = True

    def checks(self, c: CompileContext, item: Item) -> None:
        copy = c.copies(item)[0]
        assert copy.axes is not None
        thin = c._choice_value(item, "thickness_along")
        assert thin is not None, "a tab's thickness runs along an axis"
        other = copy.axes[1] if thin == copy.axes[0] else copy.axes[0]
        sizes = {"thickness": (thin, _mm(item.get("thickness")))}
        if c._choice_value(item, "end") == "round":
            c._box_body(item, lambda _: sizes, None)
            c._round_end(item)
        else:
            sizes["width"] = (other, _mm(item.get("width")))
            c._box_body(item, lambda _: sizes, "length")
        c._choice(item, "thickness_along")
        c._choice(item, "end")
        c._standing_fields(item)

    def sides(
        self, c: CompileContext, item: Item, copy: Copy, axis: str
    ) -> tuple[Plane, Plane] | None:
        return box_sides_along(c, item, copy, axis)

    def no_centre(
        self, c: CompileContext, item: Item, group: list[Copy], axis: str
    ) -> str:
        return box_no_centre(c, item, group, axis)

    def round_copy(
        self, c: CompileContext, item: Item, copy: Copy, side: RoundSide
    ) -> tuple[Middle, float, float] | None:
        return box_round_copy(c, item, copy, side)

    def straight(self, c: CompileContext, item: Item) -> float | None:
        if c._choice_value(item, "end") != "round":
            return None
        return _mm(item.get("length")) - _mm(item.get("width")) / 2

    def round_ends(
        self, c: CompileContext, item: Item, copy: Copy, axis: str
    ) -> tuple[Round, Round] | None:
        """A round-ended tab's sides across its width, when it is (about) all half-disc: its end's rounding, which is tangent to them where it starts."""
        if c._choice_value(item, "end") != "round":
            return None
        thin = c._choice_value(item, "thickness_along")
        r = _mm(item.get("width")) / 2
        if axis == thin or _mm(item.get("length")) - r >= _STRAIGHT:
            return None
        end = c._tab_end(item, copy)
        return end, end

    def seam(
        self, c: CompileContext, owner: Item, host: tuple[str, int, str], axis: str
    ) -> tuple[float, Ref] | None:
        """A round-ended tab's narrow side stops where its end's rounding starts (tab.md), with no edge built there: the rounding's axis is level with it."""
        if c._choice_value(owner, "end") != "round":
            return None
        thin = c._choice_value(owner, "thickness_along")
        copy = c.copies(owner)[host[1]]
        up = _v(copy.direction)
        k = int(np.argmax(np.abs(up)))
        if host[2][1] == thin or "xyz"[k] != axis:
            return None
        return (1.0 if up[k] > 0 else -1.0), Centre(c._tab_end(owner, copy))


ENTRY = Tab()
