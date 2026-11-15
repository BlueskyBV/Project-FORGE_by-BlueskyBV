"""How the sentences say a cylinder: its entry in the ``words`` registry (moved from ``render.py``'s table at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.items.words._common import _axis_of, _Line, _where
from forge_spec.items.words.protocol import WordsKind


class Cylinder(WordsKind):
    key = "cylinder"

    def sentence(self, ln: _Line) -> str:
        return (
            f"Cylinder {ln.item.id}: Ø{ln.v('diameter')}, {ln.v('length')} long"
            f"{_axis_of(ln)}, {_where(ln)}"
        )


ENTRY = Cylinder()
