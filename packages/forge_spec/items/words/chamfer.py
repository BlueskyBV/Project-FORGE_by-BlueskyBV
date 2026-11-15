"""How the sentences say a chamfer: its entry in the ``words`` registry (moved from ``render.py``'s table at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.items.words._common import _edges, _Line
from forge_spec.items.words.protocol import WordsKind


class Chamfer(WordsKind):
    key = "chamfer"

    def sentence(self, ln: _Line) -> str:
        return f"Chamfer {_edges(ln.get('edges'))} by {ln.v('size')} ({ln.item.id})"


ENTRY = Chamfer()
