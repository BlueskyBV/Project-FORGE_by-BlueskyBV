"""How the sentences say a thread: its entry in the ``words`` registry (moved from ``render.py``'s table at stage 4b.0b's step 3)."""

from __future__ import annotations

from forge_spec.draft import Text
from forge_spec.items.words._common import _c, _Line, _n, _tag, _text
from forge_spec.items.words.protocol import WordsKind
from forge_spec.tables import TAPPED, metric_size


def _thread(value: object) -> str:
    """A thread with its pitch said outright, so "M8x40" can't pass for an M8 bolt 40 long."""
    if not isinstance(value, Text):
        return "?"
    size = metric_size(value.text)
    coarse = TAPPED.get(size[0], (None, None))[0] if size else None
    if size is None or (size[1] is None and coarse is None):
        return _text(value)
    pitch = size[1] if size[1] is not None else coarse
    series = "coarse" if size[1] is None or pitch == coarse else "fine"
    return (
        f"{value.text!r} ({series}, {_n(pitch or 0)} mm pitch){_tag(value.provenance)}"
    )


class Thread(WordsKind):
    key = "thread"

    def sentence(self, ln: _Line) -> str:
        return (
            f"Thread {ln.item.id}: {_thread(ln.get('designation'))}, {_c(ln.get('hand'))}-handed, "
            f"on {ln.get('of')}"
            + (
                f", {ln.v('length')} from the free end"
                if ln.item.get("length")
                else ", full length"
            )
        )


ENTRY = Thread()
