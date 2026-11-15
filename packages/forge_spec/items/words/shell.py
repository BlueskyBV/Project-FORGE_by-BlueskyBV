"""How the sentences say a shell: its entry in the ``words`` registry (moved from ``render.py``'s table at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.draft import Faces
from forge_spec.items.words._common import _generic, _Line, _tag
from forge_spec.items.words.protocol import WordsKind


class Shell(WordsKind):
    key = "shell"

    def sentence(self, line: _Line) -> str:
        opened = line.get("open")
        faces = _generic(opened) if isinstance(opened, Faces) else "?"
        sealed = isinstance(opened, Faces) and not opened.faces
        several = isinstance(opened, Faces) and len(opened.faces) > 1
        opposite = (
            "the walls opposite the openings"
            if several
            else "the wall opposite the opening"
        )
        floor = f", {opposite} {line.v('floor')}" if line.item.get("floor") else ""
        return (f"Hollow {line.get('of')} ({line.item.id}): walls {line.v('thickness')}{floor}, "
                + (f"sealed all round{_tag(opened.provenance)}" if sealed and isinstance(opened, Faces)
                   else f"open at {faces}"))  # fmt: skip


ENTRY = Shell()
