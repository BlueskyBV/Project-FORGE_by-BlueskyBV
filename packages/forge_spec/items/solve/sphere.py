"""How the solver places a sphere: its entry in the ``solve`` registry (its branches moved from ``placement.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import TYPE_CHECKING

from forge_spec.draft import (
    Item,
)
from forge_spec.geometry import (
    EPS,
    BallFace,
    Dome,
    FlatFace,
    Vec,
    disc,
)
from forge_spec.items.solve._common import (
    _add,
    _bounds_round,
    _choice_of,
    _dir,
    _item_values,
    _size,
    _with,
    uneven_roundings,
)
from forge_spec.items.solve.protocol import SolveKind
from forge_spec.problems import pointer
from forge_spec.schema import FACE_AXES

if TYPE_CHECKING:
    from forge_spec.geometry import FlatFace, Part
    from forge_spec.items.solve._common import Hollowing
    from forge_spec.placement import Layout


class Sphere(SolveKind):
    key = "sphere"

    round = True

    def height(self, item: Item) -> tuple[float, str] | None:
        found = super().height(item)
        if found is not None:
            return found
        d = _size(item, "diameter")
        return (d / 2 if _choice_of(item, "portion") == "upper_half" else d), "diameter"

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
        d = _size(item, "diameter")
        half = _choice_of(item, "portion") == "upper_half"
        diameter = ((item.id, "diameter"),)
        if half:
            centre = base
            lo, hi = _bounds_round(base, up, d / 2, d / 2)
            flat = FlatFace("-end", base, joined, FACE_AXES[up], "disc", (d / 2, d / 2), 0.0, d / 2,
                            depth_model=Dome(d / 2), axis_sources=(diameter, diameter),
                            depth_sources=diameter)  # fmt: skip
            layout.faces[key] = {"-end": flat}
        else:
            # A whole ball standing on a face is centred on it, not touching it at a point.
            centre = base if host is not None else _add(base, _dir(up), d / 2)
            lo = (centre[0] - d / 2, centre[1] - d / 2, centre[2] - d / 2)
            hi = (centre[0] + d / 2, centre[1] + d / 2, centre[2] + d / 2)
            layout.faces[key] = {}
            layout.close(
                key, "-end", "fault", f"{item.id} is a whole ball; it has no flat face"
            )
        # Its curved surface takes a hole, a boss or a post, at a latitude and round its pole (item 3b's second step).
        layout.faces[key]["surface"] = BallFace("surface", centre, up, d / 2, dome=half,
                                                standing=host is not None, radius_sources=diameter)  # fmt: skip
        return lo, hi, "", {}

    def open_faces_allowed(self, item: Item) -> set[str]:
        return {"-end"} if _choice_of(item, "portion") == "upper_half" else set()

    def floor_fault(
        self,
        item: Item,
        outer: set[str],
        open_faces: set[str],
        floored: list[str],
        shell: Item,
    ) -> str | None:
        if not outer or "-end" in open_faces:
            # A dome's floor is its flat face's wall; a whole ball, or a dome
            # open underneath, has none (docs/definitions/shell.md).
            return (f"{item.id} is " + ("a whole ball" if not outer else "open underneath")
                    + ": its hollow has no floor; leave the floor out")  # fmt: skip
        return None

    def hollow(self, item: Item, key: tuple[str, int], lo: Vec, hi: Vec, up: str, layout: Layout,
               fields: dict[str, str], h: Hollowing) -> None:  # fmt: skip
        shell_at, t, f = h.shell_at, h.thickness, h.floor
        thickness_value, floor_value = h.thickness_value, h.floor_value
        open_faces, walls = h.open_faces, h.walls
        faces = layout.faces[key]
        radius = _size(item, "diameter") / 2
        dome = _choice_of(item, "portion") == "upper_half"
        room_left = radius - t - (0.0 if not dome or "-end" in open_faces else f)
        if room_left <= EPS:
            layout.problem("cant", shell_at + pointer("thickness"), f"{t:g} mm walls leave no hollow inside {item.id}",
                           [thickness_value, floor_value, *_item_values(item, "diameter")])  # fmt: skip
            return
        if "surface" in faces:
            del faces["surface"]
            layout.close(key, "surface", "unable",
                         f"{item.id} is hollowed: Forge places on a hollowed ball's surface in a later step")  # fmt: skip
        flat = faces.get("-end")
        if isinstance(flat, FlatFace) and "-end" not in open_faces:
            # Its floor: no more than its thickness, nor than the dome over it near its rim (frame.md).
            faces["-end"] = _with(flat, depth_below=f, depth_model=Dome(radius, f), depth_sources=walls)
            inside = math.sqrt(max((radius - t) * (radius - t) - f * f, 0.0))  # the hollow's section over its floor
            layout.insides[(key[0], key[1], "-end")] = replace(
                flat, centre=_add(flat.centre, _dir(up), f), half=(inside, inside), depth_model=None)
            uneven_roundings(item, layout, {"-end": f, "surface": t}, lambda which: self.edges(which, up))

    def edges(self, which: str, up: str) -> list[tuple[str, str]]:
        if which == "bottom":
            return [("-end", "surface")]
        return []


ENTRY = Sphere()
