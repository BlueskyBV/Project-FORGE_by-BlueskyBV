"""How the generator draws for a slot: its entry in the ``draw`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
slot's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

import math
import random

import numpy as np
from forge_numeric import scalar as fs

from forge_eval.generator import (
    GAP,
    REACH,
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
)
from forge_eval.items.draw.protocol import DrawKind
from forge_eval.truth import Copy, Prism, Step


class Slot(DrawKind):
    key = "slot"
    turnable = True
    flat_weight = 1
    flat_rank = 2
    cut_out = True
    cuts_turned_faces = True

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


    def on_round(self, f: Feature, side: _Round, index: int, part: _Part, strict: bool) -> list[Copy]:
        """A keyway round a rod's side (slot.md, "Round a side"): along its axis, square to the plane touching it along
        the line through its point, at an angle round it (a circle of them, blind), along it from its ends; blind, or
        right through (a tube's wall until it is in the bore all across; a solid rod's, across it)."""
        if f.pattern is not None and (f.pattern.kind != "circle" or f.depth is None):
            raise DoesNotFitError(f"{f.id}: round a side, keyways go round it in a circle, blind")
        if side.half is not None or side.leans or f.end is not None or f.choices.get("along") != side.axis:
            raise DoesNotFitError(f"{f.id}: a keyway runs along a rod's whole side, blind or right through")
        if set(f.place) - {side.axis}:
            raise DoesNotFitError(f"{f.id}: round a side, placed along its axis")
        long, wide = f.sizes["length"] / 2, f.sizes["width"] / 2
        w = side.frame.n
        zero, quarter = side.frame.u, side.frame.v
        start = f.angle if f.angle is not None else 0.0
        n = f.pattern.counts["count"] if f.pattern is not None else 1
        angles = [start + k * 360.0 / n for k in range(n)]
        along = _along(f.place.get(side.axis, Position("none")), side, long)
        if f.depth is not None:
            deep: float | None = f.depth
        elif side.bore > 0:
            if wide >= side.bore - GAP:
                raise DoesNotFitError(f"{f.id} is as wide as the bore it goes into")
            deep = side.radius - math.sqrt(side.bore * side.bore - wide * wide)
        else:
            deep = None
        reach = fs.hypot(long, wide)
        if strict:
            if along - long < GAP + side.margin[0] or along + long > side.length - GAP - side.margin[1]:
                raise DoesNotFitError(f"{f.id} runs past the side's end, or onto a rounding of its rim")
            if f.depth is None and side.bore > 0 and (along - long < side.bored[0] + GAP
                                                     or along + long > side.bored[1] - GAP):  # fmt: skip
                raise DoesNotFitError(f"{f.id} would come out onto an end's wall inside")
            if f.depth is not None and (f.depth > 0.8 * side.radius
                                        or (side.bore > 0 and f.depth > side.radius - side.bore - GAP)):  # fmt: skip
                raise DoesNotFitError(f"{f.id} is deeper than the rod or its wall, here")
            if wide > side.radius / 2:
                raise DoesNotFitError(f"{f.id} is too wide for the rod, here")
            mine = [(along, a, reach, deep) for a in angles]
            for k, here in enumerate(mine):
                for other in side.taken + mine[:k]:
                    if not _holes_apart(here, other, side.radius):
                        raise DoesNotFitError(f"{f.id} meets something else round the side")
        corner = wide if f.choices["ends"] == "round" else 0.0
        made = []
        for k, a in enumerate(angles):
            radial = fs.cos(math.radians(a)) * zero + fs.sin(math.radians(a)) * quarter
            p = side.frame_at(radial, along).origin
            copy_index = index + k
            made.append(Copy(f.id, copy_index, side.key, _t(p), _t(radial), None))
            depth = 2 * side.radius if deep is None else deep
            across = np.asarray(np.cross(radial, w), dtype=np.float64)
            part.steps.append(Step(f.id, copy_index, False, Prism(_t(p), _t(w), _t(across), _t(radial), (long, wide),
                                                                corner, -depth, 0.0),
                                   (REACH if f.depth is None else 0.0, REACH)))  # fmt: skip
        side.taken += [(along, a, reach, deep) for a in angles]
        return made


ENTRY = Slot()
