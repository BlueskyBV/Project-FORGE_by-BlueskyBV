"""What the oracle makes for a fillet: its entry in the ``oracle`` registry (its branches moved from ``oracle.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item

from forge_checks.items.oracle.protocol import OracleKind

if TYPE_CHECKING:
    from forge_checks.oracle import Step, _Making
    from forge_checks.place import Step as Planned


class Fillet(OracleKind):
    key = "fillet"

    def steps(self, item: Item, planned: Planned, making: _Making) -> list[Step]:
        return making.rounding(item, planned.edges, True)


ENTRY = Fillet()
