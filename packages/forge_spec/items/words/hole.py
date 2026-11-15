"""How the sentences say a hole: its entry in the ``words`` registry (moved from ``render.py``'s table at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.draft import Counterbore, Countersink, Fit
from forge_spec.items.words._common import _count, _depth, _Line, _n, _tag, _v, _where
from forge_spec.items.words.protocol import WordsKind
from forge_spec.tables import lookup_fit


def _diameter(value: object) -> str:
    if isinstance(value, Fit):
        entry = lookup_fit(value.fit, value.for_, value.grade or "normal")
        size = (
            f"{_n(entry.size_mm)} mm ({entry.source})"
            if entry
            else f"? ({value.fit} for {value.for_})"
        )
        return f"Ø{size}" + _tag(value.provenance)
    return f"Ø{_v(value)}"


class Hole(WordsKind):
    key = "hole"

    def sentence(self, line: _Line) -> str:
        extras = []
        bore, sink = line.get("counterbore"), line.get("countersink")
        if isinstance(bore, Counterbore):
            extras.append(f"counterbored Ø{_v(bore.diameter)}, {_v(bore.depth)} deep")
        if isinstance(sink, Countersink):
            extras.append(f"countersunk to Ø{_v(sink.diameter)} at {_v(sink.angle)}")
        extra = "".join(f", {e}" for e in extras)
        return (f"{_count(line)}hole {line.item.id}: {_diameter(line.get('diameter'))}{extra}, "
                f"{_depth(line.get('depth'))}, {_where(line, cut=True)}")  # fmt: skip


ENTRY = Hole()
