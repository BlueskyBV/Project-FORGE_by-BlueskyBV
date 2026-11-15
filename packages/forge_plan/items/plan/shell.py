"""What the planner writes for a shell: its entry in the ``plan`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
shell's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_plan.items.plan.protocol import PlanKind

if TYPE_CHECKING:
    pass

Vec = tuple[float, float, float]


class Shell(PlanKind):
    key = "shell"

    hollows = True


ENTRY = Shell()
