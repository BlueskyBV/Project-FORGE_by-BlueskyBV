"""How the generator draws for a cone: its entry in the ``draw`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
cone's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

import random
from collections.abc import Callable

import numpy as np

from forge_eval.generator import (
    Array,
    DoesNotFitError,
    Feature,
    Plan,
    _Cone,
    _Flat,
    _Foot,
    _hollow_cone,
    _Part,
    _q,
    _standing_cone,
    _v,
)
from forge_eval.items.draw.protocol import DrawKind
from forge_eval.truth import Copy, Frustum, Step


class Cone(DrawKind):
    key = "cone"
    new_weight = 1
    new_rank = 1
    may_be_zero = frozenset({"top_diameter"})
    openable = ("+end", "-end")
    shelled = 0.5  # a cup, a funnel: half the time
    first_hosts_standing = True

    def first(self, f: Feature, part: _Part) -> None:
        """The first body (cone.md): its -end at the origin, rising along +z; its ends discs (none at a point), the
        material under each its length out to its smaller end's radius, the cone's own falling from there to nothing
        at its larger end's rim, a cut right through one coming out on the other; its side takes things."""
        s = f.sizes
        rb, rt, length = s["base_diameter"] / 2, s["top_diameter"] / 2, s["length"]
        part.copies[f.id] = [Copy(f.id, 0, None, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0), ("x", "y"))]
        part.steps.append(Step(f.id, 0, True, Frustum((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), (rb, rt), length)))
        top, bottom = (f.id, 0, "+end"), (f.id, 0, "-end")
        if rt > 0:
            part.flats[top] = _Flat(top, _v((0, 0, length)), _v((0, 0, 1)), ("x", "y"), "disc", (rt, rt), length,
                                    bottom, flare=(rb, length) if rt > rb else (0.0, 0.0))  # fmt: skip
        part.flats[bottom] = _Flat(bottom, np.zeros(3), _v((0, 0, -1)), ("x", "y"), "disc", (rb, rb), length,
                                   top if rt > 0 else None, flare=(rt, length) if rb > rt else (0.0, 0.0))  # fmt: skip
        part.cones[(f.id, 0, "side")] = _Cone((f.id, 0, "side"), "z", np.zeros(3), length, rb, rt)

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
        top = ("+end",) if f.sizes["top_diameter"] > 0 else ()
        return top if f.on is not None else (*top, "-end", "side")

    def stand_flat(self, f: Feature, copy_index: int, p: Array, n: Array, e1: Array, e2: Array, face: _Flat,
                   part: _Part, strict: bool, feet: list[_Foot], k: int, beyond: frozenset[tuple[int, float]],
                   flush: frozenset[tuple[int, float]]) -> None:  # fmt: skip
        _standing_cone(f, copy_index, p, n, face, part, face.material_under(feet[k]))

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

    def shell_opening(
        self, rng: random.Random, body: Feature
    ) -> tuple[float, tuple[str, ...], float]:
        s = body.sizes
        least = min(s["base_diameter"], s["top_diameter"]) / 2
        opened = rng.choice(((), ("+end",), ("+end",), ("-end",), ("+end", "-end")))
        return least, opened, s["length"]

    def may_hollow(self, body: Feature) -> bool:
        return body.sizes["top_diameter"] > 0  # a cone that comes to a point isn't hollowed yet (shell.md)

    def hollow(self, f: Feature, body: Feature, plan: Plan, part: _Part, t: float, floor: float, opened: set[str],
               wall: Callable[[str], float]) -> None:  # fmt: skip
        _hollow_cone(f, body, part, t, wall, opened)


ENTRY = Cone()
