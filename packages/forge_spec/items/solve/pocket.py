"""How the solver places a pocket: its entry in the ``solve`` registry (its branches moved from ``placement.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item
from forge_spec.ends import Blind, UpToFace, end_of
from forge_spec.geometry import (
    EPS,
    FlatFace,
    Less,
    disc,
    rect,
    rounded_rect,
)
from forge_spec.items.solve._common import (
    _RESTS_ON_AN_ASSUMPTION,
    _add,
    _choice_of,
    _item_values,
    _length_of,
    _size,
    route,
)
from forge_spec.items.solve.protocol import SolveKind
from forge_spec.outline import Shape
from forge_spec.problems import pointer

if TYPE_CHECKING:
    from forge_spec.geometry import FlatFace, Part
    from forge_spec.placement import Instance, Layout


class Pocket(SolveKind):
    key = "pocket"

    def outline_fields(
        self, item: Item, axes: tuple[str, str] | None = None, k: int | None = None
    ) -> tuple[str, ...]:
        if _choice_of(item, "shape") == "circle":
            return ("diameter",)
        if _choice_of(item, "shape") == "hexagon":
            return ("across_flats",)
        if k is None or axes is None:
            return ("length", "width", "corner_radius")
        return ("length",) if k == 0 else ("width",)

    def outline(
        self, item: Item, layout: Layout, axes: tuple[str, str]
    ) -> tuple[Part, ...]:
        if _choice_of(item, "shape") == "circle":
            return (disc(_size(item, "diameter") / 2),)
        if _choice_of(item, "shape") == "hexagon":  # the box round it: it is placed by its own outline (shape)
            (l1, l2), (h1, h2) = _hexagon(item).box()
            return (rect((h1 - l1) / 2, (h2 - l2) / 2),)
        h1, h2 = _size(item, "length") / 2, _size(item, "width") / 2
        return rounded_rect(h1, h2, min(_size(item, "corner_radius"), h1, h2))

    def shape(self, item: Item, layout: Layout, axes: tuple[str, str]) -> Shape | None:
        return _hexagon(item) if _choice_of(item, "shape") == "hexagon" else None

    def turnable(
        self, item: Item, layout: Layout, axes: tuple[str, str]
    ) -> tuple[float, float, float] | None:
        if _choice_of(item, "shape") in ("circle", "hexagon"):
            return None  # a round pocket turned is the same pocket; a hexagon turns as its own outline (shape)
        h1, h2 = _size(item, "length") / 2, _size(item, "width") / 2
        return h1, h2, min(_size(item, "corner_radius"), h1, h2)

    def check_shape(self, item: Item, at: str, layout: Layout) -> None:
        if _choice_of(item, "shape") == "rectangle":
            radius = _length_of(item, "corner_radius")
            length, width = _size(item, "length"), _size(item, "width")
            if radius is not None and radius > min(length, width) / 2 + EPS:
                layout.problem("cant", at + pointer("corner_radius"),
                               f"a {radius:g} mm corner radius doesn't fit a {length:g} x {width:g} mm pocket "
                               f"(at most {min(length, width) / 2:g} mm)",
                               _item_values(item, "corner_radius", "width" if width < length else "length"))  # fmt: skip

    def floor(self, item: Item, copy: Instance, face: FlatFace, material: float, key: tuple[str, int],
              layout: Layout) -> None:  # fmt: skip
        """The floor of a pocket, a face other features can go into."""
        from forge_spec.placement import _outline, cut_depth

        end = end_of(item)
        layout.faces.setdefault(key, {})
        resolved = cut_depth(item, copy, layout) if isinstance(end, (Blind, UpToFace)) else None
        if resolved is None:
            layout.close(
                key, "bottom", "fault", f"{item.id} goes through; it has no bottom"
            )
            return
        # A blind one's depth; up to a face (item 2b's first step), as deep as that face's plane, its offset back.
        depth: object = end.depth if isinstance(end, Blind) else (end.offset if isinstance(end, UpToFace) else None)
        deep = resolved
        if deep >= material - EPS:
            # As deep as the material: it breaks through and leaves no floor. The
            # brief may say both, so who settles it depends on where they came from.
            kind = route("question", [*([depth] if depth is not None else []), *layout.values_of(face.depth_sources)])
            layout.close(key, "bottom", kind,
                         f"{item.id} ({deep:g} mm deep) goes right through the {material:g} mm of material; "
                         "it has no bottom" + (_RESTS_ON_AN_ASSUMPTION if kind != "question" else ""))  # fmt: skip
            return
        if face.shape == "annulus":
            p1, p2 = face.frame.on(copy.origin)
            if not face.holds(_outline(item, layout, face.axes), (p1, p2)):
                # It covers the ring's opening: the bore runs on through its floor.
                layout.close(key, "bottom", "unable",
                             f"{item.id}'s floor has the bore through it: Forge doesn't place on that yet")  # fmt: skip
                return
        centre = _add(copy.origin, face.frame.n, -deep)
        less = Less(face, face.frame.on(centre), deep)
        sizes = tuple(
            (item.id, n) for n in ("length", "width", "diameter", "corner_radius")
        )
        depths = ((item.id, "depth"), *face.depth_sources)
        if _choice_of(item, "shape") == "circle":
            r = _size(item, "diameter") / 2
            diameter = ((item.id, "diameter"),)
            floor = FlatFace("bottom", centre, face.normal, face.axes, "disc", (r, r), 0.0, material - deep,
                             axis_sources=(diameter, diameter), depth_sources=depths, less=less)  # fmt: skip
        elif _choice_of(item, "shape") == "hexagon":
            hexagon = _hexagon(item)
            (l1, l2), (h1, h2) = hexagon.box()
            flats = ((item.id, "across_flats"),)
            floor = FlatFace("bottom", centre, face.normal, face.axes, "profile", ((h1 - l1) / 2, (h2 - l2) / 2), 0.0,
                             material - deep, axis_sources=(flats, flats), depth_sources=depths, profile=hexagon,
                             less=less)  # fmt: skip
        else:
            h1, h2 = _size(item, "length") / 2, _size(item, "width") / 2
            radius = min(_size(item, "corner_radius"), h1, h2)
            floor = FlatFace("bottom", centre, face.normal, face.axes, "rect", (h1, h2), 0.0, material - deep,
                             (radius, radius, radius, radius),
                             axis_sources=(((item.id, "length"), *sizes[3:]), ((item.id, "width"), *sizes[3:])),
                             depth_sources=depths, less=less)  # fmt: skip
        layout.faces[key] = {"bottom": floor}


def _hexagon(item: Item) -> Shape:
    """A hexagonal pocket's outline about its point (pocket.md): two corners on the face's first axis."""
    return Shape.hexagon((0.0, 0.0), _size(item, "across_flats"))


ENTRY = Pocket()
