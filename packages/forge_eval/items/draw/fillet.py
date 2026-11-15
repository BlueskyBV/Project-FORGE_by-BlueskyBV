"""How the generator draws for a fillet: its entry in the ``draw`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
fillet's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from forge_eval.generator import Feature, Plan, _Part, _rounding
from forge_eval.items.draw.protocol import DrawKind


class Fillet(DrawKind):
    key = "fillet"
    follows_roundings = True
    rounds_edges = True

    def build_one(self, f: Feature, plan: Plan, part: _Part, strict: bool) -> None:
        _rounding(f, plan, part, strict)
        return


ENTRY = Fillet()
