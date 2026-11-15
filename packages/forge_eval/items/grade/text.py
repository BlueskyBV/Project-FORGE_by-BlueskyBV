"""What spec grading reads for a text: its entry in the ``grade`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
text's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from forge_spec.draft import Item

from forge_eval.items.grade.protocol import GradeKind
from forge_eval.spec_grade import _choice


class Text(GradeKind):
    key = "text"

    def raised(self, item: Item) -> bool:
        return _choice(item, "mode") == "emboss"


ENTRY = Text()
