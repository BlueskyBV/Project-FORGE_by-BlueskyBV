"""What the two-draft comparison reads of a pocket: its entry in the ``compare`` registry (its branches moved from ``compare.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.draft import Item
from forge_spec.items.compare._common import (
    Feature,
    _choice,
    _length,
    _r,
    corner_rounded,
    cut_features,
    cut_material,
    outline_area,
)
from forge_spec.items.compare.protocol import CompareKind
from forge_spec.placement import Layout


class Pocket(CompareKind):
    key = "pocket"

    corner_field = "corner_radius"

    def features(self, n: int, item: Item, layout: Layout) -> list[Feature]:
        found: list[Feature] = []
        for copy in layout.instances.get(item.id, ()):
            material = cut_material(copy, layout)
            if material is None:  # pragma: no cover - a placed cut has its face
                continue
            diameter = (
                _length(item, "diameter") or 0.0
                if _choice(item, "shape") == "circle"
                else None
            )
            # Its box across the face, and a hexagon's size across its flats, an outline's area.
            shape = _choice(item, "shape")
            own: tuple[object, ...] = ()
            if shape == "hexagon":
                own = (_r(_length(item, "across_flats") or 0.0),)
            elif shape == "profile":
                area = outline_area(item)
                own = (_r(area),) if area is not None else ()
            found += cut_features(n, item, copy, layout, material, diameter,
                                  lambda h1, h2: corner_rounded(item, h1, h2),
                                  {"hexagon": "hexagonal cut", "profile": "profiled cut"}.get(str(shape), "square cut"),
                                  own)  # fmt: skip
        return found


ENTRY = Pocket()
