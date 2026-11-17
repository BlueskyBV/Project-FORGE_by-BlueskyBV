"""Where the judge places a tab: its entry in the ``place`` registry (its branches moved from ``place.py`` at stage 4b.0b's step 3)."""

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
    _round_tab,
    _sized,
)


class Tab(PlaceKind):
    key = "tab"

    def turnable(self, item: Item) -> bool:
        return True

    def footprint(
        self, item: Item, diameters: Mapping[str, float], axes: tuple[str, str]
    ) -> Outline:
        a1, a2 = axes
        thin = _choice(item, "thickness_along")
        if thin not in axes:
            raise PlaceError(
                item.id,
                f"its thickness runs along {thin}, which isn't one of the face's axes {axes}",
            )
        return _sized(
            item,
            axes,
            a2 if thin == a1 else a1,
            _mm(item, "width"),
            _mm(item, "thickness"),
        )

    def body(self, item: Item, layout: _Layout, key: tuple[str, int], host: tuple[str, int, str] | None,
             point: Vec, up: str, axes: tuple[str, str], under: tuple[tuple[Outline, ...], Material] | None,
             faces: dict[str, Face]) -> tuple[Vec, Vec]:  # fmt: skip
        a1, a2 = axes
        thin = _choice(item, "thickness_along")
        if thin not in axes:
            raise PlaceError(
                item.id,
                f"its thickness runs along {thin}, which isn't one of the face's axes {axes}",
            )
        sizes = {
            thin: _mm(item, "thickness"),
            (a2 if thin == a1 else a1): _mm(item, "width"),
        }
        height = _mm(item, "length")
        lo, hi = _box_body(item, point, up, sizes, height, under, faces)
        if _choice(item, "end") == "round":
            _round_tab(item, faces, key, point, up, sizes, height, layout)
        return lo, hi

    def edges(self, which: str, up: str) -> Edges:
        return _box_edges(which, up, False)


ENTRY = Tab()
