"""What the spec checks read of a cone: its entry in the ``checks`` registry (its branches moved from ``checks.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.draft import Item
from forge_spec.items.checks._common import size_of
from forge_spec.items.checks.protocol import SpecCheckKind
from forge_spec.placement import Layout


class Cone(SpecCheckKind):
    key = "cone"

    def rounding_limit(self, target: Item, which: str, layout: Layout) -> float | None:
        def s(name: str) -> float | None:
            return size_of(target, name)

        base, top, length = s("base_diameter"), s("top_diameter"), s("length")
        if base is None or top is None or length is None:
            return None
        return {"top": min(top / 2, length), "bottom": min(base / 2, length),
                "both": min(top / 2, base / 2, length / 2)}.get(which)  # fmt: skip


ENTRY = Cone()
