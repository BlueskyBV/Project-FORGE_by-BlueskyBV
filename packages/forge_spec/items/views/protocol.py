"""What the confirmation views ask of a kind of item: the ``views`` role's protocol (V2-stage4b-0b-inventory.md, 2.3).

Each kind's module answers for its own kind (moved from ``render_views.py``
at stage 4b.0b's step 3), given the drawing (``d``, a ``render_views._Drawing``:
its item, copies, layout and views, and how it says and dimensions what it
shows) where it draws; what is here is the default the kinds fall to.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_registry import reserved

from forge_spec.schema import KINDS, Category

if TYPE_CHECKING:
    from forge_spec.draft import Item
    from forge_spec.geometry import Part, Vec
    from forge_spec.placement import Instance, Layout
    from forge_spec.render_views import _Canvas, _Drawing


class ViewKind:
    """One kind of item, as the confirmation views draw it."""

    #: The kind this entry is for.
    key = ""
    #: Drawn as the envelope it is designed within (a region).
    envelope = False
    #: A cut that can be seen through where it goes right through (letters can't).
    window = False
    #: Letters: written where they are seen, and never coming out the far side.
    lettered = False

    @property
    def drawable(self) -> bool:
        """Whether it is drawn on its own: a modifier is in words, with what it modifies."""
        return KINDS[self.key].category is not Category.MODIFY

    @property
    def cut(self) -> bool:
        """Whether it is drawn as a cut into the material."""
        return KINDS[self.key].category is Category.CUT

    @property
    def hides(self) -> bool:
        """Whether its material hides what is behind it: a body's, a standing item's."""
        return KINDS[self.key].category in (Category.BODY, Category.ADD)

    # ------------------------------------------------------------------
    # A body or a standing item
    # ------------------------------------------------------------------
    def homed_down_axis(self, item: Item) -> bool:
        """Whether its home view looks down its axis (a round thing's), where it doesn't stand on a flat face."""
        return False

    def body(self, d: _Drawing, first: Instance, up: int | None) -> None:
        """Its note and dimensions, its outlines drawn and its home view chosen."""
        raise NotImplementedError(f"a {self.key} isn't drawn as a body")

    def box_fields(self, item: Item, a1: str, a2: str, up: int) -> dict[int, str]:
        """Which field each frame axis of a box-like item's bounds comes from, as the solver builds it."""
        i = "xyz".index
        return {i(a1): "length", i(a2): "width", up: "height"}

    def outline(
        self, d: _Drawing, canvas: _Canvas, copy: Instance, style: str, up: int | None
    ) -> None:
        """One copy's outline on one view, in ``style``: its bounds."""
        lo, hi = copy.lo, copy.hi
        assert lo is not None and hi is not None
        canvas.rect(canvas.at(lo), canvas.at(hi), style)

    def cavity(self, d: _Drawing, canvas: _Canvas, copy: Instance, cavity: tuple[Vec, Vec], style: str,
               open_faces: set[str], up: int | None) -> None:  # fmt: skip
        """The hollow a shell leaves in it: hidden behind a wall."""
        lo, hi = cavity
        canvas.rect(canvas.at(lo), canvas.at(hi), "hidden")

    def inside(
        self, item: Item, copy: Instance, layout: Layout, up: int
    ) -> list[tuple[Vec, Vec]]:
        """Boxes wholly inside one copy's material: what can hide something behind it (a round thing's square in its circle)."""
        from forge_spec.items.views._common import round_inside

        assert copy.lo is not None and copy.hi is not None
        if (
            layout.cavities.get((item.id, copy.index)) is not None
            or item.id in layout.shells
        ):
            return []
        lo, hi = copy.lo, copy.hi
        return round_inside(copy, up, (hi[(up + 1) % 3] - lo[(up + 1) % 3]) / 2)

    # ------------------------------------------------------------------
    # A cut
    # ------------------------------------------------------------------
    def cut_round(self, item: Item) -> bool:
        """Whether it is a round cut (a hole's, a round pocket's), drawn by its radius."""
        return False

    def cut_radius(self, item: Item, layout: Layout) -> float:
        """A round cut's radius: half its diameter."""
        from forge_spec.items.views._common import _length

        return _length(item, "diameter") / 2

    def cut_mouth(
        self, item: Item, layout: Layout, axes: tuple[str, str]
    ) -> tuple[Part, ...]:
        """What goes through, across the face it is cut into: its outline."""
        from forge_spec.placement import _outline

        return _outline(item, layout, axes)

    def embossed(self, item: Item) -> bool:
        """Whether it stands out of the face, not into it (raised letters)."""
        return False

    def corner_radius(self, item: Item) -> float:
        """How a square-edged cut's corners are rounded, as drawn."""
        return 0.0

    def cut_words(self, d: _Drawing) -> None:
        """A cut's note: what it is, and how deep."""
        raise NotImplementedError(f"a {self.key} isn't drawn as a cut")

    # Reserved (V2-stage4b-0b.md, 3 and 4): named and owned now, filled by the step named, never added then.

    @reserved("stage 6")
    def drawing(self, d: _Drawing) -> None:
        """Its drawing view: section 4's slot (the confirmation views are this role's), judged by stage 6's drawing re-measured by ``forge_checks``."""
        raise NotImplementedError
