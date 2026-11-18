"""How the solver places a cone: its entry in the ``solve`` registry (its branches moved from ``placement.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import (
    Item,
)
from forge_spec.geometry import (
    ConeFace,
    Vec,
    disc,
)
from forge_spec.items.solve._common import (
    _add,
    _bounds_round,
    _dir,
    _length_of,
    _round_faces,
    _size,
)
from forge_spec.items.solve.protocol import SolveKind

if TYPE_CHECKING:
    from forge_spec.geometry import Part
    from forge_spec.placement import Layout


class Cone(SolveKind):
    key = "cone"

    rises_by = ("length",)
    round = True
    axial = True

    def outline_fields(
        self, item: Item, axes: tuple[str, str] | None = None, k: int | None = None
    ) -> tuple[str, ...]:
        return ("base_diameter",)

    def outline(
        self, item: Item, layout: Layout, axes: tuple[str, str]
    ) -> tuple[Part, ...]:
        return (disc(max(_size(item, "diameter"), _size(item, "base_diameter")) / 2),)

    def stand(self, item: Item, base: Vec, up: str, axes: tuple[str, str], key: tuple[str, int], layout: Layout,
              host: str | None, joined: str) -> tuple[Vec, Vec, str, dict[str, str]]:  # fmt: skip
        length = _length_of(item, "length") or _size(item, "height")
        outer = (_length_of(item, "diameter") or _length_of(item, "outer_diameter")
                 or _size(item, "base_diameter")) / 2  # fmt: skip
        top = _length_of(item, "top_diameter")
        inner = _size(item, "inner_diameter") / 2
        # A cone wider at its top than its base is as wide as its top.
        lo, hi = _bounds_round(base, up, length, max(outer, (top or 0.0) / 2))
        layout.faces[key] = _round_faces(item, base, up, length, outer,
                                         None if top is None else top / 2, inner)  # fmt: skip
        # Its tapered side takes a hole, a boss or a post, round it and along it (item 3b's third step).
        top_r = outer if top is None else top / 2
        diameters = tuple((item.id, n) for n in ("base_diameter", "top_diameter") if item.get(n) is not None)
        lengths = tuple((item.id, n) for n in ("length", "height") if item.get(n) is not None)
        forward = up[0] == "+"
        layout.faces[key]["side"] = ConeFace(
            "side", up[1], base if forward else _add(base, _dir(up), length), length,
            outer if forward else top_r, top_r if forward else outer,
            None if host is None else ("start" if forward else "end"),
            radius_sources=diameters, length_sources=lengths, depth_sources=diameters + lengths)  # fmt: skip
        if "+end" not in layout.faces[key]:
            layout.close(
                key,
                "+end",
                "fault",
                f"{item.id} comes to a point; it has no +end face",
            )
        return lo, hi, "+end", {}

    def edges(self, which: str, up: str) -> list[tuple[str, str]]:
        rims = {"top": [("+end", "side")], "bottom": [("-end", "side")]}
        rims["both"] = rims["top"] + rims["bottom"]
        return rims.get(which, [])


ENTRY = Cone()
