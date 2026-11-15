"""How the confirmation views draw a slot: its entry in the ``views`` registry (its branches moved from ``render_views.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item
from forge_spec.items.views._common import _choice, _length, _through, _value
from forge_spec.items.views.protocol import ViewKind

if TYPE_CHECKING:
    from forge_spec.render_views import _Drawing


class Slot(ViewKind):
    key = "slot"

    window = True

    def corner_radius(self, item: Item) -> float:
        if _choice(item, "ends") == "round" and _length(item, "length") >= _length(
            item, "width"
        ):
            return _length(item, "width") / 2
        return 0.0

    def cut_words(self, d: _Drawing) -> None:
        item = d.item
        depth = item.get("depth")
        d.say(f"slot {_value(item.get('length'))} long, {_value(item.get('width'))} wide, "
              f"{_choice(item, 'ends') or 'square'} ends", "length", "width")  # fmt: skip
        d.say(_through(depth), "depth")


ENTRY = Slot()
