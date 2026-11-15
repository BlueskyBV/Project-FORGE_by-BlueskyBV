"""How the sentences say a revolution: its entry in the ``words`` registry (moved from ``render.py``'s table at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.items.words._common import _axis_of, _generic, _Line, _where
from forge_spec.items.words.protocol import WordsKind


class Revolution(WordsKind):
    key = "revolution"

    def sentence(self, ln: _Line) -> str:
        return (
            f"Revolution {ln.item.id}: {_generic(ln.get('profile'))}, turned about its axis"  # type: ignore[arg-type]
            f"{_axis_of(ln)}, {_where(ln)}"
        )


ENTRY = Revolution()
