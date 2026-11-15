"""How the sentences say a slot: its entry in the ``words`` registry (moved from ``render.py``'s table at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.items.words._common import _c, _count, _depth, _Line, _where
from forge_spec.items.words.protocol import WordsKind


class Slot(WordsKind):
    key = "slot"

    def sentence(self, ln: _Line) -> str:
        return (
            f"{_count(ln)}slot {ln.item.id}: {ln.v('width')} wide, {ln.v('length')} long end to end, "
            f"along {_c(ln.get('along'))}, {_c(ln.get('ends'))} ends, {_depth(ln.get('depth'))}, "
            f"{_where(ln, cut=True)}"
        )


ENTRY = Slot()
