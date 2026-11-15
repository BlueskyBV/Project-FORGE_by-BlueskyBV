"""How the sentences say a fillet: its entry in the ``words`` registry (moved from ``render.py``'s table at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.items.words._common import _edges, _Line
from forge_spec.items.words.protocol import WordsKind


class Fillet(WordsKind):
    key = "fillet"

    def sentence(self, ln: _Line) -> str:
        return f"Round {_edges(ln.get('edges'))} to R{ln.v('radius')} ({ln.item.id})"


ENTRY = Fillet()
