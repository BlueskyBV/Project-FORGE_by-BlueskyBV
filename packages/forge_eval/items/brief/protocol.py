"""How the generated brief says a kind of feature: the ``brief`` role's protocol (V2-stage4b-0b-inventory.md, 2.4).

At stage 4b.0b's step 2 each method is a thin wrapper of ``generator.py``'s
function that holds the kind's branch today; step 3 moves each kind's
branch into its module, where it overrides the method.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from forge_eval.brief import Writer
from forge_eval.generator import _EDGE_WORDS, _MEASURES, Feature, _item_said, _mm


class BriefKind:
    """One kind of feature, as the brief says it and its draft writes it."""

    #: The kind this entry is for.
    key = ""
    #: How its sentence starts, before its choices' words and its kind's name.
    article = "is a "
    #: Its sentence names its kind ("a block"); a ball's, a dome's, letters' and an outline's say what they are otherwise.
    names_itself = True
    #: A first body stands upright: its axis along z is said.
    axial = False
    #: The word for each option of the choices said before its kind ("a round pocket").
    option_words: ClassVar[Mapping[str, Mapping[str, str]]] = {}

    #: A hole, a pocket or a slot: a solid taken from the face it is on, to a depth or through (not letters,
    #: whose category is a cut's too).
    cut_out = False

    def draft(self, f: Feature, w: Writer, names: Mapping[str, str]) -> dict[str, Any]:
        """The item as the draft writes it, and its sentence of the brief: every value cites the words that say it, the rest of the sentence is the item's own."""
        found: dict[str, Any] = {"id": f.id, "kind": f.kind, "words": w.start()}
        name = names[f.id]
        w.say(name[0].upper() + name[1:] + " ")
        _item_said(f, w, names, found)
        w.end()
        return found

    def item_said(
        self, f: Feature, w: Any, names: Mapping[str, str], found: dict[str, Any]
    ) -> None:
        """Its words in the brief (``generator._item_said``)."""
        from forge_eval import generator

        generator._item_said(f, w, names, found)

    def rounding_said(self, f: Feature, w: Writer, names: Mapping[str, str], found: dict[str, Any]) -> None:  # fmt: skip
        assert f.of is not None
        which = f.choices["which"]
        meets = f.choices.get("where_meets")
        w.say("bevels ")
        edges: dict[str, Any] = {"of": f.of, "which": which}
        if meets is not None:
            edges["where_meets"] = meets
        edges["words"] = w.cite(
            _EDGE_WORDS[which].format(
                of=names[f.of], meets=names[meets] if meets is not None else ""
            )
        )
        found["edges"] = edges
        ((size, v),) = f.sizes.items()
        w.say(" by ")
        found[size] = _mm(w, v)

    def words_said(self, f: Feature, w: Writer, found: dict[str, Any]) -> None:
        """Its words, where it has any (letters'): quoted, or as drawn with the brief."""

    def sizes_said(self, f: Feature) -> list[tuple[str, float, str, str]]:
        """Its sizes as said: each with what it measures."""
        return [
            (size, v, "", " " + _MEASURES.get(size, "")) for size, v in f.sizes.items()
        ]
