"""What the check compiler asks of a kind of item: the ``compile`` role's protocol (V2-stage4b-0b-inventory.md, 2.2).

Each kind's module overrides what its kind does its own way; the methods
here are what every other kind does. Each is given the compiler as ``c``,
whose checks, copies and faces it reads and adds to.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_checks.kinds.position import BallCentre, Centre, ConeRim, Middle, RoundEdge

if TYPE_CHECKING:
    from forge_spec.draft import Item

    from forge_checks.items.compile._context import CompileContext
    from forge_checks.kinds.position import Ref
    from forge_checks.kinds.surfaces import Plane, Round
    from forge_checks.kinds.wall import Annulus
    from forge_checks.place import Copy, Hollow, RoundSide


class CompileKind:
    """One kind of item, as the check compiler holds it."""

    #: The kind this entry is for.
    key = ""
    #: Whether the implicit view (the oracle) builds it: not true roundings of edges, threads, letters or freeform regions.
    implicit = True
    #: A box: its sides are planes square to the frame's axes (a block's, a post's, a rib's, a tab's).
    boxed = False
    #: It threads a rod (a thread).
    threads = False
    #: Published: a thread may go on it, ``rod_length`` the field its length is in.
    threadable = False
    rod_length = "length"

    # ------------------------------------------------------------------
    # Its own
    # ------------------------------------------------------------------
    def checks(self, c: CompileContext, item: Item) -> None:
        """Every check of the item, and every field it can't check with the reason."""
        raise NotImplementedError(f"no checks for a {self.key}")

    def main(self, c: CompileContext, item: Item, copy: Copy) -> Ref | None:
        """What a copy's centre is measured from: its fitted axis (or ball, or cone's rim); None where it is the middle of its fitted sides."""
        return None

    def sides(
        self, c: CompileContext, item: Item, copy: Copy, axis: str
    ) -> tuple[Plane, Plane] | None:
        """A rectangular item's two fitted sides across ``axis`` (+ first), facing out of its material; None where they are all arc (:meth:`round_ends`), or it has none."""
        return None

    def straight(self, c: CompileContext, item: Item) -> float | None:
        """How far a box's sides run straight from its base, where its far end is rounded; None where they run its whole height."""
        return None

    def round_ends(
        self, c: CompileContext, item: Item, copy: Copy, axis: str
    ) -> tuple[Round, Round] | None:
        """Its two sides across ``axis`` (one of its copy's axes; the -axis one first) where each is all arc: a round surface of each that reaches as far; None where they are flat (or the item is round itself)."""
        return None

    def no_centre(
        self, c: CompileContext, item: Item, group: list[Copy], axis: str
    ) -> str:
        """Why no copy's centre along ``axis`` is found."""
        return "the item's centre can't be fitted"

    def centre_ref(
        self, c: CompileContext, item: Item, copy: Copy, axis: str
    ) -> Ref | None:
        """A copy's built centre along ``axis``: its fitted axis, or the middle of its fitted sides (where they are all arc, of their axes)."""
        main = c._main(item, copy)
        if main is not None:
            return main
        ends = c._round_ends(item, copy, axis)
        if ends is not None:
            return Middle(Centre(ends[0]), Centre(ends[1]))
        sides = c._sides_along(item, copy, axis)
        return Middle(*sides) if sides is not None else None

    def shift(self, c: CompileContext, item: Item, copy: Copy, axis: str) -> float:
        """How far along ``axis`` the centre :meth:`centre_ref` finds is from the point ``place`` puts the item at."""
        return 0.0

    def edge_ref(
        self, c: CompileContext, item: Item, copy: Copy, axis: str, sign: float
    ) -> Ref | None:
        """A copy's edge on the ``sign`` side along ``axis``, as measured from that side's face edge inwards (along ``-sign`` times the axis)."""
        main = c._main(item, copy)
        if isinstance(main, Centre):
            return RoundEdge(main.round, -1.0)
        if isinstance(main, BallCentre):
            return RoundEdge(main.ball, -1.0)
        if isinstance(main, ConeRim):
            return ConeRim(main.cone, 0.0, -1.0)  # its foot: the base's rim
        ends = c._round_ends(item, copy, axis)
        if ends is not None:
            return RoundEdge(ends[1] if sign > 0 else ends[0], -1.0)
        sides = c._sides_along(item, copy, axis)
        if sides is None:
            return None
        return sides[0] if sign > 0 else sides[1]

    def placed_by_its_outline(self, c: CompileContext, item: Item) -> bool:
        """Whether its place is held, as its outline of its own is, by face accounting (a pocket of any outline)."""
        return False

    def own_surface(self, c: CompileContext, item: Item, copy: Copy) -> Round | Plane | None:
        """A surface of a copy's own, to count its copies by, where it has no frame axes to find its sides along (a
        keyway round a side); None where it has none."""
        return None

    def round_copy(
        self, c: CompileContext, item: Item, copy: Copy, side: RoundSide
    ) -> tuple[Round | Middle, float, float] | None:
        """A copy round a side, as its angle is measured: its fitted axis; its size round the side; and its middle's distance from the side's axis."""
        main = c._main(item, copy)
        if isinstance(main, Centre):
            return main.round, 2 * main.round.radius, side.radius
        return None

    # ------------------------------------------------------------------
    # Published: asked of the item another acts on
    # ------------------------------------------------------------------
    def face_refs(
        self, c: CompileContext, owner: Item, copy: Copy, face: str
    ) -> tuple[Ref | str, Ref | str, Ref | str] | str | None:
        """A round face of the item's (``face``, of ``copy``) as references: its edges, each as measured from it into the face, and its centre, each or why it isn't found; None where they aren't fitted."""
        return None

    def hollow_side(self, c: CompileContext, body: Item, copy: Copy, hollow: Hollow) -> Annulus | None:
        """A hollowed body's side wall as its two surfaces, where it is measured so (a cone's: its side and the
        hollow's behind it); None where its faces say it (a rod's, a ball's) or it has none."""
        return None

    def seam(
        self, c: CompileContext, owner: Item, host: tuple[str, int, str], axis: str
    ) -> tuple[float, Ref] | None:
        """Where its face ``host`` runs on smoothly into a round surface, along ``axis``: which side (1 or -1) and the round surface's fitted axis; None where it doesn't."""
        return None
