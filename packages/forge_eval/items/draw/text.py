"""How the generator draws for a text: its entry in the ``draw`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
text's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace

import numpy as np

from forge_eval.generator import (
    GAP,
    REACH,
    Array,
    DoesNotFitError,
    Feature,
    Plan,
    _Flat,
    _Foot,
    _letters,
    _line_length,
    _Part,
    _right,
    _t,
)
from forge_eval.items.draw.protocol import DrawKind
from forge_eval.truth import Letters, Step, ink_box


class Text(DrawKind):
    key = "text"
    turnable = True
    turns_all_round = True

    def footprint(
        self, f: Feature, axes: tuple[str, str]
    ) -> tuple[tuple[float, float], float]:
        s = f.sizes
        # The line's box (text.md): along the face's first axis its length, along the second (up) a capital's height.
        return (_line_length(f) / 2, s["height"] / 2), 0.0

    def foot_of(self, f: Feature, face: _Flat, at: tuple[float, float]) -> _Foot:
        assert f.words is not None
        box = ink_box(f.words, f.sizes["height"])
        if box is None:
            raise DoesNotFitError(f"{f.id}: letters with no ink")
        (x0, y0), (x1, y1) = box
        sign = face.frame.components(_right(face))[0]
        middle = (
            sign * ((x0 + x1) / 2 - _line_length(f) / 2),
            (y0 + y1) / 2 - f.sizes["height"] / 2,
        )
        return _Foot(
            (at[0] + middle[0], at[1] + middle[1]), ((x1 - x0) / 2, (y1 - y0) / 2), 0.0
        )

    def rise(self, f: Feature) -> float:
        s = f.sizes
        return s["depth"]

    def stand_flat(self, f: Feature, copy_index: int, p: Array, n: Array, e1: Array, e2: Array, face: _Flat,
                   part: _Part, strict: bool, feet: list[_Foot], k: int, beyond: frozenset[tuple[int, float]],
                   flush: frozenset[tuple[int, float]]) -> None:  # fmt: skip
        # Engraved, into the face to its depth (its mouth carried on into the air); embossed, out of it
        # (its foot carried on into the face). Up is the face's second axis; they run along up x out.
        engraved, deep = f.choices["mode"] == "engrave", f.sizes["depth"]
        if strict and engraved and deep > face.material_under(feet[k]) - GAP:
            raise DoesNotFitError(
                f"{f.id} is engraved deeper than the material under {face.key}"
            )
        assert f.words is not None
        # Turned in the face's plane, up is its second axis turned (``e2``), and they run along it x out.
        right = _right(face) if f.turn is None else np.asarray(np.cross(e2, n), dtype=np.float64) + 0.0
        letters = Letters(_t(p), _t(right), _t(e2), f.words, f.sizes["height"],
                          -deep if engraved else 0.0, 0.0 if engraved else deep)  # fmt: skip
        part.steps.append(
            Step(
                f.id,
                copy_index,
                not engraved,
                letters,
                (0.0, REACH) if engraved else (REACH, 0.0),
            )
        )

    def stands(self, f: Feature) -> bool:
        return f.choices["mode"] != "engrave"

    def marks(
        self,
        f: Feature,
        face: _Flat,
        at: tuple[float, float],
        half: tuple[float, float],
        corner: float,
        part: _Part,
    ) -> None:
        if f.choices["mode"] == "engrave":
            face.dug.append((face.foot(f, at), f.sizes["depth"]))

    def limits(self, f: Feature) -> None:
        if not f.words or ink_box(f.words, f.sizes["height"]) is None:
            raise DoesNotFitError(f"{f.id}: a line of letters with some ink")

    def own_changes(
        self, f: Feature, plan: Plan
    ) -> Iterator[tuple[str, list[Feature]]]:
        if f.words is None:
            return
        # One letter another: the first, then the last, each the next of the font's letters along.
        letters = _letters()
        swapped = []
        for at in sorted({0, len(f.words) - 1}):
            if f.words[at] in letters:
                other = letters[(letters.index(f.words[at]) + 1) % len(letters)]
                swapped.append(
                    replace(f, words=f.words[:at] + other + f.words[at + 1 :])
                )
        yield "text", swapped


ENTRY = Text()
