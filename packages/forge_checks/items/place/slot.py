"""Where the judge places a slot: its entry in the ``place`` registry (its branches moved from ``place.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from collections.abc import Mapping

from forge_spec.draft import Item

from forge_checks.items.place.protocol import PlaceKind
from forge_checks.outlines import Outline
from forge_checks.place import PlaceError, _choice, _mm, _sized


class Slot(PlaceKind):
    key = "slot"

    def turnable(self, item: Item) -> bool:
        return True

    def footprint(
        self, item: Item, diameters: Mapping[str, float], axes: tuple[str, str]
    ) -> Outline:
        a1, _ = axes
        along = _choice(item, "along")
        length, width = _mm(item, "length"), _mm(item, "width")
        if along not in axes:
            raise PlaceError(
                item.id,
                f"it runs along {along}, which isn't one of the face's axes {axes}",
            )
        if _choice(item, "ends") == "round":
            return Outline.stadium(length, width, along_first=along == a1)
        return _sized(item, axes, along, length, width)


ENTRY = Slot()
