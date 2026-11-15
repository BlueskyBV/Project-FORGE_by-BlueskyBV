"""How the generated brief says for a shell: its entry in the ``brief`` registry.

At stage 4b.0b's step 2 it takes every answer from the protocol, whose
methods call the program's functions as they are; step 3 moves the
shell's branches here (V2-stage4b-0b.md, 7).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from forge_eval.brief import Writer
from forge_eval.generator import Feature, _mm
from forge_eval.items.brief.protocol import BriefKind


class Shell(BriefKind):
    key = "shell"

    def draft(self, f: Feature, w: Writer, names: Mapping[str, str]) -> dict[str, Any]:
        found: dict[str, Any] = {"id": f.id, "kind": f.kind, "words": w.start()}
        name = names[f.id]
        w.say(name[0].upper() + name[1:] + " ")
        assert f.of is not None
        found["of"] = f.of
        w.say(f"hollows {names[f.of]}, ")
        for k, (size, v) in enumerate(f.sizes.items()):
            w.say(", " if k else "")
            wall = "walls" if size == "thickness" else size
            found[size] = _mm(w, v, before=f"its {wall} ", after=" thick")
        faces = list(f.faces or ())
        said = ("open on the " + " and ".join(faces) + (" faces" if len(faces) > 1 else " face")
                if faces else "sealed all round")  # fmt: skip
        w.say(", ")
        found["open"] = {"faces": faces, "from": {"words": w.cite(said)}}
        w.end()
        return found


ENTRY = Shell()
