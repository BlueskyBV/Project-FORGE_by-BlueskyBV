"""Where the judge places a cylinder: its entry in the ``place`` registry (its branches moved from ``place.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

from forge_spec.draft import Item

from forge_checks.items.place.protocol import Edges, PlaceKind
from forge_checks.outlines import TOL, Outline
from forge_checks.place import (
    _INDEX,
    FLAT_AXES,
    Face,
    FlatFace,
    Hollow,
    Material,
    PlaceError,
    RoundSide,
    Solid,
    Vec,
    _add,
    _in_plane,
    _Layout,
    _mm,
    _rod_body,
    _walls,
    opposite,
    unit,
)


class Cylinder(PlaceKind):
    key = "cylinder"

    leans = True
    rise = "length"

    axial = True
    joined_by_end = True
    both_ends = True
    rims: ClassVar[Mapping[str, Edges]] = {
        "top": (("+end", "side"),),
        "bottom": (("-end", "side"),),
    }

    def footprint(
        self, item: Item, diameters: Mapping[str, float], axes: tuple[str, str]
    ) -> Outline:
        return Outline.disc(_mm(item, "diameter") / 2)

    def body(self, item: Item, layout: _Layout, key: tuple[str, int], host: tuple[str, int, str] | None,
             point: Vec, up: str, axes: tuple[str, str], under: tuple[tuple[Outline, ...], Material] | None,
             faces: dict[str, Face]) -> tuple[Vec, Vec]:  # fmt: skip
        length = _mm(item, "length")
        base = _mm(item, "diameter") / 2
        top_r = base
        inner = 0.0
        return _rod_body(
            item, layout, key, point, up, axes, under, faces, length, base, top_r, inner
        )

    def openable(self, item: Item) -> set[str]:
        return {"+end", "-end"}

    def hollow(self, item: Item, layout: _Layout, key: tuple[str, int], base: Vec, up: str, lo: Vec, hi: Vec,
               shell: Item, thickness: float, floor: float | None, open_faces: frozenset[str]) -> None:  # fmt: skip
        faces = layout.faces[key]
        walls = _walls(("+end", "-end"), shell, open_faces, floor, thickness)
        side = faces["side"]
        assert isinstance(side, RoundSide)
        radius, length = side.radius, side.length
        inner = radius - thickness
        plus, minus = walls.get("+end", 0.0), walls.get("-end", 0.0)
        if inner <= TOL or length - plus - minus <= TOL:
            raise PlaceError(shell.id, f"its walls leave no hollow inside {item.id}")
        u = unit(up)
        for name, wall in (("+end", plus), ("-end", minus)):
            face = faces.get(name)
            if isinstance(face, FlatFace):
                faces[name] = FlatFace(
                    name, face.centre, face.normal, face.axes, face.outline, Solid(wall)
                )
        faces["side"] = RoundSide(
            "side", side.axis, side.start, side.length, radius, True, inner
        )
        near, far = _add(base, u, minus), _add(base, u, length - plus)
        plane = FLAT_AXES[up[1]]
        for name, wall, at, normal in (
            ("inner +end", plus, far, opposite(up)),
            ("inner -end", minus, near, up),
        ):
            if wall == 0.0:
                layout.close(
                    key,
                    name,
                    f"{shell.id} leaves its {name[6:]} open: it has no wall there",
                )
                continue
            faces[name] = FlatFace(
                name,
                at,
                normal,
                plane,
                Outline.disc(inner, _in_plane(at, plane)),
                Solid(wall),
            )
        start = near if up[0] == "+" else far
        faces["inner side"] = RoundSide(
            "inner side", up[1], start, length - plus - minus, inner, False, radius
        )
        k = _INDEX[up[1]]
        h_lo, h_hi = list(lo), list(hi)
        for i in range(3):
            if i != k:
                middle = (lo[i] + hi[i]) / 2
                h_lo[i], h_hi[i] = middle - inner, middle + inner
        h_lo[k], h_hi[k] = min(near[k], far[k]), max(near[k], far[k])
        layout.hollows[key] = Hollow(item.id, key[1], shell.id, {**walls, "side": thickness}, open_faces,
                                     (h_lo[0], h_lo[1], h_lo[2]), (h_hi[0], h_hi[1], h_hi[2]))  # fmt: skip


ENTRY = Cylinder()
