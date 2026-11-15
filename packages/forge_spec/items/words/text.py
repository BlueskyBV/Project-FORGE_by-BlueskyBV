"""How the sentences say a text: its entry in the ``words`` registry (moved from ``render.py``'s table at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.draft import Choice
from forge_spec.items.words._common import _Line, _tag, _text, _where
from forge_spec.items.words.protocol import WordsKind


def _mode(value: object) -> str:
    if not isinstance(value, Choice):
        return "?"
    word = {"engrave": "engraved", "emboss": "embossed"}.get(value.value, value.value)
    return word + _tag(value.provenance)


class Text(WordsKind):
    key = "text"

    def sentence(self, ln: _Line) -> str:
        return (
            f"Text {ln.item.id}: {_text(ln.get('text'))} {_mode(ln.get('mode'))} {ln.v('depth')}, "
            f"capitals {ln.v('height')} tall, {_where(ln)}"
        )


ENTRY = Text()
