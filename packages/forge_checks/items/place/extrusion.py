"""Where the judge places a extrusion: its entry in the ``place`` registry (its branches moved from ``place.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

from forge_spec.draft import Item

from forge_checks.items.place.protocol import Edges, PlaceKind
from forge_checks.outlines import Outline
from forge_checks.place import (
    FLAT_AXES,
    Face,
    FlatFace,
    Material,
    Solid,
    Vec,
    _add,
    _far,
    _Layout,
    _mm,
    _on_axis,
    _outlined,
    opposite,
    section_of,
    unit,
)


class Extrusion(PlaceKind):
    key = "extrusion"

    axial = True
    joined_by_end = True
    rims: ClassVar[Mapping[str, Edges]] = {
        "top": (("+end", "side"),),
        "bottom": (("-end", "side"),),
        "vertical": (("side", "side"),),
        "all": (("side", "side"), ("+end", "side"), ("-end", "side")),
    }

    def footprint(
        self, item: Item, diameters: Mapping[str, float], axes: tuple[str, str]
    ) -> Outline:
        return section_of(item)

    def body(self, item: Item, layout: _Layout, key: tuple[str, int], host: tuple[str, int, str] | None,
             point: Vec, up: str, axes: tuple[str, str], under: tuple[tuple[Outline, ...], Material] | None,
             faces: dict[str, Face]) -> tuple[Vec, Vec]:  # fmt: skip
        return _outlined(item, layout, key, point, up, axes, under, faces)

    def ends(self, item: Item, layout: _Layout, key: tuple[str, int], point: Vec, up: str, axes: tuple[str, str],
             under: tuple[tuple[Outline, ...], Material] | None, faces: dict[str, Face], section: Outline,
             at: tuple[float, float]) -> tuple[Vec, Vec]:  # fmt: skip
        a1, a2 = axes
        plane = FLAT_AXES[up[1]]
        u = unit(up)
        (c1, c2), (h1, h2) = section.centre, section.half
        length = _mm(item, "length")
        outline = section.moved(*at)
        middle = _on_axis(
            _on_axis(point, a1, at[0] + c1), a2, at[1] + c2
        )  # a face's centre: its box's
        faces["+end"] = FlatFace(
            "+end",
            _add(middle, u, length),
            up,
            plane,
            outline,
            _far(Solid(length), under),
        )
        faces["-end"] = FlatFace("-end", middle, opposite(up), plane, outline, Solid(length))  # fmt: skip
        ends = (_add(_on_axis(_on_axis(point, a1, at[0] + c1 - h1), a2, at[1] + c2 - h2), u, 0.0),
                _add(_on_axis(_on_axis(point, a1, at[0] + c1 + h1), a2, at[1] + c2 + h2), u, length))  # fmt: skip
        return ends


ENTRY = Extrusion()
