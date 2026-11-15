"""What the two-draft comparison reads for a revolution: its entry in the ``compare`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
revolution's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from forge_spec.items.compare.protocol import CompareKind


class Revolution(CompareKind):
    key = "revolution"


ENTRY = Revolution()
