"""A generated part's brief, written a phrase at a time, and the words each value of its draft cites (docs/V2-stage4.md, 12.1).

The generator says each item of a part in one sentence and cites, for every
value its draft gives, the words that say it, as a person's spec writer
would. A citation is made as its words are written (:meth:`Writer.cite`):
a :class:`Mark` stands in the draft for the word numbers until the whole
brief is written and numbered the way the spec checks number it
(:meth:`Writer.finish`), so no word number is ever counted by hand.

Every word of an item's sentence that no value cites is the item's own (what
it is and where it stands), so the brief is accounted for to the last word.

>>> w = Writer()
>>> item = w.start()
>>> w.say("A plate ")
>>> length = w.cite("60 mm long")
>>> w.end()
>>> text, (draft,) = w.finish(({"words": item, "length": {"from": {"words": length}}},))
>>> text, draft
('A plate 60 mm long.', {'words': [0, 1], 'length': {'from': {'words': [2, 3, 4]}}})
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from forge_spec import number_words

__all__ = ["Mark", "Writer", "number"]


class Mark:
    """Where in the brief a citation's words are, until the brief is numbered: one or more runs of its text."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "Mark()"


def number(value: float) -> str:
    """A value as the brief writes it: on its 0.001 grid, no trailing zeros, no "-0".

    >>> [number(v) for v in (12.5, 2.0, -3.25, 0.019, -0.0, 100.0)]
    ['12.5', '2', '-3.25', '0.019', '0', '100']
    """
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


class Writer:
    """A brief being written: its text so far, and the runs of it each mark cites."""

    def __init__(self) -> None:
        self._pieces: list[str] = []
        self._at = 0
        self._runs: dict[Mark, list[tuple[int, int]]] = {}
        self._item: Mark | None = None

    def _add(self, text: str, mark: Mark | None) -> None:
        if mark is not None:
            self._runs.setdefault(mark, []).append((self._at, self._at + len(text)))
        self._pieces.append(text)
        self._at += len(text)

    def start(self) -> Mark:
        """Begin an item's sentence; its words that nothing else cites are the item's (the mark returned)."""
        if self._item is not None:
            raise RuntimeError("a sentence is already begun")
        if self._pieces:
            self._add(" ", None)
        self._item = Mark()
        return self._item

    def say(self, text: str) -> None:
        """Words of the item itself: what it is, what it stands on."""
        self._add(text, self._item)

    def cite(self, text: str, mark: Mark | None = None) -> Mark:
        """Words a value of the item comes from; ``mark`` to add them to an earlier citation's."""
        found = Mark() if mark is None else mark
        self._add(text, found)
        return found

    def end(self) -> None:
        """End the item's sentence."""
        if self._item is None:
            raise RuntimeError("no sentence is begun")
        self._add(".", None)
        self._item = None

    def finish(
        self, drafts: Sequence[dict[str, Any]]
    ) -> tuple[str, tuple[dict[str, Any], ...]]:
        """The brief, and the drafts with every mark in them replaced by its word numbers.

        A mark whose runs hold no whole word is the writer's mistake, and raises
        ``ValueError``.
        """
        if self._item is not None:
            raise RuntimeError("a sentence is still begun")
        text = "".join(self._pieces)
        brief = number_words(text)
        words: dict[Mark, list[int]] = {}
        for mark, runs in self._runs.items():
            found = [
                w.index
                for w in brief.words
                if any(a <= w.start and w.end <= b for a, b in runs)
            ]
            if not found:
                raise ValueError(
                    f"no whole word in {[text[a:b] for a, b in runs]!r}: {text!r}"
                )
            words[mark] = found

        def resolved(x: Any) -> Any:
            if isinstance(x, Mark):
                return list(words[x])
            if isinstance(x, dict):
                return {k: resolved(v) for k, v in x.items()}
            if isinstance(x, list):
                return [resolved(v) for v in x]
            return x

        return text, tuple(resolved(d) for d in drafts)
