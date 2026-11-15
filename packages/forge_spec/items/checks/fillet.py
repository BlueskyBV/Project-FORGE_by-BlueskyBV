"""What the spec checks read of a fillet: its entry in the ``checks`` registry (its branches moved from ``checks.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.draft import Item, PartSpec
from forge_spec.items.checks._common import Collect, check_rounding
from forge_spec.items.checks.protocol import SpecCheckKind
from forge_spec.placement import Layout


class Fillet(SpecCheckKind):
    key = "fillet"

    def physical(
        self, spec: PartSpec, item: Item, at: str, layout: Layout, c: Collect
    ) -> None:
        check_rounding(spec, item, at, layout, c, "radius")


ENTRY = Fillet()
