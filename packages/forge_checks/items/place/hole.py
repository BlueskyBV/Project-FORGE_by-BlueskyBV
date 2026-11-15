"""Where the judge places a hole: its entry in the ``place`` registry (its branches moved from ``place.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from collections.abc import Mapping

from forge_spec.draft import Counterbore, Countersink, Item

from forge_checks.items.place.protocol import PlaceKind
from forge_checks.outlines import Outline
from forge_checks.place import (
    Copy,
    FlatFace,
    Point,
    RoundSide,
    Vec,
    _footprint,
    _hole_diameter,
    _Layout,
    _length,
    _round_hole,
)


class Hole(PlaceKind):
    key = "hole"

    @property
    def goes_round_side(self) -> bool:
        return True

    def read(self, item: Item, layout: _Layout) -> None:
        layout.diameters[item.id] = _hole_diameter(item)

    def footprint(
        self, item: Item, diameters: Mapping[str, float], axes: tuple[str, str]
    ) -> Outline:
        """Its widest circle (its counterbore's or countersink's)."""
        d = diameters[item.id]
        for extra in (item.get("counterbore"), item.get("countersink")):
            if isinstance(extra, (Counterbore, Countersink)):
                d = max(d, _length(extra.diameter))
        return Outline.disc(d / 2)

    def mouth(self, item: Item, layout: _Layout, face: FlatFace, at: Point) -> Outline:
        return Outline.disc(layout.diameters[item.id] / 2, at)

    def round_frame(self, item: Item, direction: Vec, axis: str, layout: _Layout
                    ) -> tuple[str | None, tuple[str, str] | None, float]:  # fmt: skip
        return None, None, _footprint(item, layout.diameters, ("x", "y")).half[0]

    def round_copy(self, item: Item, side: RoundSide, host: tuple[str, int, str], index: int, point: Vec,
                   direction: Vec, up: str | None, axes: tuple[str, str] | None, layout: _Layout) -> Copy:  # fmt: skip
        return _round_hole(item, side, host, index, point, direction, layout)


ENTRY = Hole()
