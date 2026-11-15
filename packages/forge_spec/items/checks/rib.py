"""What the spec checks read of a rib: its entry in the ``checks`` registry (its branches moved from ``checks.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.draft import Item
from forge_spec.items.checks._common import size_of
from forge_spec.items.checks.protocol import SpecCheckKind
from forge_spec.placement import Layout


class Rib(SpecCheckKind):
    key = "rib"

    def rounding_limit(self, target: Item, which: str, layout: Layout) -> float | None:
        def s(name: str) -> float | None:
            return size_of(target, name)

        length, thickness, height = s("length"), s("thickness"), s("height")
        if length is None or thickness is None or height is None:
            return None
        return {
            "vertical": min(length, thickness) / 2,
            "top": min(thickness / 2, height),
        }.get(which)


ENTRY = Rib()
