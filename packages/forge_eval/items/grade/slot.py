"""What spec grading reads for a slot: its entry in the ``grade`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
slot's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from forge_eval.items.grade.protocol import GradeKind


class Slot(GradeKind):
    key = "slot"
    cut_out = True


ENTRY = Slot()
