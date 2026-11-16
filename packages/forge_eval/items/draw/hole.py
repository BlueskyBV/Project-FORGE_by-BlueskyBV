"""How the generator draws for a hole: its entry in the ``draw`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
hole's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

import math
import random

import numpy as np
from forge_numeric import scalar as fs

from forge_eval.generator import (
    GAP,
    REACH,
    TURN_AXES,
    Array,
    DoesNotFitError,
    Feature,
    Position,
    _along,
    _Flat,
    _holes_apart,
    _Part,
    _q,
    _Round,
    _t,
    _v,
)
from forge_eval.items.draw.protocol import DrawKind
from forge_eval.truth import Copy, Prism, Step, unit_of


class Hole(DrawKind):
    key = "hole"
    round_rim = True
    flat_weight = 4
    flat_rank = 0
    cut_out = True
    misfits = True

    def footprint(
        self, f: Feature, axes: tuple[str, str]
    ) -> tuple[tuple[float, float], float]:
        s = f.sizes
        r = s["diameter"] / 2
        if f.recess is not None:
            r = max(r, f.recess[1] / 2)
        return (r, r), r

    def on_round(
        self, f: Feature, side: _Round, index: int, part: _Part, strict: bool
    ) -> list[Copy]:
        if f.pattern is not None and f.pattern.kind != "circle":
            raise DoesNotFitError(
                f"{f.id}: round a side, copies go round it (a circle)"
            )
        if set(f.place) - {side.axis} or f.recess is not None:
            raise DoesNotFitError(
                f"{f.id}: round a side, a plain hole placed along its axis, here"
            )
        r = f.sizes["diameter"] / 2
        w = _v(unit_of(side.axis))
        zero, quarter = (_v(unit_of(a)) for a in TURN_AXES[side.axis])
        start = f.angle or 0.0
        n = f.pattern.counts["count"] if f.pattern is not None else 1
        angles = [start + k * 360.0 / n for k in range(n)]
        along = _along(f.place.get(side.axis, Position("none")), side, r)
        # Through a tube's wall: until it is in the bore all across its mouth (hole.md); a solid rod's, across it.
        if f.depth is not None:
            deep: float | None = f.depth
        elif side.bore > 0:
            if r >= side.bore:
                raise DoesNotFitError(f"{f.id} is as wide as the bore it goes into")
            deep = side.radius - math.sqrt(side.bore * side.bore - r * r)
        else:
            deep = None
        if strict:
            if (
                along - r < GAP + side.margin[0]
                or along + r > side.length - GAP - side.margin[1]
            ):
                raise DoesNotFitError(
                    f"{f.id} runs past the side's end, or onto a rounding of its rim"
                )
            if (
                f.depth is None
                and side.bore > 0
                and (along - r < side.bored[0] + GAP or along + r > side.bored[1] - GAP)
            ):
                # Through the wall only where the bore is all across its mouth: by a hollowed cylinder's end, it
                # would come out half into the hollow and half into the end's wall (generated part 566).
                raise DoesNotFitError(
                    f"{f.id} would come out onto an end's wall inside"
                )
            if f.depth is not None and f.depth > side.radius:
                raise DoesNotFitError(f"{f.id} is deeper than the rod's radius, here")
            if (
                f.depth is not None
                and side.bore > 0
                and f.depth > side.radius - side.bore - GAP
            ):
                raise DoesNotFitError(f"{f.id} is deeper than the tube's wall")
            if r > side.radius / 2 or (side.bore > 0 and r > side.bore - GAP):
                raise DoesNotFitError(f"{f.id} is too wide for the rod, here")
            mine = [(along, a, r, deep) for a in angles]
            for k, hole in enumerate(mine):
                for other in side.taken + mine[:k]:
                    if not _holes_apart(hole, other, side.radius):
                        raise DoesNotFitError(
                            f"{f.id} meets another hole round the side"
                        )
        made = []
        for k, a in enumerate(angles):
            radial = fs.cos(math.radians(a)) * zero + fs.sin(math.radians(a)) * quarter
            p = side.start + along * w + side.radius * radial
            copy_index = index + k
            made.append(Copy(f.id, copy_index, side.key, _t(p), _t(radial), None))
            depth = 2 * side.radius if deep is None else deep
            e1 = w
            e2 = np.asarray(np.cross(radial, w), dtype=np.float64)
            part.steps.append(Step(f.id, copy_index, False, Prism(_t(p), _t(e1), _t(e2), _t(radial), (r, r), r, -depth, 0.0),
                                   (REACH if f.depth is None else 0.0, REACH)))  # fmt: skip
        side.taken += [(along, a, r, deep) for a in angles]
        return made

    def cut_solid(
        self,
        f: Feature,
        p: Array,
        e1: Array,
        e2: Array,
        n: Array,
        depth: float,
        face: _Flat,
    ) -> tuple[Prism, float]:
        radius = f.sizes["diameter"] / 2
        return Prism(
            _t(p), _t(e1), _t(e2), _t(n), (radius, radius), radius, -depth, 0.0
        ), radius

    def roundable(self, first: bool) -> tuple[str, ...]:
        return () if first else ("top",)

    def turned(self, angle: float) -> list[float]:
        """A hole turned a little round its side."""
        return [angle + d for d in (6.0, -6.0, 12.0, -12.0, 20.0, -20.0)]

    def draw_on_flat(self, rng: random.Random, face: _Flat, top: float, sizes: dict[str, float],
                     choices: dict[str, str]) -> tuple[str, float, float] | None:  # fmt: skip
        recess = None
        sizes["diameter"] = _q(rng.uniform(1.5, top))
        if rng.random() < 0.2:
            recess = (
                "counterbore",
                _q(sizes["diameter"] + rng.uniform(1.5, 5)),
                _q(rng.uniform(0.5, 2.0)),
            )
        elif rng.random() < 0.15:
            recess = ("countersink", _q(sizes["diameter"] + rng.uniform(1.0, 4)), 90.0)
        return recess

    def most_rounding(self, target: Feature, which: str) -> tuple[str, float]:
        s = target.sizes
        most = min(s["diameter"], 4.0)
        return which, most

    def round_mouth(self, target: Feature) -> bool:
        return True


ENTRY = Hole()
