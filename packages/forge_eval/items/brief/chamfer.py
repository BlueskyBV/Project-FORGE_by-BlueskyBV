"""How the generated brief says for a chamfer: its entry in the ``brief`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
chamfer's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from forge_eval.brief import Writer
from forge_eval.generator import Feature, _rounding_said
from forge_eval.items.brief.protocol import BriefKind


class Chamfer(BriefKind):
    key = "chamfer"

    def draft(self, f: Feature, w: Writer, names: Mapping[str, str]) -> dict[str, Any]:
        found: dict[str, Any] = {"id": f.id, "kind": f.kind, "words": w.start()}
        name = names[f.id]
        w.say(name[0].upper() + name[1:] + " ")
        _rounding_said(f, w, names, found)
        w.end()
        return found


ENTRY = Chamfer()
