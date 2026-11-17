"""Where the judge places a rib: its entry in the ``place`` registry (its branches moved from ``place.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from collections.abc import Mapping

from forge_spec.draft import Item

from forge_checks.items.place.protocol import Edges, PlaceKind
from forge_checks.outlines import Outline
from forge_checks.place import (
    Face,
    Material,
    PlaceError,
    Vec,
    _box_body,
    _box_edges,
    _choice,
    _Layout,
    _mm,
    _sized,
)


class Rib(PlaceKind):
    key = "rib"

    def turnable(self, item: Item) -> bool:
        return True

    def footprint(
        self, item: Item, diameters: Mapping[str, float], axes: tuple[str, str]
    ) -> Outline:
        return _sized(
            item,
            axes,
            _choice(item, "along"),
            _mm(item, "length"),
            _mm(item, "thickness"),
        )

    def body(self, item: Item, layout: _Layout, key: tuple[str, int], host: tuple[str, int, str] | None,
             point: Vec, up: str, axes: tuple[str, str], under: tuple[tuple[Outline, ...], Material] | None,
             faces: dict[str, Face]) -> tuple[Vec, Vec]:  # fmt: skip
        a1, a2 = axes
        along = _choice(item, "along")
        if along not in axes:
            raise PlaceError(
                item.id,
                f"it runs along {along}, which isn't one of the face's axes {axes}",
            )
        sizes = {
            along: _mm(item, "length"),
            (a2 if along == a1 else a1): _mm(item, "thickness"),
        }
        height = _mm(item, "height")
        return _box_body(item, point, up, sizes, height, under, faces)

    def edges(self, which: str, up: str) -> Edges:
        return _box_edges(which, up, False)


ENTRY = Rib()
