"""Where the judge places a tube: its entry in the ``place`` registry (its branches moved from ``place.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

from forge_spec.draft import Item

from forge_checks.items.place.protocol import Edges, PlaceKind
from forge_checks.outlines import Outline
from forge_checks.place import Face, Material, PlaceError, Vec, _Layout, _mm, _rod_body


class Tube(PlaceKind):
    key = "tube"

    axial = True
    joined_by_end = True
    both_ends = True
    rims: ClassVar[Mapping[str, Edges]] = {
        "top": (("+end", "side"), ("+end", "bore")),
        "bottom": (("-end", "side"), ("-end", "bore")),
        "outer": (("+end", "side"), ("-end", "side")),
        "bore": (("+end", "bore"), ("-end", "bore")),
    }

    def footprint(
        self, item: Item, diameters: Mapping[str, float], axes: tuple[str, str]
    ) -> Outline:
        return Outline.disc(_mm(item, "outer_diameter") / 2)

    def body(self, item: Item, layout: _Layout, key: tuple[str, int], host: tuple[str, int, str] | None,
             point: Vec, up: str, axes: tuple[str, str], under: tuple[tuple[Outline, ...], Material] | None,
             faces: dict[str, Face]) -> tuple[Vec, Vec]:  # fmt: skip
        length = _mm(item, "length")
        base = _mm(item, "outer_diameter") / 2
        top_r = base
        inner = _mm(item, "inner_diameter") / 2
        if not 0 < inner < base:
            raise PlaceError(item.id, "a tube's bore is narrower than its outside")
        return _rod_body(
            item,
            layout,
            key,
            point,
            up,
            axes,
            under,
            faces,
            length,
            base,
            top_r,
            inner,
            bored=True,
        )


ENTRY = Tube()
