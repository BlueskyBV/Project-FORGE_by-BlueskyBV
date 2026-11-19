"""How the confirmation views draw a pocket: its entry in the ``views`` registry (its branches moved from ``render_views.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item
from forge_spec.items.views._common import _choice, _length, _through, _value
from forge_spec.items.views.protocol import ViewKind

if TYPE_CHECKING:
    from forge_spec.render_views import _Drawing


class Pocket(ViewKind):
    key = "pocket"

    window = True

    def cut_round(self, item: Item) -> bool:
        return _choice(item, "shape") == "circle"

    def corner_radius(self, item: Item) -> float:
        return min(
            _length(item, "corner_radius"),
            _length(item, "length") / 2,
            _length(item, "width") / 2,
        )

    def cut_words(self, d: _Drawing) -> None:
        item = d.item
        depth = item.get("depth")
        if _choice(item, "shape") == "circle":
            d.say(f"round pocket Ø{_value(item.get('diameter'))}", "diameter")
        elif _choice(item, "shape") == "profile":
            d.say("pocket of its outline", "profile")
        elif _choice(item, "shape") == "hexagon":
            d.say(f"hex pocket {_value(item.get('across_flats'))} across flats", "across_flats")
        else:
            d.say(
                f"pocket {_value(item.get('length'))} x {_value(item.get('width'))}",
                "length",
                "width",
            )
            if item.get("corner_radius") is not None:
                d.say(f"corners R{_value(item.get('corner_radius'))}", "corner_radius")
        d.say(_through(depth), "depth")


ENTRY = Pocket()
