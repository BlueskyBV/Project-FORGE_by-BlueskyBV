"""What the two-draft comparison reads of a hole: its entry in the ``compare`` registry (its branches moved from ``compare.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.draft import Item
from forge_spec.items.compare._common import (
    Feature,
    _r,
    corner_rounded,
    cut_features,
    cut_material,
)
from forge_spec.items.compare.protocol import CompareKind
from forge_spec.placement import Instance, Layout


class Hole(CompareKind):
    key = "hole"

    def features(self, n: int, item: Item, layout: Layout) -> list[Feature]:
        found: list[Feature] = []
        for copy in layout.instances.get(item.id, ()):
            material = cut_material(copy, layout)
            if material is None:  # pragma: no cover - a placed cut has its face
                continue
            diameter = layout.diameters.get(item.id, 0.0)
            found += cut_features(n, item, copy, layout, material, diameter,
                                  lambda h1, h2: corner_rounded(item, h1, h2))  # fmt: skip
        return found

    def cut_outline(
        self, item: Item, copy: Instance, layout: Layout
    ) -> tuple[object, ...]:
        return (_r(layout.diameters.get(item.id, 0.0)),)


ENTRY = Hole()
