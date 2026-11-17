"""Where the judge places a boss: its entry in the ``place`` registry (its branches moved from ``place.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

from forge_spec.draft import Item

from forge_checks.items.place.protocol import Edges, PlaceKind
from forge_checks.outlines import Outline
from forge_checks.place import Face, Material, Vec, _Layout, _mm, _rod_body


class Boss(PlaceKind):
    key = "boss"
    leans = True

    rims: ClassVar[Mapping[str, Edges]] = {"top": (("+end", "side"),)}

    def footprint(
        self, item: Item, diameters: Mapping[str, float], axes: tuple[str, str]
    ) -> Outline:
        return Outline.disc(_mm(item, "diameter") / 2)

    def body(self, item: Item, layout: _Layout, key: tuple[str, int], host: tuple[str, int, str] | None,
             point: Vec, up: str, axes: tuple[str, str], under: tuple[tuple[Outline, ...], Material] | None,
             faces: dict[str, Face]) -> tuple[Vec, Vec]:  # fmt: skip
        length = _mm(item, "height")
        base = _mm(item, "diameter") / 2
        top_r = base
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
            foot_face=False,
        )

    def far(self, up: str) -> str:
        return "+end"


ENTRY = Boss()
