"""Where the judge places a slot: its entry in the ``place`` registry (its branches moved from ``place.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from collections.abc import Mapping

from forge_spec.draft import Item

from forge_checks.items.place.protocol import PlaceKind
from forge_checks.outlines import Outline
from forge_checks.place import (
    Copy,
    PlaceError,
    RoundSide,
    Vec,
    _choice,
    _Layout,
    _mm,
    _round_slot,
    _sized,
    in_axes,
)


class Slot(PlaceKind):
    key = "slot"

    def turnable(self, item: Item) -> bool:
        return True

    @property
    def goes_round_side(self) -> bool:
        """A keyway (slot.md, "Round a side")."""
        return True

    def round_frame(self, item: Item, direction: Vec, axis: str, layout: _Layout
                    ) -> tuple[str | None, tuple[str, str] | None, float]:  # fmt: skip
        along = _choice(item, "along")
        if along != axis:
            raise PlaceError(item.id, f"round a side, a slot runs along the side's axis {axis}, for now, not {along}")
        return None, None, _mm(item, "length") / 2

    def round_copy(self, item: Item, side: RoundSide, host: tuple[str, int, str], index: int, point: Vec,
                   direction: Vec, up: str | None, axes: tuple[str, str] | None, layout: _Layout) -> Copy:  # fmt: skip
        return _round_slot(item, side, host, index, point, direction)

    def footprint(
        self, item: Item, diameters: Mapping[str, float], axes: tuple[str, str]
    ) -> Outline:
        a1, _ = axes
        along = _choice(item, "along")
        along = None if along is None else in_axes(along, axes)
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
