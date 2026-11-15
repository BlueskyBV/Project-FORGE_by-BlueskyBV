"""What the generator's shape model checks for a chamfer: its entry in the ``truth`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
chamfer's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from forge_eval.items.truth.protocol import TruthKind


class Chamfer(TruthKind):
    key = "chamfer"


ENTRY = Chamfer()
