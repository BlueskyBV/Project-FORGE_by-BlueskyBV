"""How the sentences say a tab: its entry in the ``words`` registry (moved from ``render.py``'s table at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.items.words._common import _c, _count, _Line, _where
from forge_spec.items.words.protocol import WordsKind


class Tab(WordsKind):
    key = "tab"

    def sentence(self, ln: _Line) -> str:
        return (
            f"{_count(ln)}tab {ln.item.id}: sticking out {ln.v('length')}, {ln.v('width')} wide, "
            f"{ln.v('thickness')} thick along {_c(ln.get('thickness_along'))}, {_c(ln.get('end'))} end, "
            f"{_where(ln)}"
        )


ENTRY = Tab()
