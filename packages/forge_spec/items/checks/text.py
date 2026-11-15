"""What the spec checks read of a text: its entry in the ``checks`` registry (its branches moved from ``checks.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.draft import Item, PartSpec
from forge_spec.draft import Text as Words
from forge_spec.font import FONT, missing_letters
from forge_spec.items.checks._common import Collect
from forge_spec.items.checks.protocol import SpecCheckKind
from forge_spec.placement import Layout
from forge_spec.problems import pointer


class Text(SpecCheckKind):
    key = "text"

    def physical(
        self, spec: PartSpec, item: Item, at: str, layout: Layout, c: Collect
    ) -> None:
        """Letters are set in the pinned font (docs/definitions/text.md).

        The reader has already turned back an empty text, and one with line
        breaks, tabs or other characters that aren't plain printable text.
        """
        text = item.get("text")
        if not isinstance(text, Words):
            return
        missing = missing_letters(text.text)
        if missing:
            shown = ", ".join(repr(ch) for ch in missing)
            c.add(
                "unable",
                at + pointer("text"),
                f"Forge's font ({FONT}) has no {shown}, for now",
            )


ENTRY = Text()
