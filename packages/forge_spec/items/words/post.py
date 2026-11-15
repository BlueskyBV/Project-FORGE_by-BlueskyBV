"""How the sentences say a post: its entry in the ``words`` registry (moved from ``render.py``'s table at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.items.words._common import _count, _Line, _where
from forge_spec.items.words.protocol import WordsKind


class Post(WordsKind):
    key = "post"

    def sentence(self, ln: _Line) -> str:
        return (
            f"{_count(ln)}post {ln.item.id}: {ln.v('length')} x {ln.v('width')}, {ln.v('height')} tall, "
            f"{_where(ln)}"
        )


ENTRY = Post()
