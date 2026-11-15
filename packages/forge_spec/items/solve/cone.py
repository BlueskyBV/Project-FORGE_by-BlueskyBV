"""How the solver places a cone: its entry in the ``solve`` registry (its branches moved from ``placement.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forge_spec.draft import (
    Item,
)
from forge_spec.geometry import (
    Vec,
    disc,
)
from forge_spec.items.solve._common import (
    _bounds_round,
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
        layout.close(key, "side", "unable",
                     f"{item.id}'s side is tapered; Forge places on a cone's ends only, for now")  # fmt: skip
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
