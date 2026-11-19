"""What the spec checks read of a pocket: its entry in the ``checks`` registry (its branches moved from ``checks.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.draft import Item
from forge_spec.items.checks._common import cut_rounding_limit, size_of
from forge_spec.items.checks.protocol import SpecCheckKind
from forge_spec.placement import Layout


class Pocket(SpecCheckKind):
    key = "pocket"

    def rounding_limit(self, target: Item, which: str, layout: Layout) -> float | None:
        def s(name: str) -> float | None:
            return size_of(target, name)

        deepest = cut_rounding_limit(target, layout)
        if which == "bottom":
            # An inside rounding round the floor: its ball within the pocket, and round a rounded corner within
            # the corner's own radius (it can't reach past the corner's axis).
            depth = s("depth")
            across = s("diameter") or s("across_flats") or min(s("length") or 0.0, s("width") or 0.0)
            corner = s("corner_radius") or 0.0
            most = corner if corner > 0 else across / 2
            return None if depth is None else min(depth, most)
        return deepest

    def edges_missing(self, target: Item, which: str, layout: Layout) -> tuple[str, str] | None:
        choice = target.get("shape")
        if getattr(choice, "value", None) == "profile":
            return "unable", (f"{target.id} is a pocket of its own outline: Forge doesn't round or bevel its edges "
                              "yet")  # fmt: skip
        return super().edges_missing(target, which, layout)


ENTRY = Pocket()
