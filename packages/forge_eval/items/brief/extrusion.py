"""How the generated brief says for an extrusion: its entry in the ``brief`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
extrusion's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from forge_eval.items.brief.protocol import BriefKind


class Extrusion(BriefKind):
    key = "extrusion"
    article = "is an extrusion "
    names_itself = False
    axial = True


ENTRY = Extrusion()
