"""How the generated brief says for a pocket: its entry in the ``brief`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
pocket's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

from forge_eval.items.brief.protocol import BriefKind


class Pocket(BriefKind):
    key = "pocket"
    cut_out = True
    option_words: ClassVar[Mapping[str, Mapping[str, str]]] = {
        "shape": {"rectangle": "rectangular", "circle": "round", "hexagon": "hexagonal"}
    }


ENTRY = Pocket()
