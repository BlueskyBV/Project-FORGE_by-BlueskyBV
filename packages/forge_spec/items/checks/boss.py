"""What the spec checks read of a boss: its entry in the ``checks`` registry (its branches moved from ``checks.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.draft import Item
from forge_spec.items.checks._common import rod_rounding_limit
from forge_spec.items.checks.protocol import SpecCheckKind
from forge_spec.placement import Layout


class Boss(SpecCheckKind):
    key = "boss"

    threadable = True

    def rounding_limit(self, target: Item, which: str, layout: Layout) -> float | None:
        return rod_rounding_limit(target, which)


ENTRY = Boss()
