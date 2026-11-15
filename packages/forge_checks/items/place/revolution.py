"""Where the judge places a revolution: its entry in the ``place`` registry (its branches moved from ``place.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

from forge_spec.draft import Item

from forge_checks.items.place.protocol import Edges, PlaceKind
from forge_checks.outlines import TOL, Outline
from forge_checks.place import (
    FLAT_AXES,
    Face,
    FlatFace,
    Material,
    PlaceError,
    Turned,
    Vec,
    _add,
    _base,
    _far,
    _Layout,
    _on_axis,
    _outlined,
    _turned_end,
    opposite,
    section_of,
    unit,
)


class Revolution(PlaceKind):
    key = "revolution"

    axial = True
    joined_by_end = True
    rims: ClassVar[Mapping[str, Edges]] = {
        "top": (("+end", "side"),),
        "bottom": (("-end", "side"),),
    }

    def footprint(
        self, item: Item, diameters: Mapping[str, float], axes: tuple[str, str]
    ) -> Outline:
        return _base(item)

    def extent(
        self, item: Item, foot: Outline
    ) -> tuple[tuple[float, float], tuple[float, float]]:
        """Its widest, round its axis."""
        widest = section_of(item)
        r = widest.centre[0] + widest.half[0]
        return (-r, r), (-r, r)

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
        r = c1 + h1
        if section.centre[0] - h1 < -TOL:
            raise PlaceError(
                item.id,
                "a revolution's outline is a half outline: it reaches across its axis",
            )
        for name, top in (("+end", True), ("-end", False)):
            end = _turned_end(section, top)
            if end is None:
                layout.close(key, name, f"its outline doesn't run straight across its axis at its "
                             f"{'greatest' if top else 'least'} height: it has no flat {name}")  # fmt: skip
                continue
            height, inner, outer = end
            centre = _add(point, u, height)
            outline = (
                Outline.ring(outer, inner, at)
                if inner > TOL
                else Outline.disc(outer, at)
            )
            own = Turned(at, section, height, top)
            faces[name] = FlatFace(name, centre, up if top else opposite(up), plane, outline,
                                   _far(own, under) if top else own)  # fmt: skip
        ends = (_add(_on_axis(_on_axis(point, a1, at[0] - r), a2, at[1] - r), u, c2 - h2),
                _add(_on_axis(_on_axis(point, a1, at[0] + r), a2, at[1] + r), u, c2 + h2))  # fmt: skip
        return ends


ENTRY = Revolution()
