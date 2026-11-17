"""How the generator draws for a rib: its entry in the ``draw`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
rib's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

import random

from forge_eval.generator import Feature, _Flat, _q
from forge_eval.items.draw.protocol import DrawKind


class Rib(DrawKind):
    key = "rib"
    turnable = True
    new_weight = 2
    new_rank = 0
    stand_height = "height"

    def footprint(
        self, f: Feature, axes: tuple[str, str]
    ) -> tuple[tuple[float, float], float]:
        s = f.sizes
        run, across = s["length"] / 2, s["thickness"] / 2
        return ((run, across) if f.choices["along"] == axes[0] else (across, run)), 0.0

    def faces_of(self, f: Feature) -> tuple[str, ...]:
        return ("+x", "-x", "+y", "-y", "+z", "-z")

    def draw_new(
        self, rng: random.Random, face: _Flat, top: float, choices: dict[str, str]
    ) -> dict[str, float]:
        choices["along"] = rng.choice(face.axes)
        thickness = _q(rng.uniform(1.0, max(1.1, top / 2)))
        sizes = {"length": _q(rng.uniform(2 * thickness, max(2 * thickness + 0.1, top * 2))), "thickness": thickness,
                 "height": _q(rng.uniform(2, 12))}  # fmt: skip
        return sizes


ENTRY = Rib()
