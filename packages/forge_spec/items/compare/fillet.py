"""What the two-draft comparison reads of a fillet: its entry in the ``compare`` registry (its branches moved from ``compare.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.draft import Item
from forge_spec.items.compare._common import Feature, rounding_features
from forge_spec.items.compare.protocol import CompareKind
from forge_spec.placement import Layout


class Fillet(CompareKind):
    key = "fillet"

    def features(self, n: int, item: Item, layout: Layout) -> list[Feature]:
        return rounding_features(n, item, layout, "radius")


ENTRY = Fillet()
