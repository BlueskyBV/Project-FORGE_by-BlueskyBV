"""How the generated brief says for a text: its entry in the ``brief`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
text's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from forge_eval.brief import Writer
from forge_eval.generator import _DRAWN, Feature, _quotable, _words_value
from forge_eval.items.brief.protocol import BriefKind


class Text(BriefKind):
    key = "text"
    article = "is "
    names_itself = False
    option_words: ClassVar[Mapping[str, Mapping[str, str]]] = {
        "mode": {"engrave": "engraved", "emboss": "raised"}
    }

    def words_said(self, f: Feature, w: Writer, found: dict[str, Any]) -> None:
        assert f.words is not None
        if _quotable(f.words):
            w.say("lettering reading \u201c")
            found["text"] = _words_value(f.words, {"words": w.cite(f.words)})
            w.say("\u201d, ")
        else:
            w.say("lettering as drawn with this brief, ")
            found["text"] = _words_value(f.words, _DRAWN)

    def sizes_said(self, f: Feature) -> list[tuple[str, float, str, str]]:
        s = f.sizes
        rise = " deep" if f.choices["mode"] == "engrave" else " high"
        return [
            (size, v, "", " tall" if size == "height" else rise)
            for size, v in s.items()
        ]


ENTRY = Text()
