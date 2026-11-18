"""How the generator draws for a boss: its entry in the ``draw`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
boss's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

import random

from forge_eval.generator import (
    Feature,
    Plan,
    _Flat,
    _Part,
    _q,
    _Round,
    _round_rod,
    _standing_round,
)
from forge_eval.items.draw.protocol import DrawKind
from forge_eval.truth import Copy


class Boss(DrawKind):
    key = "boss"
    on_ball = True
    ball_weight = 3
    ball_rank = 2

    def ball_sizes(self, rng: random.Random, radius: float) -> tuple[dict[str, float], float | None, float]:
        sizes = {"diameter": _q(rng.uniform(1.5, max(1.6, radius / 2.5))),
                 "height": _q(rng.uniform(1.0, max(1.1, min(10.0, radius))))}  # fmt: skip
        return sizes, None, sizes["diameter"] / 2
    leans = True
    flat_weight = 1
    flat_rank = 3
    drawn_tangent = True
    threadable = True
    rod_length = "height"
    round_foot = True
    leans_round = True
    stands_flush = True
    stand_height = "height"
    falls_flush = True
    round_far_end = True

    def footprint(
        self, f: Feature, axes: tuple[str, str]
    ) -> tuple[tuple[float, float], float]:
        s = f.sizes
        r = s["diameter"] / 2
        return (r, r), r

    def on_round(
        self, f: Feature, side: _Round, index: int, part: _Part, strict: bool
    ) -> list[Copy]:
        return _standing_round(f, side, index, part, strict)

    def faces_of(self, f: Feature) -> tuple[str, ...]:
        return ("+end",)

    def roundable(self, first: bool) -> tuple[str, ...]:
        return () if first else ("top", "joint")

    def draw_on_flat(self, rng: random.Random, face: _Flat, top: float, sizes: dict[str, float],
                     choices: dict[str, str]) -> tuple[str, float, float] | None:  # fmt: skip
        sizes["diameter"], sizes["height"] = (
            _q(rng.uniform(3, top * 1.5)),
            _q(rng.uniform(2, 12)),
        )
        return None

    def most_rounding(self, target: Feature, which: str) -> tuple[str, float]:
        s = target.sizes
        r, height = s["diameter"] / 2, s.get("length", s.get("height", 0.0))
        most = {"top": min(r, height), "bottom": min(r, height), "both": min(r, height / 2),
                "joint": min(height, 3.0)}[which]  # fmt: skip
        return which, most

    def rounded(self, f: Feature, target: Feature, copy: Copy, which: str, size: float, part: _Part,
                host: _Flat | None, strict: bool, plan: Plan) -> None:  # fmt: skip
        _round_rod(f, target, copy, which, size, part, host, strict)


ENTRY = Boss()
