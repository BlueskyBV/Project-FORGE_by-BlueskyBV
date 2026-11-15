"""How the confirmation views draw a region: its entry in the ``views`` registry (its branches moved from ``render_views.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Text
from forge_spec.items.views._common import _tag, _value, box_anchor, box_body
from forge_spec.items.views.protocol import ViewKind
from forge_spec.placement import Instance

if TYPE_CHECKING:
    from forge_spec.render_views import _Drawing


class Region(ViewKind):
    key = "region"

    envelope = True

    def body(self, d: _Drawing, first: Instance, up: int | None) -> None:
        item = d.item
        box_body(d, first, "region (designed later, within this envelope)")
        describe = item.get("describe")
        if isinstance(describe, Text):
            d.say(f"for {describe.text!r}{_tag(describe.provenance)}", "describe")
        if item.get("min_wall") is not None:
            d.say(f"no wall under {_value(item.get('min_wall'))}", "min_wall")
        box_anchor(d, first)


ENTRY = Region()
