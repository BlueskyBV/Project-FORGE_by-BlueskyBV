"""Where the judge places a thread: its entry in the ``place`` registry (its branches moved from ``place.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_checks.items.place.protocol import PlaceKind


class Thread(PlaceKind):
    key = "thread"

    made_last = True


ENTRY = Thread()
