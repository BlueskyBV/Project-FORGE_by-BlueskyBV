"""What the two-draft comparison asks of a kind of item: the ``compare`` role's protocol (V2-stage4b-0b-inventory.md, 2.3).

Each kind's module answers for its own kind (moved from ``compare.py`` at
stage 4b.0b's step 3); what is here is the default the kinds fall to: a
solid's features, copy by copy. "Published" answers are given by the item
another acts on: the rounded item's edges.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from forge_spec.draft import Item
    from forge_spec.items.compare._common import Feature, _Edge
    from forge_spec.placement import Instance, Layout


class CompareKind:
    """One kind of item, as two drafts are compared by what they build."""

    #: The kind this entry is for.
    key = ""
    #: The field that rounds a square-edged cut's corners, where the drafts differ there.
    corner_field = "ends"

    def features(self, n: int, item: Item, layout: Layout) -> list[Feature]:
        """Every shape the item builds: each placed copy's solid."""
        from dataclasses import replace

        from forge_spec.items.compare._common import turned_form

        found: list[Feature] = []
        for copy in layout.instances.get(item.id, ()):
            if copy.lo is not None and copy.hi is not None:
                made = self.solid(n, item, copy)
                # Turned in its face, the box round it, its own way and its own sizes (1b's first move).
                turned = (
                    turned_form(item, layout, copy.face_axes)
                    if copy.face_axes is not None and copy.host is not None
                    else None
                )
                if turned is not None:
                    ways, own = turned
                    made = [replace(f, directions=(*f.directions, *ways), detail=(*f.detail, *own)) for f in made]
                found += made
        return found

    def solid(self, n: int, item: Item, copy: Instance) -> list[Feature]:
        """One copy's solid, as its own shape."""
        from forge_spec.items.compare._common import Feature, _mid, _sub

        assert copy.lo is not None and copy.hi is not None
        lo, hi, kind = copy.lo, copy.hi, item.kind
        sizes, centre = _sub(hi, lo), _mid(lo, hi)
        return [Feature(n, item.id, kind, kind, sizes, centre)]

    def shape_differs(
        self, mine: Feature, other: Feature, here: str
    ) -> tuple[str, str] | None:
        """Where one of its items is built two ways in the two drafts, what to say of it; None: as any item's."""
        return None

    # ------------------------------------------------------------------
    # Published: asked of the item another acts on
    # ------------------------------------------------------------------
    def edges(self, item: Item, copy: Instance, which: str) -> Iterable[_Edge]:
        """A solid's edges ``which``: a box's twelve, by where they lie."""
        from forge_spec.items.compare._common import _box_edges

        return _box_edges(copy, which)

    def cut_outline(
        self, item: Item, copy: Instance, layout: Layout
    ) -> tuple[object, ...]:
        """A cut's outline at its mouth, as its rounded edge is compared: its sizes across the face."""
        from forge_spec.geometry import bbox
        from forge_spec.items.compare._common import _r
        from forge_spec.placement import _outline

        if copy.face_axes is None:
            return ()
        h1, h2 = bbox(_outline(item, layout, copy.face_axes))
        return (_r(2 * h1), _r(2 * h2))

    def cut_edges(
        self, item: Item, copy: Instance, which: str, layout: Layout
    ) -> Iterable[_Edge]:
        """A cut's rounded or chamfered edge: its mouth's outline, or a pocket's floor's."""
        from forge_spec.items.compare._common import cut_rim

        return cut_rim(item, copy, which, self.cut_outline(item, copy, layout))
