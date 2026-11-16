"""What spec grading asks of a kind of item: the ``grade`` role's protocol (V2-stage4b-0b-inventory.md, 2.4).

At stage 4b.0b's step 2 each method is a thin wrapper of
``spec_grade.py``'s function that holds the kind's branch today; step 3
moves each kind's branch into its module, where it overrides the method.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from forge_numeric import scalar as fs
from forge_spec.placement import Instance, mm
from forge_spec.schema import KINDS, Category
from forge_spec.values import Value

if TYPE_CHECKING:
    from forge_spec.draft import Item
    from forge_spec.placement import Layout


class GradeKind:
    """One kind of item, as spec grading reads it from the layout."""

    #: The kind this entry is for.
    key = ""
    #: A freeform region (designed later): what it settles is checked on the built part.
    freeform = False
    #: It hollows another (a shell).
    hollows = False
    #: A turned profile (a revolution), which may leave a bore.
    turned = False
    #: A tube: its bore is a through hole when both its ends are open.
    bored = False
    #: A hole, a pocket or a slot (not letters, whose category is a cut's too).
    cut_out = False

    @property
    def taken(self) -> bool:
        """A cut, by its category (letters too): it may reach a hollow."""
        return KINDS[self.key].category is Category.CUT

    def raised(self, item: Item) -> bool:
        """Raised lettering, which unsettles what the envelope says."""
        return False

    def reach(self, item: Item, layout: Layout) -> float | None:
        """How far a cut reaches from its centre at most, whatever way it turns; None if unknown."""
        size = {
            n: mm(v)
            for n in ("length", "width", "diameter")
            if isinstance(v := item.get(n), Value)
        }
        if "length" in size and "width" in size:
            return fs.hypot(size["length"], size["width"]) / 2
        return None

    def through_diameter(self, item: Item, layout: Layout) -> float | None:
        """The diameter of the through hole it may make (a hole's, a round pocket's); None where it makes none."""
        return None

    def bore_runs(self, item: Item, items: Sequence[Item], copies: Sequence[Instance],
                  runs: dict[tuple[int, float, float], list[tuple[float, float, float]]]) -> str | None:  # fmt: skip
        """Its bore's runs through the part (a tube's), or why it may be closed."""
        return None
