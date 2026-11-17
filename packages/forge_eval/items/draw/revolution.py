"""How the generator draws for a revolution: its entry in the ``draw`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
revolution's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from forge_eval.generator import (
    Array,
    Feature,
    _first_revolution,
    _Flat,
    _Foot,
    _Part,
    _profile_box,
    _standing_profile,
)
from forge_eval.items.draw.protocol import DrawKind


class Revolution(DrawKind):
    key = "revolution"
    hosts_standing = True

    def footprint(
        self, f: Feature, axes: tuple[str, str]
    ) -> tuple[tuple[float, float], float]:
        r = _profile_box(f)[1][
            0
        ]  # its widest circle about its axis, the overhang too (place.md: its reach)
        return (r, r), r

    def first(self, f: Feature, part: _Part) -> None:
        _first_revolution(f, part)
        return

    def rise(self, f: Feature) -> float:
        return _profile_box(f)[1][1]

    def faces_of(self, f: Feature) -> tuple[str, ...]:
        return (
            ("+end", "-end") if f.on is None else ("+end",)
        )  # standing, its -end is joined to its face

    def stand_flat(self, f: Feature, copy_index: int, p: Array, n: Array, e1: Array, e2: Array, face: _Flat,
                   part: _Part, strict: bool, feet: list[_Foot], k: int, beyond: frozenset[tuple[int, float]],
                   flush: frozenset[tuple[int, float]]) -> None:  # fmt: skip
        _standing_profile(f, copy_index, p, n, face, part, face.material_under(feet[k]))


ENTRY = Revolution()
