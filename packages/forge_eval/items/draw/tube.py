"""How the generator draws for a tube: its entry in the ``draw`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
tube's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

import random

import numpy as np

from forge_eval.generator import (
    GAP,
    REACH,
    Array,
    DoesNotFitError,
    Feature,
    _Flat,
    _Foot,
    _Part,
    _q,
    _Round,
    _standing_tube,
    _v,
)
from forge_eval.items.draw.protocol import DrawKind
from forge_eval.truth import Copy, Prism, Step


class Tube(DrawKind):
    key = "tube"
    new_weight = 1
    new_rank = 2
    hosts_standing = True

    def footprint(
        self, f: Feature, axes: tuple[str, str]
    ) -> tuple[tuple[float, float], float]:
        s = f.sizes
        r = s["outer_diameter"] / 2
        return (r, r), r

    def first(self, f: Feature, part: _Part) -> None:
        s = f.sizes
        origin = np.zeros(3)
        r, inner, length = s["outer_diameter"] / 2, s["inner_diameter"] / 2, s["length"]
        part.copies[f.id] = [
            Copy(f.id, 0, None, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), ("x", "y"))
        ]
        z = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        part.steps.append(Step(f.id, 0, True, Prism(*z, (r, r), r, 0.0, length)))
        # The bore all the way through (tube.md), carried on past both ends into the air.
        part.steps.append(
            Step(
                f.id,
                0,
                False,
                Prism(*z, (inner, inner), inner, 0.0, length),
                (REACH, REACH),
            )
        )
        for end, height, up in (("+end", length, 1.0), ("-end", 0.0, -1.0)):
            part.flats[(f.id, 0, end)] = _Flat((f.id, 0, end), _v((0.0, 0.0, height)), _v((0.0, 0.0, up)), ("x", "y"),
                                               "ring", (r, r), length, (f.id, 0, "-end" if up > 0 else "+end"),
                                               inner=inner)  # fmt: skip
        part.rounds[(f.id, 0, "side")] = _Round(
            (f.id, 0, "side"), "z", origin.copy(), length, r, bore=inner
        )
        return

    def rise(self, f: Feature) -> float:
        s = f.sizes
        return s["length"]

    def faces_of(self, f: Feature) -> tuple[str, ...]:
        return ("+end", "-end", "side")

    def stand_flat(self, f: Feature, copy_index: int, p: Array, n: Array, e1: Array, e2: Array, face: _Flat,
                   part: _Part, strict: bool, feet: list[_Foot], k: int, beyond: frozenset[tuple[int, float]],
                   flush: frozenset[tuple[int, float]]) -> None:  # fmt: skip
        _standing_tube(f, copy_index, p, n, face, part)

    def limits(self, f: Feature) -> None:
        s = f.sizes
        if not s["inner_diameter"] < s["outer_diameter"] - 2 * GAP:
            raise DoesNotFitError(f"{f.id}: a tube's bore is narrower than its outside")

    def draw_new(
        self, rng: random.Random, face: _Flat, top: float, choices: dict[str, str]
    ) -> dict[str, float]:
        outer = _q(rng.uniform(2.5, max(2.6, top)))
        wall = rng.uniform(0.8, max(0.9, outer - 1.0))
        sizes = {
            "outer_diameter": _q(2 * outer),
            "inner_diameter": _q(2 * (outer - wall)),
            "length": _q(rng.uniform(2, 15)),
        }
        return sizes


ENTRY = Tube()
