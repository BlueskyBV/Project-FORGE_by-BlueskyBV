"""Where the judge places a cone: its entry in the ``place`` registry (its branches moved from ``place.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

from forge_spec.draft import Item

from forge_checks.items.place.protocol import Edges, PlaceKind
from forge_checks.outlines import Outline
from forge_checks.place import Face, Material, Vec, _Layout, _mm, _rod_body


class Cone(PlaceKind):
    key = "cone"

    axial = True
    joined_by_end = True
    both_ends = True
    rims: ClassVar[Mapping[str, Edges]] = {
        "top": (("+end", "side"),),
        "bottom": (("-end", "side"),),
    }

    def footprint(
        self, item: Item, diameters: Mapping[str, float], axes: tuple[str, str]
    ) -> Outline:
        return Outline.disc(_mm(item, "base_diameter") / 2)

    def body(self, item: Item, layout: _Layout, key: tuple[str, int], host: tuple[str, int, str] | None,
             point: Vec, up: str, axes: tuple[str, str], under: tuple[tuple[Outline, ...], Material] | None,
             faces: dict[str, Face]) -> tuple[Vec, Vec]:  # fmt: skip
        length = _mm(item, "length")
        base, top_r = (
            _mm(item, "base_diameter") / 2,
            _mm(item, "top_diameter", zero=True) / 2,
        )
        inner = 0.0
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
            tapered=True,
        )


ENTRY = Cone()
