"""How the confirmation views draw for a thread: its entry in the ``views`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
thread's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from forge_spec.items.views.protocol import ViewKind


class Thread(ViewKind):
    key = "thread"


ENTRY = Thread()
