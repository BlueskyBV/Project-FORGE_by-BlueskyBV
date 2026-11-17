"""Where the judge places a text: its entry in the ``place`` registry (its branches moved from ``place.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from collections.abc import Mapping

from forge_spec.draft import Item
from forge_spec.draft import Text as Words

from forge_checks.items.place.protocol import PlaceKind
from forge_checks.letters import ink_box
from forge_checks.outlines import Outline
from forge_checks.place import (
    _INDEX,
    FlatFace,
    PlaceError,
    _choice,
    _mm,
    _text_length,
    unit,
)


class Text(PlaceKind):
    key = "text"

    def turnable(self, item: Item) -> bool:
        return True

    def footprint(
        self, item: Item, diameters: Mapping[str, float], axes: tuple[str, str]
    ) -> Outline:
        return Outline.rect(_text_length(item) / 2, _mm(item, "height") / 2)

    def covers(
        self, item: Item, diameters: Mapping[str, float], face: FlatFace
    ) -> Outline | None:
        """Its ink's box: placed by their box (text.md), letters' ink reaches past it (a j's tail, an f's hook)."""
        length = _text_length(item)
        text = item.get("text")
        assert isinstance(text, Words)
        height = _mm(item, "height")
        box = ink_box(text.text, height)
        if box is None:
            return None
        (x0, y0), (x1, y1) = box
        up, out = unit("+" + face.axes[1]), unit(face.normal)
        right = (
            up[1] * out[2] - up[2] * out[1],
            up[2] * out[0] - up[0] * out[2],
            up[0] * out[1] - up[1] * out[0],
        )
        sign = right[_INDEX[face.axes[0]]]
        centre = (sign * ((x0 + x1) / 2 - length / 2), (y0 + y1) / 2 - height / 2)
        return Outline.rect((x1 - x0) / 2, (y1 - y0) / 2, centre)

    def embossed(self, item: Item) -> bool:
        return _choice(item, "mode") == "emboss"

    def cut_through(self, item: Item) -> None:
        raise PlaceError(item.id, "letters are cut to a depth, never through")


ENTRY = Text()
