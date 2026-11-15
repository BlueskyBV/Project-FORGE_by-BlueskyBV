"""How the sentences say a rib: its entry in the ``words`` registry (moved from ``render.py``'s table at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.items.words._common import _c, _count, _Line, _where
from forge_spec.items.words.protocol import WordsKind


class Rib(WordsKind):
    key = "rib"

    def sentence(self, ln: _Line) -> str:
        return (
            f"{_count(ln)}rib {ln.item.id}: {ln.v('length')} long along {_c(ln.get('along'))}, "
            f"{ln.v('thickness')} thick, {ln.v('height')} tall, {_where(ln)}"
        )


ENTRY = Rib()
