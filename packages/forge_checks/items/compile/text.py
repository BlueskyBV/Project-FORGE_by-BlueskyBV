"""What the check compiler holds for a text: its entry in the ``compile`` registry (its branches moved from ``compiler.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_numeric import scalar as fs
from forge_spec.draft import Item
from forge_spec.draft import Text as Words

from forge_checks.items.compile._common import _mm, _t, _v, leaves
from forge_checks.items.compile.protocol import CompileKind
from forge_checks.kinds.size import Between
from forge_checks.kinds.surfaces import Plane
from forge_checks.letters import ink_box, line_length

if TYPE_CHECKING:
    from forge_checks.items.compile._context import CompileContext


class Text(CompileKind):
    key = "text"

    def checks(self, c: CompileContext, item: Item) -> None:
        """Letters (text.md): how deep they are cut, or how high they stand, from the face round them; the face they are on and their mode, told from the others; their outlines, size and place, held by face accounting (docs/V2-stage4.md, 7.1).

        The floor (or top) is looked for within the letters' reach of their
        point: the ink's box's far corner. A tenth of a capital's height is
        the font's finest detail (the gap under an accent, a letter's eye),
        the feature size the coverage radius is set by.
        """
        text = item.get("text")
        assert isinstance(text, Words), "letters have their text"
        height = _mm(item.get("height"))
        ink = ink_box(text.text, height)
        if ink is None:
            c._not_placed(item, "spaces alone: there are no letters to check")
            return
        c.size(item, height / 10)
        (x0, y0), (x1, y1) = ink
        middle = line_length(text.text, height) / 2
        reach = fs.hypot(
            max(abs(x0 - middle), abs(x1 - middle)),
            max(abs(y0 - height / 2), abs(y1 - height / 2)),
        )
        embossed = c._choice_value(item, "mode") == "emboss"
        for copy in c.copies(item):
            assert copy.span is not None
            depth = copy.span[1] - copy.span[0]
            if not embossed:
                c._cut_depth(item, copy, 0.0, reach, depth)
                continue
            top = Plane(
                _t(_v(copy.point) + depth * _v(copy.direction)), copy.direction, reach
            )
            base = Plane(copy.point, copy.direction, reach + 4.0)
            if not (c.seen(top) and c.seen(base)):
                c.skip(
                    item,
                    "depth",
                    "their tops or the face round them isn't on the part's surface",
                )
                continue
            c.check(item, "depth", "size", depth, c.tol(item.get("depth")), Between(top, base, copy.direction),
                       copy.index)  # fmt: skip
            c.size(item, depth)
        c._on(item)
        c._choice(item, "mode")
        for name in leaves(item):
            if name not in ("on", "depth", "mode"):
                c.skip(item, name, "letters' outlines have no single size: face accounting holds every point "
                          "of the built letters to the font's", held_by="face accounting")  # fmt: skip

    implicit = False


ENTRY = Text()
