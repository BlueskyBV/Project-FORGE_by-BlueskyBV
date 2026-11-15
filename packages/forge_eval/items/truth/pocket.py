"""What the generator's shape model checks for a pocket: its entry in the ``truth`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
pocket's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from forge_eval.items.truth.protocol import TruthKind


class Pocket(TruthKind):
    key = "pocket"
    sided = True


ENTRY = Pocket()
