"""What the oracle asks of a kind of item: the ``oracle`` role's protocol (V2-stage4b-0b-inventory.md, 2.2).

Each kind's module overrides what its kind does its own way; the methods
here are what every other kind does. "Published" methods are answered by
the item another acts on (the hollowed, rounded or threaded item). The
oracle's context, ``making``, is what is made so far and the oracle's own
ways of making a hollow, a rounding and a thread.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from forge_registry import reserved
from forge_spec.schema import KINDS, Category

from forge_checks.items.oracle._shapes import OracleError, box_footprint

if TYPE_CHECKING:
    from forge_spec.draft import Item

    from forge_checks import rounds
    from forge_checks.csg import Node
    from forge_checks.oracle import Step, _Making
    from forge_checks.place import Copy, Face, Hollow, Placed
    from forge_checks.place import Step as Planned
    from forge_checks.shapes import Shape2D


class OracleKind:
    """One kind of item, as the oracle makes its shape."""

    #: The kind this entry is for.
    key = ""
    #: It hollows another (a shell).
    hollows = False
    #: Published: a thread may go on it, ``rod_length`` the field its length is in.
    threadable = False
    rod_length = "length"
    #: Published: the edges a rounding names on it are its outline's, along it or round its ends (an extrusion's).
    outline_rounded = False

    @property
    def taken(self) -> bool:
        """Its copies are taken from the part, not added to it (a cut's)."""
        return KINDS[self.key].category is Category.CUT

    # ------------------------------------------------------------------
    # Its own
    # ------------------------------------------------------------------
    def steps(self, item: Item, planned: Planned, making: _Making) -> list[Step]:
        """Its steps, in the order the placement makes it: a step for each copy (:meth:`copy_steps`)."""
        found: list[Step] = []
        for copy in making.placed.copies[item.id]:
            face = making.placed.face(copy.host) if copy.host is not None else None
            if copy.frame is not None and copy.local is not None:
                # On a turned item's face: made upright, as on that face with its item upright, then moved
                # (place.md, "A turned item's faces").
                from dataclasses import replace

                from forge_checks.moved import moved_node
                from forge_checks.place import FlatFace

                upright = replace(face, local=None) if isinstance(face, FlatFace) else face
                found += [replace(s, node=moved_node(s.node, copy.frame))
                          for s in self.copy_steps(item, copy.local, upright, making)]  # fmt: skip
                key = (item.id, copy.index)
                if key in making.made:
                    making.made[key] = moved_node(making.made[key], copy.frame)
                continue
            found += self.copy_steps(item, copy, face, making)
        return found

    def copy_steps(
        self,
        item: Item,
        copy: Copy,
        face: Face | None,
        making: _Making,
    ) -> list[Step]:
        """One copy's step: its solid taken from the part (a cut's), or added to it and kept as the copy's own."""
        if self.taken:
            assert face is not None
            return [
                making.step(
                    item, copy, False, self.node(item, copy, face, making.placed)
                )
            ]
        node = self.node(item, copy, face, making.placed)
        making.made[(item.id, copy.index)] = node
        return [making.step(item, copy, True, node)]

    def left_unchecked(self, item: Item) -> str | None:
        """Why the oracle leaves the item's shape unchecked, where it does."""
        return None

    def node(
        self, item: Item, copy: Copy, face: Face | None, placed: Placed
    ) -> Node:
        """One copy's solid: what a body or a standing feature adds, or a cut takes away."""
        raise OracleError(f"{item.id}: a {item.kind} is not made by the oracle yet")

    def outline(self, item: Item, axes: tuple[str, str]) -> Shape2D:
        """A flat cut's outline in a face's axes (a slot's, a pocket's)."""
        raise OracleError(f"{item.id}: a {item.kind} has no outline")

    # ------------------------------------------------------------------
    # Published: asked of the item another acts on
    # ------------------------------------------------------------------
    def hollow(self, item: Item, copy: Copy, placed: Placed) -> Node:
        """The hollow a shell makes in one copy of the body (shell.md)."""
        raise OracleError(f"{item.id}: a {item.kind} isn't hollowed by the oracle")

    def wall_bands(self, body: Item, copy: Copy, placed: Placed) -> dict[str, Node]:
        """Each closed face's band: every point its wall's thickness in from it or nearer (or outside the body), by face."""
        raise OracleError(f"{body.id}: a {body.kind} isn't hollowed by the oracle")

    def rim_chains(
        self,
        target: Item,
        copy: Copy,
        which: str,
        pairs: tuple[tuple[str, str], ...],
        making: _Making,
        whole: Node,
        hollow: Hollow | None,
    ) -> tuple[list[rounds.Chain], list[tuple[rounds.Chain, frozenset[str]]]]:
        """The edges ``pairs`` a rounding names on one copy of the item, as chains; and a box-like body's single edges, each with its two faces."""
        raise OracleError(
            f"{target.id}: a {target.kind}'s edges aren't made by the oracle"
        )

    def cut_chains(
        self, item: Item, copy: Copy, which: str, placed: Placed, size: float
    ) -> tuple[list[rounds.Chain], bool, list[Node], Node | None]:
        """A cut's rim (its mouth's edge, taking material away) or a pocket's floor's edge (filling the corner)."""
        raise OracleError(f"{item.id}: a {item.kind}'s edges aren't made by the oracle")

    def footprint_chain(
        self,
        item: Item,
        copy: Copy,
        corners: Mapping[frozenset[str], tuple[str, float]],
    ) -> rounds.Chain:
        """The corner round a standing item's foot, in the air above the face and outside the item: a box-like one's, round its foot's face."""
        return box_footprint(copy, corners)

    # Reserved (V2-stage4b-0b.md, 3 and 4): named and owned now, filled by the step named, never added then.

    @reserved("4b.0d2")
    def acts_on(self, item: Item) -> tuple[str, ...]:
        """The items it acts on, by id (item 11): the order's graph, as the judge evaluates it on its own."""
        raise NotImplementedError

    @reserved("4b.0d2")
    def order_rank(self) -> int:
        """Its rank in the canonical order (item 11), the default inferred and shown at confirmation."""
        raise NotImplementedError

    @reserved("4b.0d2")
    def as_of(self, item: Item) -> str | None:
        """The item after which stood the shape it acts on, where it says (item 11's ``as_of``)."""
        raise NotImplementedError

    @reserved("4b.0d2")
    def face_roles(self, item: Item) -> tuple[str, ...]:
        """Its faces' roles (item 12): how they split under cuts and merge across tangent joins, a copy's by its pattern coordinates."""
        raise NotImplementedError

    @reserved("4b.0d2")
    def edge_roles(self, item: Item) -> tuple[tuple[str, str], ...]:
        """Its edges' roles, each the two face roles that meet there (item 12)."""
        raise NotImplementedError

    @reserved("4b.0d2")
    def select(self, item: Item, rule: Any) -> Any:
        """A selection rule's faces or edges of it (item 12), evaluated on the oracle's own ``as_of`` shape and held to the stored set both ways."""
        raise NotImplementedError
