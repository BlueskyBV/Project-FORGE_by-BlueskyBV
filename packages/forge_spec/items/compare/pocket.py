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
            hexagon = _choice(item, "shape") == "hexagon"  # its box across the face, and its size across its flats
            found += cut_features(n, item, copy, layout, material, diameter,
                                  lambda h1, h2: corner_rounded(item, h1, h2),
                                  "hexagonal cut" if hexagon else "square cut",
                                  (_r(_length(item, "across_flats") or 0.0),) if hexagon else ())  # fmt: skip
        return found


ENTRY = Pocket()
