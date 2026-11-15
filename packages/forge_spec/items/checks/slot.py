"""What the spec checks read of a slot: its entry in the ``checks`` registry (its branches moved from ``checks.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.draft import Item
from forge_spec.items.checks._common import cut_rounding_limit
from forge_spec.items.checks.protocol import SpecCheckKind
from forge_spec.placement import Layout


class Slot(SpecCheckKind):
    key = "slot"

    def rounding_limit(self, target: Item, which: str, layout: Layout) -> float | None:
        return cut_rounding_limit(target, layout)


ENTRY = Slot()
