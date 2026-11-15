"""What the spec checks read of a sphere: its entry in the ``checks`` registry (its branches moved from ``checks.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.draft import Choice, Item
from forge_spec.items.checks._common import size_of
from forge_spec.items.checks.protocol import SpecCheckKind
from forge_spec.placement import Layout


class Sphere(SpecCheckKind):
    key = "sphere"

    def rounding_limit(self, target: Item, which: str, layout: Layout) -> float | None:
        diameter = size_of(target, "diameter")
        return None if diameter is None else diameter / 2

    def edges_missing(
        self, target: Item, which: str, layout: Layout
    ) -> tuple[str, str] | None:
        if which == "bottom":
            portion = target.get("portion")
            if isinstance(portion, Choice) and portion.value == "whole":
                return "fault", f"{target.id} is a whole ball: it has no rim to round"
        return super().edges_missing(target, which, layout)


ENTRY = Sphere()
