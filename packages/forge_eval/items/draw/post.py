"""How the generator draws for a post: its entry in the ``draw`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
post's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from forge_eval.generator import (
    Feature,
    Plan,
    _drop_covered,
    _earlier_vertical,
    _Flat,
    _Part,
    _Round,
    _round_box,
    _standing_round,
)
from forge_eval.items.draw.protocol import DrawKind
from forge_eval.truth import Copy


class Post(DrawKind):
    key = "post"
    flat_weight = 1
    flat_rank = 4
    drawn_flush = True
    stands_flush = True
    stand_height = "height"

    def on_round(
        self, f: Feature, side: _Round, index: int, part: _Part, strict: bool
    ) -> list[Copy]:
        return _standing_round(f, side, index, part, strict)

    def faces_of(self, f: Feature) -> tuple[str, ...]:
        return ("+x", "-x", "+y", "-y", "+z", "-z")

    def roundable(self, first: bool) -> tuple[str, ...]:
        return () if first else ("vertical", "top", "joint")

    def most_rounding(self, target: Feature, which: str) -> tuple[str, float]:
        s = target.sizes
        across, height = min(s["length"], s["width"]) / 2, s["height"]
        most = {"vertical": across, "top": min(across, height), "bottom": min(across, height),
                "all": min(across, height / 2), "joint": min(height, 3.0)}[which]  # fmt: skip
        return which, most

    def rounded(self, f: Feature, target: Feature, copy: Copy, which: str, size: float, part: _Part,
                host: _Flat | None, strict: bool, plan: Plan) -> None:  # fmt: skip
        _round_box(
            f,
            target,
            copy,
            which,
            size,
            part,
            host,
            strict,
            _earlier_vertical(f, target, plan),
        )

    def after_rounding(
        self, f: Feature, target: Feature, part: _Part, made: int, strict: bool
    ) -> None:
        _drop_covered(f, target, part, made, strict)


ENTRY = Post()
