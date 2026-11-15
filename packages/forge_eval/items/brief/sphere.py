"""How the generated brief says for a sphere: its entry in the ``brief`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
sphere's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

from forge_eval.items.brief.protocol import BriefKind


class Sphere(BriefKind):
    key = "sphere"
    names_itself = False
    option_words: ClassVar[Mapping[str, Mapping[str, str]]] = {
        "portion": {"whole": "ball", "upper_half": "dome"}
    }


ENTRY = Sphere()
