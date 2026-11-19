"""How the sentences say a pocket: its entry in the ``words`` registry (moved from ``render.py``'s table at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.items.words._common import _c, _count, _depth, _generic, _Line, _where
from forge_spec.items.words.protocol import WordsKind


class Pocket(WordsKind):
    key = "pocket"

    def sentence(self, line: _Line) -> str:
        if line.item.get("shape") is not None and _c(line.item.get("shape")).startswith(
            "circle"
        ):
            shape = f"round pocket {line.item.id} ({_c(line.get('shape'))}): Ø{line.v('diameter')}"
        elif line.item.get("shape") is not None and _c(line.item.get("shape")).startswith("profile"):
            shape = (f"pocket {line.item.id} of its own outline ({_c(line.get('shape'))}): "
                     f"{_generic(line.get('profile'))}, about the point where it is placed")  # type: ignore[arg-type]
        elif line.item.get("shape") is not None and _c(line.item.get("shape")).startswith("hexagon"):
            shape = (f"hexagonal pocket {line.item.id} ({_c(line.get('shape'))}): {line.v('across_flats')} across "
                     "its flats, two corners on the face's first axis")  # fmt: skip
        else:
            corners = (
                f", corners R{line.v('corner_radius')}"
                if line.item.get("corner_radius")
                else ""
            )
            shape = (f"rectangular pocket {line.item.id} ({_c(line.get('shape'))}): {line.v('length')} x "
                     f"{line.v('width')}{corners}")  # fmt: skip
        return f"{_count(line)}{shape}, {_depth(line.get('depth'))}, {_where(line, cut=True)}"


ENTRY = Pocket()
