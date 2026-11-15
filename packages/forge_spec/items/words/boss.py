"""How the sentences say a boss: its entry in the ``words`` registry (moved from ``render.py``'s table at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.items.words._common import _count, _Line, _where
from forge_spec.items.words.protocol import WordsKind


class Boss(WordsKind):
    key = "boss"

    def sentence(self, ln: _Line) -> str:
        return f"{_count(ln)}boss {ln.item.id}: Ø{ln.v('diameter')}, {ln.v('height')} tall, {_where(ln)}"


ENTRY = Boss()
