"""How the generated brief says for a fillet: its entry in the ``brief`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
fillet's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from forge_eval.brief import Writer
from forge_eval.generator import _EDGE_WORDS, Feature, _mm, _rounding_said
from forge_eval.items.brief.protocol import BriefKind


class Fillet(BriefKind):
    key = "fillet"

    def draft(self, f: Feature, w: Writer, names: Mapping[str, str]) -> dict[str, Any]:
        found: dict[str, Any] = {"id": f.id, "kind": f.kind, "words": w.start()}
        name = names[f.id]
        w.say(name[0].upper() + name[1:] + " ")
        _rounding_said(f, w, names, found)
        w.end()
        return found

    def rounding_said(self, f: Feature, w: Writer, names: Mapping[str, str], found: dict[str, Any]) -> None:  # fmt: skip
        assert f.of is not None
        which = f.choices["which"]
        meets = f.choices.get("where_meets")
        w.say("rounds ")
        edges: dict[str, Any] = {"of": f.of, "which": which}
        if meets is not None:
            edges["where_meets"] = meets
        edges["words"] = w.cite(
            _EDGE_WORDS[which].format(
                of=names[f.of], meets=names[meets] if meets is not None else ""
            )
        )
        found["edges"] = edges
        ((size, v),) = f.sizes.items()
        w.say(" to a ")
        found[size] = _mm(w, v, after=" radius")


ENTRY = Fillet()
