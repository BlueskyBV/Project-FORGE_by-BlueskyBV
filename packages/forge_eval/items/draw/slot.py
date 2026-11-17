"""How the generator draws for a slot: its entry in the ``draw`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
slot's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

import random

from forge_eval.generator import DoesNotFitError, Feature, _Flat, _q
from forge_eval.items.draw.protocol import DrawKind


class Slot(DrawKind):
    key = "slot"
    turnable = True
    flat_weight = 1
    flat_rank = 2
    cut_out = True

    def footprint(
        self, f: Feature, axes: tuple[str, str]
    ) -> tuple[tuple[float, float], float]:
        s = f.sizes
        long, short = s["length"] / 2, s["width"] / 2
        corner = short if f.choices["ends"] == "round" else 0.0
        return (
            (long, short) if f.choices["along"] == axes[0] else (short, long)
        ), corner

    def limits(self, f: Feature) -> None:
        s = f.sizes
        if s["length"] < s["width"]:
            raise DoesNotFitError(f"{f.id}: a slot is no shorter than it is wide")

    def draw_on_flat(self, rng: random.Random, face: _Flat, top: float, sizes: dict[str, float],
                     choices: dict[str, str]) -> tuple[str, float, float] | None:  # fmt: skip
        sizes["width"] = _q(rng.uniform(2, max(2.2, top / 1.5)))
        choices["along"] = rng.choice(face.axes)
        choices["ends"] = rng.choice(["round", "square"])
        as_long = choices["ends"] == "round" and rng.random() < 0.2  # a circle
        sizes["length"] = (
            sizes["width"] if as_long else _q(sizes["width"] + rng.uniform(2, top * 2))
        )
        return None


ENTRY = Slot()
