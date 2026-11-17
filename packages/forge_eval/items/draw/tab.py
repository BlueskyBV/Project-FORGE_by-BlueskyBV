"""How the generator draws for a tab: its entry in the ``draw`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
tab's branches here (V2-stage4b-0b.md, 7).
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
    _round_tab,
)
from forge_eval.items.draw.protocol import DrawKind


class Tab(DrawKind):
    key = "tab"
    flat_weight = 1
    flat_rank = 6

    def footprint(
        self, f: Feature, axes: tuple[str, str]
    ) -> tuple[tuple[float, float], float]:
        s = f.sizes
        thin, t, w = f.choices["thickness_along"], s["thickness"] / 2, s["width"] / 2
        return ((t, w) if thin == axes[0] else (w, t)), 0.0

    def rise(self, f: Feature) -> float:
        s = f.sizes
        return s["length"]

    def faces_of(self, f: Feature) -> tuple[str, ...]:
        return ("+x", "-x", "+y", "-y", "+z", "-z")

    def stand_flat(self, f: Feature, copy_index: int, p: Array, n: Array, e1: Array, e2: Array, face: _Flat,
                   part: _Part, strict: bool, feet: list[_Foot], k: int, beyond: frozenset[tuple[int, float]],
                   flush: frozenset[tuple[int, float]]) -> None:  # fmt: skip
        if f.choices["end"] != "round":
            super().stand_flat(
                f, copy_index, p, n, e1, e2, face, part, strict, feet, k, beyond, flush
            )
            return
        _round_tab(f, copy_index, p, n, face, part, None if f.turn is None else (e1, e2))

    def limits(self, f: Feature) -> None:
        s = f.sizes
        if f.choices.get("end") == "round" and s["length"] < s["width"] / 2:
            raise DoesNotFitError(
                f"{f.id}: a round-ended tab sticks out at least half its width"
            )

    def draw_on_flat(self, rng: random.Random, face: _Flat, top: float, sizes: dict[str, float],
                     choices: dict[str, str]) -> tuple[str, float, float] | None:  # fmt: skip
        choices["thickness_along"] = rng.choice(face.axes)
        choices["end"] = rng.choice(["round", "square"])
        sizes["thickness"] = _q(rng.uniform(2, max(2.2, top)))
        r = _q(rng.uniform(2, max(2.2, top)))
        sizes["width"] = 2 * r
        all_disc = choices["end"] == "round" and rng.random() < 0.25
        sizes["length"] = r if all_disc else _q(r + rng.uniform(1, 14))
        return None


ENTRY = Tab()
