"""What the two-draft comparison reads of a text: its entry in the ``compare`` registry (its branches moved from ``compare.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.draft import Item
from forge_spec.draft import Text as Words
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


ENTRY = Text()
