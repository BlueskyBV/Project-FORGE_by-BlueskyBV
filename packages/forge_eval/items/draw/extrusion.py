"""How the generator draws for an extrusion: its entry in the ``draw`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
extrusion's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from forge_eval.generator import (
    REACH,
    Array,
    Feature,
    _first_extrusion,
    _Flat,
    _flat_axes,
    _Foot,
    _footprint,
    _moved,
    _named,
    _Part,
    _point,
    _profile_box,
    _standing_profile,
    _t,
    _under,
    _widest,
    outline_of,
)
from forge_eval.items.draw.protocol import DrawKind
from forge_eval.truth import Pushed, Step


class Extrusion(DrawKind):
    key = "extrusion"
    hosts_standing = True

    def footprint(
        self, f: Feature, axes: tuple[str, str]
    ) -> tuple[tuple[float, float], float]:
        (l1, l2), (h1, h2) = _profile_box(
            f
        )  # the box round its outline (about the box's middle: _foot_of)
        return ((h1 - l1) / 2, (h2 - l2) / 2), 0.0

    def extent(
        self, f: Feature, axes: tuple[str, str]
    ) -> tuple[tuple[float, float], tuple[float, float]]:
        (l1, l2), (h1, h2) = _profile_box(f)
        return (l1, h1), (l2, h2)

    def foot_of(self, f: Feature, face: _Flat, at: tuple[float, float]) -> _Foot:
        half, _ = _footprint(f, face.axes)
        # The box round its outline, which runs along the face's axes from its point (extrusion.md).
        (l1, l2), (h1, h2) = _profile_box(f)
        return _Foot((at[0] + (l1 + h1) / 2, at[1] + (l2 + h2) / 2), half, 0.0)

    def first(self, f: Feature, part: _Part) -> None:
        _first_extrusion(f, part)
        return

    def rise(self, f: Feature) -> float:
        s = f.sizes
        return s["length"]

    def standing_profile(
        self,
        f: Feature,
        index: int,
        base: Array,
        n: Array,
        face: _Flat,
        part: _Part,
        under: float,
    ) -> None:
        assert f.outline is not None
        name, values = f.outline[0], dict(f.outline[1])
        shape = outline_of(name, values)
        up = _named(n)
        e1, e2 = face.frame.u, face.frame.v
        length = f.sizes["length"]
        part.steps.append(Step(f.id, index, True, Pushed(_t(base), _t(e1), _t(e2), _t(n), shape, 0.0, length),
                               (REACH, 0.0)))  # fmt: skip
        point = face.frame.plane(base)
        moved = _moved(shape, point[0], point[1])
        (l1, l2), (h1, h2) = moved.box()
        middle = _point(face, ((l1 + h1) / 2, (l2 + h2) / 2)) + length * n
        far = (f.id, index, "+end")
        part.flats[far] = _Flat(far, middle, n.copy(), _flat_axes(up), "profile", ((h1 - l1) / 2, (h2 - l2) / 2),
                                length + under, face.exit, outline=moved, widest=_widest(moved))  # fmt: skip
        return

    def faces_of(self, f: Feature) -> tuple[str, ...]:
        return (
            ("+end", "-end") if f.on is None else ("+end",)
        )  # standing, its -end is joined to its face

    def stand_flat(self, f: Feature, copy_index: int, p: Array, n: Array, e1: Array, e2: Array, face: _Flat,
                   part: _Part, strict: bool, feet: list[_Foot], k: int, beyond: frozenset[tuple[int, float]],
                   flush: frozenset[tuple[int, float]]) -> None:  # fmt: skip
        _standing_profile(f, copy_index, p, n, face, part, _under(face, feet[k]))


ENTRY = Extrusion()
