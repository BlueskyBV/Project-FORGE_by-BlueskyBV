"""What the oracle makes for a text: its entry in the ``oracle`` registry (its branches moved from ``oracle.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from forge_numeric import vector as fv
from forge_spec.draft import Item
from forge_spec.draft import Text as Words
from forge_spec.font import text_width

from forge_checks.csg import Node
from forge_checks.items.oracle._shapes import _axis, _choice, _frame, _mm
from forge_checks.items.oracle.protocol import OracleKind
from forge_checks.letters import Ink, LetterPrism, Letters2D
from forge_checks.place import Copy, FlatFace, RoundSide

if TYPE_CHECKING:
    from forge_checks.oracle import Step, _Making


class Text(OracleKind):
    key = "text"

    def copy_steps(
        self, item: Item, copy: Copy, face: FlatFace | RoundSide | None, making: _Making
    ) -> list[Step]:
        """Its letters, cut into the face or standing on it; spaces alone take nothing and add nothing."""
        letters = _letters(item, copy)
        embossed = _choice(item, "mode") == "emboss"
        if letters is None:
            return []
        return [making.step(item, copy, embossed, letters)]


def _letters(item: Item, copy: Copy) -> Node | None:
    """A line of letters (text.md): the pinned font's outlines, their line's box centred on the copy's point, reading the right way round from outside the face, to their depth (in, or out of, the face); None for spaces alone.

    Up is the face's second axis; they run along up cross outward.
    """
    assert copy.axes is not None and copy.span is not None
    text = item.get("text")
    assert isinstance(text, Words)
    height = _mm(item.get("height"))
    flat = _frame(copy.point, _axis(copy.axes[0]), _axis(copy.axes[1]))
    outward = np.asarray(copy.direction, dtype=float)
    sign = float(fv.matmul(np.asarray(flat.w), -outward))
    t0, t1 = sorted((sign * copy.span[0], sign * copy.span[1]))
    right = float(fv.matmul(np.cross(np.asarray(flat.v), outward), np.asarray(flat.u)))
    length = text_width(text.text, height)
    ink = Ink.of(text.text, height, right=right, at=(-right * length / 2, -height / 2))
    if ink.box is None:
        return None
    return LetterPrism(flat, Letters2D(ink, height / 10), t0, t1)


ENTRY = Text()
