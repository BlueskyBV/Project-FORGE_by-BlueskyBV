"""What the judge's own placement asks of a kind of item: the ``place`` role's protocol (V2-stage4b-0b-inventory.md, 2.2).

Each kind's module overrides what its kind does its own way; the methods
here are what every other kind does. ``place.py`` asks the registry when
placing, never when imported, so these modules use its vocabulary.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

from forge_spec.draft import Item
from forge_spec.schema import KINDS, Category

from forge_checks.outlines import Outline
from forge_checks.place import (
    Copy,
    Face,
    FlatFace,
    Material,
    PlaceError,
    Point,
    RoundSide,
    Vec,
    _footprint,
    _Layout,
    _standing,
    direction_of,
)

Edges = tuple[tuple[str, str], ...]


class PlaceKind:
    """One kind of item, as the judge places it from its definition."""

    #: The kind this entry is for.
    key = ""

    @property
    def hollowable(self) -> bool:
        """Published: a shell may hollow it (its definition says so: shell.md)."""
        return KINDS[self.key].hollowable

    #: A first body or a body on a face runs along the axis it names, or the face's normal (a round or outlined body).
    axial = False
    #: It is joined to what it stands on by its ``-end`` (a round or outlined body, a ball), not the face opposite its up.
    joined_by_end = False
    #: It rounds another's edges (a fillet, a chamfer); it is made after everything else (they, and a thread).
    rounds_edges = False
    made_last = False
    #: Published: the solver keeps its hollow's box (not a ball's).
    cavity_boxed = True
    #: Published: the rims its edge sets name, by the two faces each lies between; ``both_ends``: ``both`` is its top and bottom.
    rims: ClassVar[Mapping[str, Edges]] = {}
    both_ends = False

    #: It may lean from square to its flat face (``tilt``; place.md): a hole, a boss, a post, a block and a cylinder.
    leans = False
    #: The field it rises by out of the face it stands on (a cylinder's, its length).
    rise = "height"

    def turnable(self, item: Item) -> bool:
        """Whether a ``place.turn`` turns it in its face's plane (place.md): a slot, a rectangular pocket, a rib, a tab, a
        block, a post and a line of letters."""
        return False

    @property
    def made(self) -> bool:
        """It is made, not a change to another (a modifier)."""
        return KINDS[self.key].category is not Category.MODIFY

    @property
    def is_body(self) -> bool:
        """A body: the first sits on the origin, every other stands on a face."""
        return KINDS[self.key].category is Category.BODY

    @property
    def taken(self) -> bool:
        """A cut: taken from the material under the face it is on."""
        return KINDS[self.key].category is Category.CUT

    @property
    def goes_round_side(self) -> bool:
        """It may go round a round side (a standing feature, a hole)."""
        return KINDS[self.key].category is Category.ADD

    #: It may go on a ball's, a dome's or a cone's curved surface (item 3b's second and third steps): a hole, a boss,
    #: a post.
    goes_on_curved = False

    # ------------------------------------------------------------------
    # Its own
    # ------------------------------------------------------------------
    def read(self, item: Item, layout: _Layout) -> None:
        """What placing reads of the item before anything is placed (a shell's body, a hole's diameter)."""

    def footprint(
        self, item: Item, diameters: Mapping[str, float], axes: tuple[str, str]
    ) -> Outline:
        """Its outline on a flat face with these axes, centred on the origin of the face's coordinates."""
        raise PlaceError(item.id, f"a {item.kind} has no footprint on a face")

    def extent(
        self, item: Item, foot: Outline
    ) -> tuple[tuple[float, float], tuple[float, float]]:
        """How far it reaches back and forth along a face's two axes from its point: its footprint's box."""
        (c1, c2), (h1, h2) = foot.centre, foot.half
        return (c1 - h1, c1 + h1), (c2 - h2, c2 + h2)

    def covers(
        self, item: Item, diameters: Mapping[str, float], face: FlatFace
    ) -> Outline | None:
        """What it covers on a flat face, centred on the origin of the face's coordinates: its footprint."""
        return _footprint(item, diameters, face.axes)

    def mouth(self, item: Item, layout: _Layout, face: FlatFace, at: Point) -> Outline:
        """The outline a cut goes in through: what it covers (a line of letters' ink's box), or its outline."""
        from forge_checks.place import _covering

        covering = _covering(item, layout.diameters, face)
        if (
            covering is None
        ):  # letters with no ink take nothing: their line's box stands for them
            covering = _footprint(item, layout.diameters, face.axes)
        return covering.moved(*at)

    def embossed(self, item: Item) -> bool:
        """A cut that stands out of the face instead (letters embossed)."""
        return False

    def cut_through(self, item: Item) -> None:
        """A cut through all the material under its mouth: refused where it can't be."""

    def after_cut(self, item: Item, face: FlatFace, index: int, point: Vec, mouth: Outline, depth: float,
                  layout: _Layout) -> None:  # fmt: skip
        """What a cut's copy makes beyond its own span (a pocket's floor)."""

    def round_frame(
        self, item: Item, direction: Vec, axis: str, layout: _Layout
    ) -> tuple[str | None, tuple[str, str] | None, float]:
        """Round a side, facing ``direction`` off its ``axis``: the way it stands, its axes, and how far it reaches along the side."""
        up = direction_of(direction)
        if up is None:
            raise PlaceError(
                item.id,
                "a standing feature stands round a side only where it faces along a frame axis",
            )
        around = next(a for a in "xyz" if a not in (up[1], axis))
        axes = (around, axis)
        reach_along = _footprint(item, layout.diameters, axes).half[1]
        return up, axes, reach_along

    def round_copy(self, item: Item, side: RoundSide, host: tuple[str, int, str], index: int, point: Vec,
                   direction: Vec, up: str | None, axes: tuple[str, str] | None, layout: _Layout) -> Copy:  # fmt: skip
        """One copy round a side: standing on it."""
        assert axes is not None and up is not None
        return _standing(item, side, host, index, point, up, axes, layout)

    def body(self, item: Item, layout: _Layout, key: tuple[str, int], host: tuple[str, int, str] | None,
             point: Vec, up: str, axes: tuple[str, str], under: tuple[tuple[Outline, ...], Material] | None,
             faces: dict[str, Face]) -> tuple[Vec, Vec]:  # fmt: skip
        """A body's or standing feature's bounds, its faces put in ``faces`` (or closed)."""
        raise PlaceError(item.id, f"a {item.kind} doesn't stand on a face")

    def ends(self, item: Item, layout: _Layout, key: tuple[str, int], point: Vec, up: str, axes: tuple[str, str],
             under: tuple[tuple[Outline, ...], Material] | None, faces: dict[str, Face], section: Outline,
             at: tuple[float, float]) -> tuple[Vec, Vec]:  # fmt: skip
        """An outlined body's two far corners, its flat ends put in ``faces``."""
        raise PlaceError(item.id, f"a {item.kind} has no outline")

    def far(self, up: str) -> str:
        """The face that takes things where it stands round a side: its far one."""
        return up

    # ------------------------------------------------------------------
    # Published: asked of the item another acts on
    # ------------------------------------------------------------------
    def edges(self, which: str, up: str) -> Edges:
        """Its edges ``which``, each by the two faces it lies between."""
        if which == "both" and self.both_ends:
            return self.rims["top"] + self.rims["bottom"]
        return self.rims.get(which, ())

    def openable(self, item: Item) -> set[str]:
        """The faces a shell may leave open."""
        return set()

    def rim(self, face: FlatFace, thickness: float, open_faces: frozenset[str]) -> FlatFace | None:
        """The rim a shell leaves of a face it leaves open, ``thickness`` walls round the hollow (shell.md, "The rim"),
        ``open_faces`` the faces it leaves open: the face less the hollow's mouth, its material what was under it; None
        where it takes nothing yet."""
        return None

    def hollow(self, item: Item, layout: _Layout, key: tuple[str, int], base: Vec, up: str, lo: Vec, hi: Vec,
               shell: Item, thickness: float, floor: float | None, open_faces: frozenset[str]) -> None:  # fmt: skip
        """Hollow one copy: its walls as the material under its faces, its inside faces, and the hollow."""
        raise PlaceError(
            shell.id,
            f"a shell hollows a block, a cylinder or a sphere, not a {item.kind}",
        )
