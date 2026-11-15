"""How the confirmation views draw a hole: its entry in the ``views`` registry (its branches moved from ``render_views.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Counterbore, Countersink, Fit, Item
from forge_spec.geometry import Part, disc
from forge_spec.items.views._common import _fit, _through, _value
from forge_spec.items.views.protocol import ViewKind
from forge_spec.placement import Layout

if TYPE_CHECKING:
    from forge_spec.render_views import _Drawing


class Hole(ViewKind):
    key = "hole"

    window = True

    def cut_round(self, item: Item) -> bool:
        return True

    def cut_radius(self, item: Item, layout: Layout) -> float:
        return layout.diameters.get(item.id, 0.0) / 2

    def cut_mouth(
        self, item: Item, layout: Layout, axes: tuple[str, str]
    ) -> tuple[Part, ...]:
        # A hole's bore is what goes through; a counterbore stops short.
        return (disc(layout.diameters.get(item.id, 0.0) / 2),)

    def cut_words(self, d: _Drawing) -> None:
        item = d.item
        depth = item.get("depth")
        diameter = item.get("diameter")
        if isinstance(diameter, Fit):
            d.say(
                "hole " + _fit(diameter, d.layout.diameters.get(item.id)),
                "diameter",
            )
        else:
            d.say(f"hole Ø{_value(diameter)}", "diameter")
        d.say(_through(depth), "depth")
        bore, sink = item.get("counterbore"), item.get("countersink")
        if isinstance(bore, Counterbore):
            d.say(
                f"counterbored Ø{_value(bore.diameter)}, {_value(bore.depth)} deep",
                "counterbore",
            )
        if isinstance(sink, Countersink):
            d.say(
                f"countersunk Ø{_value(sink.diameter)} at {_value(sink.angle)}",
                "countersink",
            )


ENTRY = Hole()
