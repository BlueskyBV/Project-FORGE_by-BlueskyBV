"""Where the judge places a sphere: its entry in the ``place`` registry (its branches moved from ``place.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

from forge_spec.draft import Item

from forge_checks.items.place.protocol import Edges, PlaceKind
from forge_checks.outlines import TOL, Outline
from forge_checks.place import (
    _INDEX,
    FLAT_AXES,
    Dome,
    Face,
    FlatFace,
    Hollow,
    Material,
    PlaceError,
    RoundBall,
    Solid,
    Vec,
    _add,
    _box,
    _choice,
    _in_plane,
    _Layout,
    _mm,
    opposite,
    unit,
)


class Sphere(PlaceKind):
    key = "sphere"

    joined_by_end = True
    cavity_boxed = False
    rims: ClassVar[Mapping[str, Edges]] = {"bottom": (("-end", "surface"),)}

    def footprint(
        self, item: Item, diameters: Mapping[str, float], axes: tuple[str, str]
    ) -> Outline:
        return Outline.disc(_mm(item, "diameter") / 2)

    def body(self, item: Item, layout: _Layout, key: tuple[str, int], host: tuple[str, int, str] | None,
             point: Vec, up: str, axes: tuple[str, str], under: tuple[tuple[Outline, ...], Material] | None,
             faces: dict[str, Face]) -> tuple[Vec, Vec]:  # fmt: skip
        a1, a2 = axes
        u = unit(up)
        radius = _mm(item, "diameter") / 2
        if _choice(item, "portion") == "upper_half":
            centre = point
            lo, hi = _box(point, up, {a1: 2 * radius, a2: 2 * radius}, radius)
            plane = FLAT_AXES[up[1]]
            faces["-end"] = FlatFace("-end", point, opposite(up), plane, Outline.disc(radius, _in_plane(point, plane)),
                                     Dome(_in_plane(point, plane), radius))  # fmt: skip
        else:
            centre = point if host is not None else _add(point, u, radius)
            lo = (centre[0] - radius, centre[1] - radius, centre[2] - radius)
            hi = (centre[0] + radius, centre[1] + radius, centre[2] + radius)
            layout.close(key, "-end", "a whole ball has no flat face")
        # Its curved surface takes a hole, a boss or a post (item 3b's second step).
        faces["surface"] = RoundBall("surface", centre, up, radius, _choice(item, "portion") == "upper_half",
                                     host is not None)  # fmt: skip
        return lo, hi

    def openable(self, item: Item) -> set[str]:
        dome = _choice(item, "portion") == "upper_half"
        return {"-end"} if dome else set()

    def hollow(self, item: Item, layout: _Layout, key: tuple[str, int], base: Vec, up: str, lo: Vec, hi: Vec,
               shell: Item, thickness: float, floor: float | None, open_faces: frozenset[str]) -> None:  # fmt: skip
        faces = layout.faces[key]
        dome = _choice(item, "portion") == "upper_half"
        if "surface" in faces:
            layout.close(key, "surface", "a hollowed ball's surface takes nothing, for now")
        if floor is not None and (not dome or "-end" in open_faces):
            raise PlaceError(
                shell.id, "only a dome with its flat face closed has a floor"
            )
        radius = (hi[0] - lo[0]) / 2
        walls = (
            {}
            if not dome or "-end" in open_faces
            else {"-end": floor if floor is not None else thickness}
        )
        walls["surface"] = thickness
        floor_wall = walls.get("-end", 0.0)
        if radius - thickness - floor_wall <= TOL:
            raise PlaceError(
                shell.id, f"{thickness:g} mm walls leave no hollow inside {item.id}"
            )
        flat = faces.get("-end")
        if isinstance(flat, FlatFace) and "-end" in walls:
            faces["-end"] = FlatFace(
                "-end",
                flat.centre,
                flat.normal,
                flat.axes,
                flat.outline,
                Solid(walls["-end"]),
            )
        if dome:
            k = _INDEX[up[1]]
            sign = 1.0 if up[0] == "+" else -1.0
            h_lo, h_hi = list(lo), list(hi)
            for i in range(3):
                if i != k:
                    h_lo[i], h_hi[i] = (
                        base[i] - (radius - thickness),
                        base[i] + (radius - thickness),
                    )
            ends = sorted(
                (base[k] + sign * floor_wall, base[k] + sign * (radius - thickness))
            )
            h_lo[k], h_hi[k] = ends
        else:
            h_lo = [(lo[i] + hi[i]) / 2 - (radius - thickness) for i in range(3)]
            h_hi = [(lo[i] + hi[i]) / 2 + (radius - thickness) for i in range(3)]
        layout.hollows[key] = Hollow(item.id, key[1], shell.id, walls, open_faces,
                                     (h_lo[0], h_lo[1], h_lo[2]), (h_hi[0], h_hi[1], h_hi[2]))  # fmt: skip
        return


ENTRY = Sphere()
