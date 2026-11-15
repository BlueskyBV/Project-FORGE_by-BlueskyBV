"""How the generator draws for a cone: its entry in the ``draw`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
cone's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

import random

from forge_eval.generator import (
    Array,
    DoesNotFitError,
    Feature,
    _Flat,
    _Foot,
    _Part,
    _q,
    _standing_cone,
    _under,
)
from forge_eval.items.draw.protocol import DrawKind


class Cone(DrawKind):
    key = "cone"
    new_weight = 1
    new_rank = 1
    may_be_zero = frozenset({"top_diameter"})

    def footprint(
        self, f: Feature, axes: tuple[str, str]
    ) -> tuple[tuple[float, float], float]:
        s = f.sizes
        r = s["base_diameter"] / 2  # its base (place.md: a post's base)
        return (r, r), r

    def foot_of(self, f: Feature, face: _Flat, at: tuple[float, float]) -> _Foot:
        # Its base, or its top where that is wider: what it takes up over the face, kept clear of the rest.
        r = max(f.sizes["base_diameter"], f.sizes["top_diameter"]) / 2
        return _Foot(at, (r, r), r)

    def rise(self, f: Feature) -> float:
        s = f.sizes
        return s["length"]

    def faces_of(self, f: Feature) -> tuple[str, ...]:
        return ("+end",) if f.sizes["top_diameter"] > 0 else ()

    def stand_flat(self, f: Feature, copy_index: int, p: Array, n: Array, e1: Array, e2: Array, face: _Flat,
                   part: _Part, strict: bool, feet: list[_Foot], k: int, beyond: frozenset[tuple[int, float]],
                   flush: frozenset[tuple[int, float]]) -> None:  # fmt: skip
        _standing_cone(f, copy_index, p, n, face, part, _under(face, feet[k]))

    def limits(self, f: Feature) -> None:
        if not f.sizes["top_diameter"] >= 0:
            raise DoesNotFitError(f"{f.id}: a cone's top is 0 across or more")

    def draw_new(
        self, rng: random.Random, face: _Flat, top: float, choices: dict[str, str]
    ) -> dict[str, float]:
        base = _q(rng.uniform(1.5, max(1.6, top)))
        roll = rng.random()
        tip = (
            0.0
            if roll < 0.25
            else _q(rng.uniform(0.5, 2 * base - 0.5))
            if roll < 0.85
            else _q(2 * base + rng.uniform(0.5, 4))
        )
        sizes = {
            "base_diameter": _q(2 * base),
            "top_diameter": tip,
            "length": _q(rng.uniform(2, 15)),
        }
        return sizes


ENTRY = Cone()
