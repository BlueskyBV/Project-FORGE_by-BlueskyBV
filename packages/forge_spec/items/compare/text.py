"""What the two-draft comparison reads of a text: its entry in the ``compare`` registry (its branches moved from ``compare.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.draft import Item, Place
from forge_spec.draft import Text as Words
from forge_spec.geometry import Vec
from forge_spec.items.compare._common import (
    _INDEX,
    Feature,
    _axis,
    _choice,
    _length,
    _r,
    cut_material,
)
from forge_spec.items.compare.protocol import CompareKind
from forge_spec.items.solve._common import _turn, degrees
from forge_spec.placement import Layout


class Text(CompareKind):
    key = "text"

    def features(self, n: int, item: Item, layout: Layout) -> list[Feature]:
        found: list[Feature] = []
        for copy in layout.instances.get(item.id, ()):
            if (
                cut_material(copy, layout) is None
            ):  # pragma: no cover - a placed cut has its face
                continue
            kind = item.kind
            mouth = copy.origin
            assert copy.face_axes is not None
            # Letters read the right way round from outside the face: up is the
            # face's second axis, and they run along up x outward
            # (docs/definitions/text.md), so text on a -z face runs along -x.
            rises = _axis(_INDEX[copy.face_axes[1]])
            turned = _turned_up(item, copy.face_axes)
            if turned is not None:  # turned in the face's plane, up with them (1b's first move)
                rises = turned
            out = copy.normal
            reads = (
                rises[1] * out[2] - rises[2] * out[1],
                rises[2] * out[0] - rises[0] * out[2],
                rises[0] * out[1] - rises[1] * out[0],
            )
            letters = item.get("text")
            found += [Feature(n, item.id, kind, "text", None, mouth,
                              (letters.text if isinstance(letters, Words) else None, _choice(item, "mode"),
                               _r(_length(item, "height") or 0.0), _r(_length(item, "depth") or 0.0)),
                              ((copy.normal, True), (reads, True), (rises, True)))]  # fmt: skip
        return found


def _turned_up(item: Item, axes: tuple[str, str]) -> Vec | None:
    """The way up a line of letters turned in its face's plane: the face's second axis, turned from its first
    towards it; None if it isn't turned."""
    place = item.get("place")
    if not isinstance(place, Place) or place.turn is None:
        return None
    c, s = _turn(degrees(place.turn))
    first, second = _axis(_INDEX[axes[0]]), _axis(_INDEX[axes[1]])
    return (-s * first[0] + c * second[0] + 0.0, -s * first[1] + c * second[1] + 0.0,
            -s * first[2] + c * second[2] + 0.0)  # fmt: skip


ENTRY = Text()
