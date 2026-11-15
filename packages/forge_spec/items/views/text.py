"""How the confirmation views draw a text: its entry in the ``views`` registry (its branches moved from ``render_views.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item
from forge_spec.draft import Text as Words
from forge_spec.items.views._common import _choice, _tag, _value
from forge_spec.items.views.protocol import ViewKind

if TYPE_CHECKING:
    from forge_spec.render_views import _Drawing


class Text(ViewKind):
    key = "text"

    lettered = True

    def embossed(self, item: Item) -> bool:
        return _choice(item, "mode") == "emboss"

    def cut_words(self, d: _Drawing) -> None:
        item = d.item
        depth = item.get("depth")
        text = item.get("text")
        shown = (
            f"{text.text!r}{_tag(text.provenance)}" if isinstance(text, Words) else "?"
        )
        d.say(
            f"text {shown}, capitals {_value(item.get('height'))} tall",
            "text",
            "height",
        )
        if _choice(item, "mode") == "emboss":
            d.say(f"embossed {_value(depth)} high", "depth")
        else:
            d.say(f"engraved {_value(depth)} deep", "depth")


ENTRY = Text()
