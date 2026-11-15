"""How the sentences say a tube: its entry in the ``words`` registry (moved from ``render.py``'s table at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.items.words._common import _axis_of, _Line, _where
from forge_spec.items.words.protocol import WordsKind


class Tube(WordsKind):
    key = "tube"

    def sentence(self, ln: _Line) -> str:
        return (
            f"Tube {ln.item.id}: Ø{ln.v('outer_diameter')} outside, Ø{ln.v('inner_diameter')} "
            f"bore right through, {ln.v('length')} long{_axis_of(ln)}, {_where(ln)}"
        )


ENTRY = Tube()
