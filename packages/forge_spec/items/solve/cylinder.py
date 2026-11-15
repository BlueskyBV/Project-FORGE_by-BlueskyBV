"""How the solver places a cylinder: its entry in the ``solve`` registry (its branches moved from ``placement.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from forge_spec.draft import (
    Item,
)
from forge_spec.geometry import (
    EPS,
    FlatFace,
    SideFace,
    Vec,
    disc,
)
from forge_spec.items.solve._common import (
    _INDEX,
    _bounds_round,
    _item_values,
    _length_of,
    _opposite,
    _round_faces,
    _size,
    _with,
)
from forge_spec.items.solve.protocol import SolveKind
from forge_spec.problems import pointer
from forge_spec.schema import FACE_AXES

if TYPE_CHECKING:
    from forge_spec.geometry import FlatFace, Part
    from forge_spec.items.solve._common import Hollowing
    from forge_spec.placement import Layout


class Cylinder(SolveKind):
    key = "cylinder"

    rises_by = ("length",)
    round = True
    axial = True

    def outline_fields(
        self, item: Item, axes: tuple[str, str] | None = None, k: int | None = None
    ) -> tuple[str, ...]:
        return ("diameter",)

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
        return lo, hi, "+end", {}

    def open_faces_allowed(self, item: Item) -> set[str]:
        return {"+end", "-end"}

    def floor_fault(
        self,
        item: Item,
        outer: set[str],
        open_faces: set[str],
        floored: list[str],
        shell: Item,
    ) -> str | None:
        if not floored:
            return (f"a floor is the wall opposite an opening, and {shell.id} has "
                    + ("no opening" if not open_faces else f"none with a wall opposite ({sorted(open_faces)})")
                    + ": leave the floor out")  # fmt: skip
        return None

    def hollow(self, item: Item, key: tuple[str, int], lo: Vec, hi: Vec, up: str, layout: Layout,
               fields: dict[str, str], h: Hollowing) -> None:  # fmt: skip
        shell_at, t = h.shell_at, h.thickness
        thickness_value, floor_value = h.thickness_value, h.floor_value
        open_faces, walls, wall = h.open_faces, h.walls, h.wall
        faces = layout.faces[key]
        radius = (hi[_INDEX[FACE_AXES[up][0]]] - lo[_INDEX[FACE_AXES[up][0]]]) / 2
        length = _size(item, "length")
        top, bottom = wall("+end", "-end"), wall("-end", "+end")
        if radius - t <= EPS or length - top - bottom <= EPS:
            layout.problem("cant", shell_at + pointer("thickness"),
                           f"{t:g} mm walls leave no hollow inside {item.id}",
                           [thickness_value, floor_value, *_item_values(item, "diameter" if radius - t <= EPS else "length")])  # fmt: skip
            return
        for name, depth in (("+end", top), ("-end", bottom)):
            face = faces.get(name)
            if isinstance(face, FlatFace):
                faces[name] = _with(face, depth_below=depth, depth_sources=walls)
        side = faces.get("side")
        if isinstance(side, SideFace):
            faces["side"] = _with(side, wall=t, depth_sources=walls)
        k = _INDEX[up[1]]
        sign = 1.0 if up[0] == "+" else -1.0  # from the -end towards the +end
        plus_end, minus_end = (hi[k], lo[k]) if sign > 0 else (lo[k], hi[k])
        inner_plus, inner_minus = plus_end - sign * top, minus_end + sign * bottom
        centre_line = [(lo[i] + hi[i]) / 2 for i in range(3)]
        a1, a2 = FACE_AXES[up]
        diameter = ((item.id, "diameter"), *walls)
        inner_length = length - top - bottom
        for name, depth, where, normal, far in (("inner +end", top, inner_plus, _opposite(up), "-end"),
                                                ("inner -end", bottom, inner_minus, up, "+end")):  # fmt: skip
            if depth == 0.0:
                layout.close(
                    key,
                    name,
                    "fault",
                    f"{item.id}'s {name[6:]} is open: it has no wall there",
                )
                continue
            position = list(centre_line)
            position[k] = where
            room = math.inf if far in open_faces else inner_length
            faces[name] = FlatFace(name, (position[0], position[1], position[2]), normal, (a1, a2), "disc",
                                   (radius - t, radius - t), 0.0, depth, axis_sources=(diameter, diameter),
                                   depth_sources=walls, room=room,
                                   room_sources=((item.id, "length"), *walls))  # fmt: skip
        start = list(centre_line)
        start[k] = min(inner_plus, inner_minus)
        inner_lo = [centre_line[i] - (radius - t) for i in range(3)]
        inner_hi = [centre_line[i] + (radius - t) for i in range(3)]
        inner_lo[k], inner_hi[k] = (
            min(inner_plus, inner_minus),
            max(inner_plus, inner_minus),
        )
        layout.cavities[key] = (
            (inner_lo[0], inner_lo[1], inner_lo[2]),
            (inner_hi[0], inner_hi[1], inner_hi[2]),
        )
        faces["inner side"] = SideFace("inner side", up[1], (start[0], start[1], start[2]), inner_length,
                                       radius - t, False, t, radius_sources=diameter,
                                       length_sources=((item.id, "length"), *walls), depth_sources=walls)  # fmt: skip
        return

    def edges(self, which: str, up: str) -> list[tuple[str, str]]:
        rims = {"top": [("+end", "side")], "bottom": [("-end", "side")]}
        rims["both"] = rims["top"] + rims["bottom"]
        return rims.get(which, [])


ENTRY = Cylinder()
