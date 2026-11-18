"""How the generator draws for a sphere: its entry in the ``draw`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
sphere's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

import random
from collections.abc import Callable

import numpy as np

from forge_eval.generator import (
    GAP,
    Array,
    DoesNotFitError,
    Feature,
    Plan,
    _Ball,
    _ball,
    _Flat,
    _Foot,
    _hollow_dome,
    _named,
    _Part,
    _q,
    _t,
    _v,
)
from forge_eval.items.draw.protocol import DrawKind
from forge_eval.truth import Copy, Step, Turned, unit_of


class Sphere(DrawKind):
    key = "sphere"
    new_weight = 1
    new_rank = 3
    openable = ("-end",)
    hosts_standing = True

    def footprint(
        self, f: Feature, axes: tuple[str, str]
    ) -> tuple[tuple[float, float], float]:
        s = f.sizes
        r = (
            s["diameter"] / 2
        )  # a ball's circle across the face its centre is on; a dome's flat face
        return (r, r), r

    def first(self, f: Feature, part: _Part) -> None:
        s = f.sizes
        origin = np.zeros(3)
        r = s["diameter"] / 2
        part.copies[f.id] = [
            Copy(f.id, 0, None, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), ("x", "y"))
        ]
        part.steps.append(
            Step(f.id, 0, True, Turned((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), _ball(f)))
        )
        if f.choices["portion"] == "upper_half":
            part.flats[(f.id, 0, "-end")] = _Flat((f.id, 0, "-end"), origin.copy(), _v((0, 0, -1)), ("x", "y"),
                                                  "disc", (r, r), r, None, dome=r)  # fmt: skip
        # Its curved surface takes a hole, a boss or a post (item 3b's second step).
        part.balls[(f.id, 0, "surface")] = _Ball((f.id, 0, "surface"), origin.copy(), "+z", r,
                                                 f.choices["portion"] == "upper_half", False)  # fmt: skip
        return

    def rise(self, f: Feature) -> float:
        s = f.sizes
        return s["diameter"] / 2

    def faces_of(self, f: Feature) -> tuple[str, ...]:
        return ("-end",) if f.on is None else ()

    def stand_flat(self, f: Feature, copy_index: int, p: Array, n: Array, e1: Array, e2: Array, face: _Flat,
                   part: _Part, strict: bool, feet: list[_Foot], k: int, beyond: frozenset[tuple[int, float]],
                   flush: frozenset[tuple[int, float]]) -> None:  # fmt: skip
        if (
            strict
            and f.choices["portion"] == "whole"
            and f.sizes["diameter"] / 2 > face.material_under(feet[k]) - GAP
        ):
            raise DoesNotFitError(
                f"{f.id}: its lower half would come out of the far side of {face.key}, here"
            )
        part.steps.append(Step(f.id, copy_index, True, Turned(_t(p), _t(n), _ball(f))))
        up = _named(n)
        if np.array_equal(n, _v(unit_of(up))):  # its curved surface takes things where it stands along an axis
            key = (f.id, copy_index, "surface")
            part.balls[key] = _Ball(key, p.copy(), up, f.sizes["diameter"] / 2, f.choices["portion"] == "upper_half",
                                    True)  # fmt: skip

    def draw_new(
        self, rng: random.Random, face: _Flat, top: float, choices: dict[str, str]
    ) -> dict[str, float]:
        choices["portion"] = rng.choice(["whole", "upper_half"])
        sizes = {"diameter": _q(rng.uniform(3, max(3.1, 2 * top)))}
        return sizes

    def shell_opening(
        self, rng: random.Random, body: Feature
    ) -> tuple[float, tuple[str, ...], float]:
        s = body.sizes
        least = s["diameter"] / 2
        opened = ("-end",) if rng.random() < 0.3 else ()
        across = least
        return least, opened, across

    def may_hollow(self, body: Feature) -> bool:
        return body.choices.get("portion") == "upper_half"

    def floored(self, opened: set[str] | tuple[str, ...]) -> bool:
        return not opened

    def hollow(self, f: Feature, body: Feature, plan: Plan, part: _Part, t: float, floor: float, opened: set[str],
               wall: Callable[[str], float]) -> None:  # fmt: skip
        _hollow_dome(f, body, part, t, floor, bool(opened))
        part.balls.pop((body.id, 0, "surface"), None)  # a hollowed dome's surface takes nothing, for now


ENTRY = Sphere()
