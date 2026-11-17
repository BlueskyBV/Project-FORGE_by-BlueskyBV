"""How the solver places a text: its entry in the ``solve`` registry (its branches moved from ``placement.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item
from forge_spec.draft import Text as Words
from forge_spec.font import missing_letters, text_width
from forge_spec.geometry import (
    FlatFace,
    rect,
)
from forge_spec.items.solve._common import _choice_of, _size
from forge_spec.items.solve.protocol import SolveKind
from forge_spec.letters import ink_box

if TYPE_CHECKING:
    from forge_spec.geometry import FlatFace, Part
    from forge_spec.placement import Layout


class Text(SolveKind):
    key = "text"

    lettered = True

    def outline_fields(
        self, item: Item, axes: tuple[str, str] | None = None, k: int | None = None
    ) -> tuple[str, ...]:
        if k is None or axes is None:
            return ("height", "text")
        return ("height", "text") if k == 0 else ("height",)

    def outline(
        self, item: Item, layout: Layout, axes: tuple[str, str]
    ) -> tuple[Part, ...]:
        # The line's box in the pinned font: its letters' advances, a capital
        # tall (docs/definitions/text.md). Letters the font lacks are the
        # spec checks' to report; here they take no room.
        text = item.get("text")
        letters = text.text if isinstance(text, Words) else ""
        height = _size(item, "height")
        width = text_width(
            "".join(ch for ch in letters if not missing_letters(ch)), height
        )
        return (rect(width / 2, height / 2),)

    def turnable(
        self, item: Item, layout: Layout, axes: tuple[str, str]
    ) -> tuple[float, float, float] | None:
        (line,) = self.outline(item, layout, axes)
        return line.half[0], line.half[1], 0.0

    def covers(self, item: Item, layout: Layout, face: FlatFace) -> tuple[Part, ...]:
        """Letters cover their ink's box: placed by their box (text.md), their ink reaches past it (a j's tail, an f's hook).

        The ink's box (forge_spec.letters) is what must lie on the face and
        clear of what else is on it (docs/V2-stage4.md, 7.1). The letters run
        left to right along up (the face's second axis) cross outward.
        """
        text = item.get("text")
        letters = "".join(
            ch
            for ch in (text.text if isinstance(text, Words) else "")
            if not missing_letters(ch)
        )
        height = _size(item, "height")
        ink = ink_box(letters, height)
        if ink is None:
            return ()
        (x0, y0), (x1, y1) = ink
        up, out = face.frame.v, face.frame.n
        right = (
            up[1] * out[2] - up[2] * out[1],
            up[2] * out[0] - up[0] * out[2],
            up[0] * out[1] - up[1] * out[0],
        )
        sign = face.frame.across(right)[0]
        middle = text_width(letters, height) / 2
        return (
            rect(
                (x1 - x0) / 2,
                (y1 - y0) / 2,
                sign * ((x0 + x1) / 2 - middle),
                (y0 + y1) / 2 - height / 2,
            ),
        )

    def embossed(self, item: Item) -> bool:
        return _choice_of(item, "mode") == "emboss"


ENTRY = Text()
