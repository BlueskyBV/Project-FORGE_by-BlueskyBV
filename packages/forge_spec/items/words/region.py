"""How the sentences say a region: its entry in the ``words`` registry (moved from ``render.py``'s table at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.items.words._common import _Line, _text, _where
from forge_spec.items.words.protocol import WordsKind


class Region(WordsKind):
    key = "region"

    def sentence(self, ln: _Line) -> str:
        return (
            f"Freeform region {ln.item.id} within {ln.v('length')} x {ln.v('width')} x {ln.v('height')}"
            + (f", no wall under {ln.v('min_wall')}" if ln.item.get("min_wall") else "")
            + f", for {_text(ln.get('describe'))}, {_where(ln)} (checked by its constraints only)"
        )


ENTRY = Region()
