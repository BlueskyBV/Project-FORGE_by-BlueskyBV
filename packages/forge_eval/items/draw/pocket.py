"""How the generator draws for a pocket: its entry in the ``draw`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
pocket's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

import math
import random

from forge_eval.generator import (
    DoesNotFitError,
    Feature,
    _Flat,
    _moved,
    _q,
    outline_of,
)
from forge_eval.items.draw.protocol import DrawKind
from forge_eval.truth import Outline2


class Pocket(DrawKind):
    key = "pocket"
    turnable = True
    round_rim = True
    flat_weight = 2
    flat_rank = 1
    cut_out = True
    cuts_turned_faces = True
    misfits = True

    def footprint(
        self, f: Feature, axes: tuple[str, str]
    ) -> tuple[tuple[float, float], float]:
        s = f.sizes
        if f.choices.get("shape") == "circle":
            r = s["diameter"] / 2
            return (r, r), r
        if f.choices.get("shape") == "hexagon":  # the box round it: its corners on the first axis
            h = s["across_flats"] / 2
            return (2 * h / math.sqrt(3.0), h), 0.0
        own = self.own_outline(f, axes)
        if own is not None:  # its drawn outline's box (about the box's middle: foot_of)
            (l1, l2), (h1, h2) = own.box()
            return ((h1 - l1) / 2, (h2 - l2) / 2), 0.0
        return (s["length"] / 2, s["width"] / 2), s.get("corner_radius", 0.0)

    def corners(self, f: Feature, axes: tuple[str, str]) -> list[tuple[float, float]] | None:
        if f.choices.get("shape") != "hexagon":
            return None
        h = f.sizes["across_flats"] / 2
        r = 2 * h / math.sqrt(3.0)
        return [(r, 0.0), (r / 2, h), (-r / 2, h), (-r, 0.0), (-r / 2, -h), (r / 2, -h)]

    def own_outline(self, f: Feature, axes: tuple[str, str]) -> Outline2 | None:
        if f.choices.get("shape") == "profile" and f.outline is not None:
            # Drawn about the middle of the box round it, so that what it covers is its footprint about its point,
            # as every other cut's is (generated part 2451; pocket.md lets a profile lie off its point).
            shape = outline_of(f.outline[0], dict(f.outline[1]))
            (l1, l2), (h1, h2) = shape.box()
            return _moved(shape, -(l1 + h1) / 2, -(l2 + h2) / 2)
        return super().own_outline(f, axes)

    def limits(self, f: Feature) -> None:
        s = f.sizes
        if (
            s.get("corner_radius", 0.0)
            > min(s.get("length", math.inf), s.get("width", math.inf)) / 2
        ):
            raise DoesNotFitError(
                f"{f.id}: a pocket's corners are rounded to at most half its length and width"
            )

    def roundable(self, first: bool) -> tuple[str, ...]:
        return () if first else ("top", "bottom")

    def draw_on_flat(self, rng: random.Random, face: _Flat, top: float, sizes: dict[str, float],
                     choices: dict[str, str]) -> tuple[str, float, float] | None:  # fmt: skip
        if rng.random() < 0.3:
            choices["shape"] = "circle"
            sizes["diameter"] = _q(rng.uniform(2, top * 1.5))
        else:
            choices["shape"] = "rectangle"
            sizes["length"], sizes["width"] = (
                _q(rng.uniform(3, top * 2)),
                _q(rng.uniform(3, top * 1.5)),
            )
            roll = rng.random()
            if roll < 0.35:
                sizes["corner_radius"] = _q(
                    rng.uniform(0.3, min(sizes["length"], sizes["width"]) / 2 - 0.2)
                )
            elif roll < 0.5:
                # Its ends rounded all across: a stadium, or a square as round as a disc.
                short = _q(rng.uniform(1.5, top * 0.75))
                sizes["width"] = 2 * short
                sizes["length"] = (
                    2 * short if roll < 0.42 else _q(2 * short + rng.uniform(1, top))
                )
                sizes["corner_radius"] = short
        return None

    def round_mouth(self, target: Feature) -> bool:
        return target.choices.get("shape") == "circle"


ENTRY = Pocket()
