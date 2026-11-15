"""How the sentences say a cone: its entry in the ``words`` registry (moved from ``render.py``'s table at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.items.words._common import _axis_of, _Line, _where
from forge_spec.items.words.protocol import WordsKind


class Cone(WordsKind):
    key = "cone"

    def sentence(self, ln: _Line) -> str:
        return (
            f"Cone {ln.item.id}: Ø{ln.v('base_diameter')} at the base to Ø{ln.v('top_diameter')} "
            f"at the top, {ln.v('length')} long{_axis_of(ln)}, {_where(ln)}"
        )


ENTRY = Cone()
