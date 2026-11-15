"""How the generator draws for a region: its entry in the ``draw`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
region's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from forge_eval.items.draw.protocol import DrawKind


class Region(DrawKind):
    key = "region"


ENTRY = Region()
