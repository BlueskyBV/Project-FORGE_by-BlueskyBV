"""Where the judge places a post: its entry in the ``place`` registry (its branches moved from ``place.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from collections.abc import Mapping

from forge_spec.draft import Item

from forge_checks.items.place.protocol import Edges, PlaceKind
from forge_checks.outlines import Outline
from forge_checks.place import Face, Material, Vec, _box_body, _box_edges, _Layout, _mm


class Post(PlaceKind):
    key = "post"

    def footprint(
        self, item: Item, diameters: Mapping[str, float], axes: tuple[str, str]
    ) -> Outline:
        return Outline.rect(_mm(item, "length") / 2, _mm(item, "width") / 2)

    def body(self, item: Item, layout: _Layout, key: tuple[str, int], host: tuple[str, int, str] | None,
             point: Vec, up: str, axes: tuple[str, str], under: tuple[tuple[Outline, ...], Material] | None,
             faces: dict[str, Face]) -> tuple[Vec, Vec]:  # fmt: skip
        a1, a2 = axes
        sizes = {a1: _mm(item, "length"), a2: _mm(item, "width")}
        height = _mm(item, "height")
        return _box_body(item, point, up, sizes, height, under, faces)

    def edges(self, which: str, up: str) -> Edges:
        return _box_edges(which, up, False)


ENTRY = Post()
