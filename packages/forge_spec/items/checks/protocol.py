"""What the spec checks ask of a kind of item: the ``checks`` role's protocol (V2-stage4b-0b-inventory.md, 2.3).

Each kind's module answers for its own kind (moved from ``checks.py`` at
stage 4b.0b's step 3); what is here is the default the kinds fall to.
"Published" answers are given by the item another acts on: the rounded
body, the threaded rod.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from forge_registry import reserved

from forge_spec.schema import KINDS, Category

if TYPE_CHECKING:
    from forge_spec.draft import Item, PartSpec
    from forge_spec.items.checks._common import Collect
    from forge_spec.placement import Layout
    from forge_spec.words import NumberedBrief


class SpecCheckKind:
    """One kind of item, as the spec checks read it."""

    #: The kind this entry is for.
    key = ""
    #: Whether its outline is turned about an axis, and checked as a revolution's is.
    turned = False
    #: Published: whether a thread may go on it.
    threadable = False

    @property
    def body(self) -> bool:
        """Whether it is a body (the part's first is its name in the brief)."""
        return KINDS[self.key].category is Category.BODY

    def physical(
        self, spec: PartSpec, item: Item, at: str, layout: Layout, c: Collect
    ) -> None:
        """What can't be made of it, or needs a person's decision, whatever the brief says (beyond a length of 0, which every kind's is)."""

    def held_words(self, item: Item, brief: NumberedBrief) -> tuple[int, ...]:
        """The number words in its own words that it holds by what it is, with no value of its own (a whole ball on a
        face is "half sunk" into it): they are used."""
        return ()

    # ------------------------------------------------------------------
    # Published: asked of the item another acts on
    # ------------------------------------------------------------------
    def rounding_limit(self, target: Item, which: str, layout: Layout) -> float | None:
        """The largest rounding that could fit on its edges ``which``, or None if it isn't settled here."""
        return None

    def edges_missing(
        self, target: Item, which: str, layout: Layout
    ) -> tuple[str, str] | None:
        """Why its edge set ``which`` names no edges at all, if it doesn't (docs/definitions/edges.md)."""
        if not self.body:
            return None
        from forge_spec.items.checks._common import base_edges_missing

        return base_edges_missing(target, which, layout)

    # Reserved (V2-stage4b-0b.md, 3 and 4): named and owned now, filled by the step named, never added then.

    @reserved("4b.0c")
    def migrations(self) -> tuple[Any, ...]:
        """Its fields' migrations from each earlier schema version, each proven oracle-equal across the corpus (item 14)."""
        raise NotImplementedError

    @reserved("4b.0d4")
    def classes(self, item: Item) -> dict[str, str]:
        """Its verification class per field and mode (item 18), in place of the kind's one ``verification``."""
        raise NotImplementedError
