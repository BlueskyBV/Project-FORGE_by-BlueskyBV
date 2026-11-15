"""What the spec checks read of a tab: its entry in the ``checks`` registry (its branches moved from ``checks.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.draft import Item
from forge_spec.items.checks._common import size_of
from forge_spec.items.checks.protocol import SpecCheckKind
from forge_spec.placement import Layout


class Tab(SpecCheckKind):
    key = "tab"

    def rounding_limit(self, target: Item, which: str, layout: Layout) -> float | None:
        def s(name: str) -> float | None:
            return size_of(target, name)

        width, thickness, length = s("width"), s("thickness"), s("length")
        if width is None or thickness is None or length is None:
            return None
        return {
            "vertical": min(width, thickness) / 2,
            "top": min(thickness / 2, width / 2, length),
        }.get(which)


ENTRY = Tab()
