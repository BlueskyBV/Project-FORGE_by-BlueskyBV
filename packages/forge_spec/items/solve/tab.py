"""How the solver places a tab: its entry in the ``solve`` registry (its branches moved from ``placement.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import (
    Item,
)
from forge_spec.geometry import (
    EPS,
    FlatFace,
    Vec,
    rect,
)
from forge_spec.items.solve._common import (
    _bounds_box,
    _box_faces,
    _choice_of,
    _item_values,
    _oriented,
    _size,
    _with,
)
from forge_spec.items.solve.protocol import SolveKind
from forge_spec.problems import pointer

if TYPE_CHECKING:
    from forge_spec.geometry import FlatFace, Part
    from forge_spec.placement import Layout


def _tab(item: Item, base: Vec, up: str, axes: tuple[str, str], key: tuple[str, int],
         layout: Layout) -> tuple[Vec, Vec]:  # fmt: skip
    """A tab's bounds and faces; a round end rounds two corners of its flat faces."""
    a1, a2 = axes
    thin = _choice_of(item, "thickness_along") or a2
    wide = a1 if thin == a2 else a2
    thickness, width, length = (
        _size(item, "thickness"),
        _size(item, "width"),
        _size(item, "length"),
    )
    sizes = {thin: thickness, wide: width}
    lo, hi = _bounds_box(base, up, sizes, length)
    fields = {thin: "thickness", wide: "width", up[1]: "length"}
    faces = _box_faces(lo, hi, item.id, fields)
    layout.faces[key] = faces
    if _choice_of(item, "end") != "round":
        return lo, hi
    radius = width / 2
    layout.close(key, up, "unable",
                 f"{item.id}'s round end is curved; Forge places on its flat faces only, for now")  # fmt: skip
    straight = length - radius
    for side in ("+" + wide, "-" + wide):
        if straight > EPS:
            faces[side] = _box_faces(
                *_bounds_box(base, up, sizes, straight), item.id, fields
            )[side]
        else:
            layout.close(key, side, "fault",
                         f"{item.id} is all round end ({length:g} mm long, {width:g} mm wide): it has no {side} face")  # fmt: skip
    for side in ("+" + thin, "-" + thin):
        flat = faces[side]
        assert isinstance(flat, FlatFace)
        k = flat.axes.index(up[1])  # the round end is along this axis of the face
        sign = 1 if up[0] == "+" else -1
        # The two corners at the far end are each a quarter of the half-circle:
        # as big as half the width, and as long as the tab allows.
        size = min(radius, 2 * flat.half[k], flat.half[1 - k])
        corners = tuple(size if (s1, s2)[k] == sign else 0.0
                        for s1, s2 in ((1, 1), (-1, 1), (-1, -1), (1, -1)))  # fmt: skip
        faces[side] = _with(
            flat, corners=(corners[0], corners[1], corners[2], corners[3])
        )
    return lo, hi


class Tab(SolveKind):
    key = "tab"

    rises_by = ("length",)

    def outline_fields(
        self, item: Item, axes: tuple[str, str] | None = None, k: int | None = None
    ) -> tuple[str, ...]:
        if k is None or axes is None:
            return ("thickness", "width")
        return (
            ("thickness",)
            if _choice_of(item, "thickness_along") == axes[k]
            else ("width",)
        )

    def outline(
        self, item: Item, layout: Layout, axes: tuple[str, str]
    ) -> tuple[Part, ...]:
        thin, wide = _size(item, "thickness") / 2, _size(item, "width") / 2
        return (
            rect(*_oriented(axes, _choice_of(item, "thickness_along"), thin, wide)),
        )

    def turnable(
        self, item: Item, layout: Layout, axes: tuple[str, str]
    ) -> tuple[float, float, float] | None:
        (foot,) = self.outline(item, layout, axes)
        return foot.half[0], foot.half[1], 0.0

    def check_shape(self, item: Item, at: str, layout: Layout) -> None:
        if _choice_of(item, "end") == "round":
            length, width = _size(item, "length"), _size(item, "width")
            if length < width / 2 - EPS:
                layout.problem("cant", at + pointer("length"),
                               f"a fully round end needs the tab to stick out at least half its width "
                               f"({width / 2:g} mm); it sticks out {length:g} mm",
                               _item_values(item, "length", "width", "end"))  # fmt: skip

    def stand(self, item: Item, base: Vec, up: str, axes: tuple[str, str], key: tuple[str, int], layout: Layout,
              host: str | None, joined: str) -> tuple[Vec, Vec, str, dict[str, str]]:  # fmt: skip
        lo, hi = _tab(item, base, up, axes, key, layout)
        return lo, hi, up, {}


ENTRY = Tab()
