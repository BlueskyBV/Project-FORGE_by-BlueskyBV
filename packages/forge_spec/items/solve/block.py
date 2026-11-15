"""How the solver places a block: its entry in the ``solve`` registry (its branches moved from ``placement.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

import math
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
    _INDEX,
    _bounds_box,
    _box_faces,
    _item_values,
    _opposite,
    _size,
    _with,
)
from forge_spec.items.solve.protocol import SolveKind
from forge_spec.problems import pointer
from forge_spec.schema import DIRECTIONS, FACE_AXES

if TYPE_CHECKING:
    from forge_spec.geometry import FlatFace, Part
    from forge_spec.items.solve._common import Hollowing
    from forge_spec.placement import Layout


class Block(SolveKind):
    key = "block"

    shell_fields = True

    def outline_fields(
        self, item: Item, axes: tuple[str, str] | None = None, k: int | None = None
    ) -> tuple[str, ...]:
        if k is None or axes is None:
            return ("length", "width")
        return ("length",) if k == 0 else ("width",)

    def outline(
        self, item: Item, layout: Layout, axes: tuple[str, str]
    ) -> tuple[Part, ...]:
        return (rect(_size(item, "length") / 2, _size(item, "width") / 2),)

    def stand(self, item: Item, base: Vec, up: str, axes: tuple[str, str], key: tuple[str, int], layout: Layout,
              host: str | None, joined: str) -> tuple[Vec, Vec, str, dict[str, str]]:  # fmt: skip
        a1, a2 = axes
        sizes = {a1: _size(item, "length"), a2: _size(item, "width")}
        lo, hi = _bounds_box(base, up, sizes, _size(item, "height"))
        fields = {a1: "length", a2: "width", up[1]: "height"}
        layout.faces[key] = _box_faces(lo, hi, item.id, fields)
        return lo, hi, up, fields

    def open_faces_allowed(self, item: Item) -> set[str]:
        return set(DIRECTIONS)

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
        th = {d: wall(d, _opposite(d)) for d in DIRECTIONS}
        cavity_lo = [lo[i] + th["-" + "xyz"[i]] for i in range(3)]
        cavity_hi = [hi[i] - th["+" + "xyz"[i]] for i in range(3)]
        shut = [a for i, a in enumerate("xyz") if cavity_hi[i] - cavity_lo[i] <= EPS]
        if shut:
            layout.problem("cant", shell_at + pointer("thickness"),
                           f"{t:g} mm walls leave no hollow inside {item.id} along {', '.join(shut)}",
                           [thickness_value, floor_value, *_item_values(item, *(fields.get(a, "height") for a in shut))])  # fmt: skip
            return
        layout.cavities[key] = ((cavity_lo[0], cavity_lo[1], cavity_lo[2]),
                                (cavity_hi[0], cavity_hi[1], cavity_hi[2]))  # fmt: skip
        for d in DIRECTIONS:
            face = faces.get(d)
            if isinstance(face, FlatFace):
                faces[d] = _with(face, depth_below=th[d], depth_sources=walls)
            inner = f"inner {d}"
            if d in open_faces:
                layout.close(
                    key,
                    inner,
                    "fault",
                    f"{item.id}'s {d} side is open: it has no wall there",
                )
                continue
            k = _INDEX[d[1]]
            a1, a2 = FACE_AXES[d]
            centre = [(cavity_lo[i] + cavity_hi[i]) / 2 for i in range(3)]
            centre[k] = cavity_hi[k] if d[0] == "+" else cavity_lo[k]
            half = ((cavity_hi[_INDEX[a1]] - cavity_lo[_INDEX[a1]]) / 2,
                    (cavity_hi[_INDEX[a2]] - cavity_lo[_INDEX[a2]]) / 2)  # fmt: skip
            room = (
                math.inf if _opposite(d) in open_faces else cavity_hi[k] - cavity_lo[k]
            )
            own = (item.id, fields.get(a1, "")), (item.id, fields.get(a2, ""))
            faces[inner] = FlatFace(inner, (centre[0], centre[1], centre[2]), _opposite(d), (a1, a2), "rect", half,
                                    0.0, th[d], axis_sources=((own[0], *walls), (own[1], *walls)),
                                    depth_sources=walls, room=room,
                                    room_sources=((item.id, fields.get(d[1], "")), *walls))  # fmt: skip
        return

    def edges(self, which: str, up: str) -> list[tuple[str, str]]:
        down = _opposite(up)
        sides = [d for d in DIRECTIONS if d[1] != up[1]]
        vertical = [
            (a, b) for n, a in enumerate(sides) for b in sides[n + 1 :] if a[1] != b[1]
        ]
        sets = {
            "vertical": vertical,
            "top": [(up, s) for s in sides],
            "bottom": [(down, s) for s in sides],
        }
        sets["all"] = sets["vertical"] + sets["top"] + sets["bottom"]
        return sets.get(which, [])


ENTRY = Block()
