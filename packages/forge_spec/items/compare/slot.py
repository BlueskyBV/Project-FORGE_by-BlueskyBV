"""What the two-draft comparison reads of a slot: its entry in the ``compare`` registry (its branches moved from ``compare.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.draft import Item
from forge_spec.items.compare._common import (
    Feature,
    _choice,
    _length,
    cut_features,
    cut_material,
)
from forge_spec.items.compare.protocol import CompareKind
from forge_spec.placement import Layout


class Slot(CompareKind):
    key = "slot"

    def features(self, n: int, item: Item, layout: Layout) -> list[Feature]:
        found: list[Feature] = []
        for copy in layout.instances.get(item.id, ()):
            material = cut_material(copy, layout)
            if material is None:  # pragma: no cover - a placed cut has its face
                continue
            found += cut_features(n, item, copy, layout, material, None,
                                  lambda h1, h2: self.corner(item, h1, h2))  # fmt: skip
        return found

    def corner(self, item: Item, h1: float, h2: float) -> float:
        """How a slot's corners are rounded, seen looking into it: a round-ended slot's are half its width."""
        width, length = _length(item, "width") or 0.0, _length(item, "length") or 0.0
        return (
            width / 2 if _choice(item, "ends") == "round" and length >= width else 0.0
        )


ENTRY = Slot()
