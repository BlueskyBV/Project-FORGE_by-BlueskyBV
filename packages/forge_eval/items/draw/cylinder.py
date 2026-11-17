"""How the generator draws for a cylinder: its entry in the ``draw`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
cylinder's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

import random
from collections.abc import Callable

import numpy as np

from forge_eval.generator import (
    Feature,
    Plan,
    _Flat,
    _hollow_cylinder,
    _Part,
    _Round,
    _round_rod,
    _v,
)
from forge_eval.items.draw.protocol import DrawKind
from forge_eval.truth import Copy, Prism, Step


class Cylinder(DrawKind):
    key = "cylinder"
    openable = ("+end", "-end")
    hosts_standing = True
    threadable = True
    round_far_end = True

    def footprint(
        self, f: Feature, axes: tuple[str, str]
    ) -> tuple[tuple[float, float], float]:
        s = f.sizes
        r = s["diameter"] / 2
        return (r, r), r

    def first(self, f: Feature, part: _Part) -> None:
        s = f.sizes
        origin = np.zeros(3)
        r, length = s["diameter"] / 2, s["length"]
        part.copies[f.id] = [
            Copy(f.id, 0, None, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), ("x", "y"))
        ]
        part.steps.append(Step(f.id, 0, True, Prism((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0),
                                                     (r, r), r, 0.0, length)))  # fmt: skip
        part.flats[(f.id, 0, "+end")] = _Flat((f.id, 0, "+end"), _v((0, 0, length)), _v((0, 0, 1)), ("x", "y"), "disc",
                                              (r, r), length, (f.id, 0, "-end"), level=True)  # fmt: skip
        part.flats[(f.id, 0, "-end")] = _Flat((f.id, 0, "-end"), origin.copy(), _v((0, 0, -1)), ("x", "y"), "disc",
                                              (r, r), length, (f.id, 0, "+end"), level=True)  # fmt: skip
        part.rounds[(f.id, 0, "side")] = _Round(
            (f.id, 0, "side"), "z", origin.copy(), length, r
        )
        return

    def rise(self, f: Feature) -> float:
        s = f.sizes
        return s["length"]

    def faces_of(self, f: Feature) -> tuple[str, ...]:
        return ("+end", "-end", "side")

    def roundable(self, first: bool) -> tuple[str, ...]:
        return ("top", "bottom", "both") if first else ()

    def shell_opening(
        self, rng: random.Random, body: Feature
    ) -> tuple[float, tuple[str, ...], float]:
        s = body.sizes
        least = min(s["diameter"] / 2, s["length"])
        opened = rng.choice(((), ("+end",), ("+end",), ("-end",), ("+end", "-end")))
        across = s["length"]
        return least, opened, across

    def hollow(self, f: Feature, body: Feature, plan: Plan, part: _Part, t: float, floor: float, opened: set[str],
               wall: Callable[[str], float]) -> None:  # fmt: skip
        _hollow_cylinder(f, body, part, t, wall, opened)

    def most_rounding(self, target: Feature, which: str) -> tuple[str, float]:
        s = target.sizes
        r, height = s["diameter"] / 2, s.get("length", s.get("height", 0.0))
        most = {"top": min(r, height), "bottom": min(r, height), "both": min(r, height / 2),
                "joint": min(height, 3.0)}[which]  # fmt: skip
        return which, most

    def rounded(self, f: Feature, target: Feature, copy: Copy, which: str, size: float, part: _Part,
                host: _Flat | None, strict: bool, plan: Plan) -> None:  # fmt: skip
        _round_rod(f, target, copy, which, size, part, host, strict)


ENTRY = Cylinder()
