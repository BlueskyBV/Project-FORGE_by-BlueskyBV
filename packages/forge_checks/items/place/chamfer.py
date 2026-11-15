"""Where the judge places a chamfer: its entry in the ``place`` registry (its branches moved from ``place.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_checks.items.place.protocol import PlaceKind


class Chamfer(PlaceKind):
    key = "chamfer"

    rounds_edges = True
    made_last = True


ENTRY = Chamfer()
