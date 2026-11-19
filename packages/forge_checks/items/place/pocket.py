"""Where the judge places a pocket: its entry in the ``place`` registry (its branches moved from ``place.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

import math
from collections.abc import Mapping

from forge_spec.draft import Item

from forge_checks.items.place.protocol import PlaceKind
from forge_checks.outlines import TOL, Outline, Segment
from forge_checks.place import (
    FlatFace,
    PlaceError,
    Vec,
    _choice,
    _Layout,
    _mm,
    _mm_or,
    _pocket_floor,
)


class Pocket(PlaceKind):
    key = "pocket"

    def turnable(self, item: Item) -> bool:
        return _choice(item, "shape") != "circle"  # a round one turns into itself

    def footprint(
        self, item: Item, diameters: Mapping[str, float], axes: tuple[str, str]
    ) -> Outline:
        if _choice(item, "shape") == "circle":
            return Outline.disc(_mm(item, "diameter") / 2)
        if _choice(item, "shape") == "hexagon":
            # Two corners on the face's first axis, across_flats / sqrt(3) out; anticlockwise (pocket.md).
            h = _mm(item, "across_flats") / 2
            r = 2 * h / math.sqrt(3.0)
            corners = [(r, 0.0), (r / 2, h), (-r / 2, h), (-r, 0.0), (-r / 2, -h), (r / 2, -h)]
            return Outline.profile([Segment(a, b) for a, b in zip(corners, [*corners[1:], corners[0]], strict=True)])
        h1, h2 = _mm(item, "length") / 2, _mm(item, "width") / 2
        r = _mm_or(item, "corner_radius", 0.0) or 0.0
        if r > min(h1, h2) + TOL:
            raise PlaceError(
                item.id,
                f"a {r:g} mm corner radius doesn't fit a {2 * h1:g} x {2 * h2:g} mm pocket",
            )
        return Outline.rect(h1, h2, corners=(r, r, r, r))

    def after_cut(self, item: Item, face: FlatFace, index: int, point: Vec, mouth: Outline, depth: float,
                  layout: _Layout) -> None:  # fmt: skip
        _pocket_floor(item, face, index, point, mouth, depth, layout)


ENTRY = Pocket()
