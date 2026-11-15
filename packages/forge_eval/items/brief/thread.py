"""How the generated brief says for a thread: its entry in the ``brief`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
thread's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from forge_eval.brief import Writer
from forge_eval.generator import Feature, _chosen, _mm, _words_value
from forge_eval.items.brief.protocol import BriefKind


class Thread(BriefKind):
    key = "thread"
    option_words: ClassVar[Mapping[str, Mapping[str, str]]] = {
        "hand": {"right": "right-hand", "left": "left-hand"}
    }

    def draft(self, f: Feature, w: Writer, names: Mapping[str, str]) -> dict[str, Any]:
        found: dict[str, Any] = {"id": f.id, "kind": f.kind, "words": w.start()}
        name = names[f.id]
        w.say(name[0].upper() + name[1:] + " ")
        assert f.of is not None and f.words is not None
        found["of"] = f.of
        w.say("is an ")
        found["designation"] = _words_value(f.words, {"words": w.cite(f.words)})
        w.say(f" thread cut into {names[f.of]}, ")
        hand = f.choices.get("hand", "right")
        found["hand"] = _chosen(w, hand, self.option_words["hand"][hand])
        if "length" in f.sizes:
            w.say(", ")
            found["length"] = _mm(w, f.sizes["length"], after=" long")
        w.end()
        return found


ENTRY = Thread()
