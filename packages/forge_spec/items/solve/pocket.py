"""How the solver places a pocket: its entry in the ``solve`` registry (its branches moved from ``placement.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import Item
from forge_spec.geometry import (
    EPS,
    FlatFace,
    Less,
    disc,
    outline_on_face,
    rounded_rect,
)
from forge_spec.items.solve._common import (
    _INDEX,
    _RESTS_ON_AN_ASSUMPTION,
    _add,
    _choice_of,
    _dir,
    _item_values,
    _length_of,
    _size,
    mm,
    route,
)
from forge_spec.items.solve.protocol import SolveKind
from forge_spec.problems import pointer
from forge_spec.values import Value

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
        if k is None or axes is None:
            return ("length", "width", "corner_radius")
        return ("length",) if k == 0 else ("width",)

    def outline(
        self, item: Item, layout: Layout, axes: tuple[str, str]
    ) -> tuple[Part, ...]:
        if _choice_of(item, "shape") == "circle":
            return (disc(_size(item, "diameter") / 2),)
        h1, h2 = _size(item, "length") / 2, _size(item, "width") / 2
        return rounded_rect(h1, h2, min(_size(item, "corner_radius"), h1, h2))

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
        from forge_spec.placement import _outline

        depth = item.get("depth")
        layout.faces.setdefault(key, {})
        if not isinstance(depth, Value):
            layout.close(
                key, "bottom", "fault", f"{item.id} goes through; it has no bottom"
            )
            return
        deep = mm(depth)
        if deep >= material - EPS:
            # As deep as the material: it breaks through and leaves no floor. The
            # brief may say both, so who settles it depends on where they came from.
            kind = route("question", [depth, *layout.values_of(face.depth_sources)])
            layout.close(key, "bottom", kind,
                         f"{item.id} ({deep:g} mm deep) goes right through the {material:g} mm of material; "
                         "it has no bottom" + (_RESTS_ON_AN_ASSUMPTION if kind != "question" else ""))  # fmt: skip
            return
        if face.shape == "annulus":
            i1, i2 = (_INDEX[a] for a in face.axes)
            p1, p2 = (
                copy.origin[i1] - face.centre[i1],
                copy.origin[i2] - face.centre[i2],
            )
            if not outline_on_face(face, _outline(item, layout, face.axes), p1, p2):
                # It covers the ring's opening: the bore runs on through its floor.
                layout.close(key, "bottom", "unable",
                             f"{item.id}'s floor has the bore through it: Forge doesn't place on that yet")  # fmt: skip
                return
        centre = _add(copy.origin, _dir(face.normal), -deep)
        i1, i2 = (_INDEX[a] for a in face.axes)
        less = Less(
            face, (centre[i1] - face.centre[i1], centre[i2] - face.centre[i2]), deep
        )
        sizes = tuple(
            (item.id, n) for n in ("length", "width", "diameter", "corner_radius")
        )
        depths = ((item.id, "depth"), *face.depth_sources)
        if _choice_of(item, "shape") == "circle":
            r = _size(item, "diameter") / 2
            diameter = ((item.id, "diameter"),)
            floor = FlatFace("bottom", centre, face.normal, face.axes, "disc", (r, r), 0.0, material - deep,
                             axis_sources=(diameter, diameter), depth_sources=depths, less=less)  # fmt: skip
        else:
            h1, h2 = _size(item, "length") / 2, _size(item, "width") / 2
            radius = min(_size(item, "corner_radius"), h1, h2)
            floor = FlatFace("bottom", centre, face.normal, face.axes, "rect", (h1, h2), 0.0, material - deep,
                             (radius, radius, radius, radius),
                             axis_sources=(((item.id, "length"), *sizes[3:]), ((item.id, "width"), *sizes[3:])),
                             depth_sources=depths, less=less)  # fmt: skip
        layout.faces[key] = {"bottom": floor}


ENTRY = Pocket()
