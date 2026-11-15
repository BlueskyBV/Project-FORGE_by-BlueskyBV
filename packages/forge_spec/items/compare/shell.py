"""What the two-draft comparison reads of a shell: its entry in the ``compare`` registry (its branches moved from ``compare.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.draft import Faces, Item
from forge_spec.items.compare._common import (
    Feature,
    _face_direction,
    _length,
    _mid,
    _r,
    _sub,
)
from forge_spec.items.compare.protocol import CompareKind
from forge_spec.placement import Layout


class Shell(CompareKind):
    key = "shell"

    def features(self, n: int, item: Item, layout: Layout) -> list[Feature]:
        """A hollow by its cavity."""
        kind = item.kind
        of = item.get("of")
        if not isinstance(of, str):  # pragma: no cover - a checked draft names its body
            return []
        found: list[Feature] = []
        for copy in layout.instances.get(of, ()):
            if copy.lo is None or copy.hi is None:
                continue
            opened = item.get("open")
            faces = opened.faces if isinstance(opened, Faces) else ()
            ways = tuple((_face_direction(face, copy), True) for face in faces)
            cavity = layout.cavities.get((of, copy.index))
            if cavity is not None:
                found.append(Feature(n, item.id, kind, "hollow", _sub(cavity[1], cavity[0]), _mid(*cavity),
                                     ("hollow", len(faces)), ways, field="thickness", of=of))  # fmt: skip
            else:  # a ball's or a dome's: its walls, as given
                thickness, floor = _length(item, "thickness"), _length(item, "floor")
                found.append(Feature(n, item.id, kind, "hollow", None, _mid(copy.lo, copy.hi),
                                     ("hollow ball", _r(thickness or 0.0), None if floor is None else _r(floor),
                                      len(faces)), ways, field="thickness", of=of))  # fmt: skip
        return found


ENTRY = Shell()
