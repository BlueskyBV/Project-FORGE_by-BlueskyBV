"""How the solver places a chamfer: its entry in the ``solve`` registry (its branches moved from ``placement.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.items.solve.protocol import SolveKind

if TYPE_CHECKING:
    pass


class Chamfer(SolveKind):
    key = "chamfer"

    rounding = True
    made_last = True


ENTRY = Chamfer()
