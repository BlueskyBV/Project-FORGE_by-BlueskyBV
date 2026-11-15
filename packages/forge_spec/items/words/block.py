"""How the sentences say a block: its entry in the ``words`` registry (moved from ``render.py``'s table at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.items.words._common import _Line, _where
from forge_spec.items.words.protocol import WordsKind


class Block(WordsKind):
    key = "block"

    def sentence(self, ln: _Line) -> str:
        return (
            f"Block {ln.item.id}: {ln.v('length')} x {ln.v('width')} x {ln.v('height')} "
            f"(length x width x height), {_where(ln)}"
        )


ENTRY = Block()
