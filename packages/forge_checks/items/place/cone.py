"""Where the judge places a cone: its entry in the ``place`` registry (its branches moved from ``place.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

from forge_numeric import scalar as fs
from forge_spec.draft import Item

from forge_checks.items.place.protocol import Edges, PlaceKind
from forge_checks.outlines import TOL, Outline
from forge_checks.place import (
    _INDEX,
    Face,
    FlatFace,
    Hollow,
    Material,
    PlaceError,
    RoundCone,
    Solid,
    Vec,
    _add,
    _Layout,
    _mm,
    _rod_body,
    _walls,
    unit,
)


class Cone(PlaceKind):
    key = "cone"

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
        return Outline.disc(_mm(item, "base_diameter") / 2)

    def body(self, item: Item, layout: _Layout, key: tuple[str, int], host: tuple[str, int, str] | None,
             point: Vec, up: str, axes: tuple[str, str], under: tuple[tuple[Outline, ...], Material] | None,
             faces: dict[str, Face]) -> tuple[Vec, Vec]:  # fmt: skip
        length = _mm(item, "length")
        base, top_r = (
            _mm(item, "base_diameter") / 2,
            _mm(item, "top_diameter", zero=True) / 2,
        )
        inner = 0.0
        found = _rod_body(item, layout, key, point, up, axes, under, faces, length, base, top_r, inner, tapered=True)
        # Its tapered side takes a hole, a boss or a post, round it and along it (item 3b's third step).
        forward = up[0] == "+"
        start = point if forward else _add(point, unit(up), length)
        faces["side"] = RoundCone("side", up[1], start, length, base if forward else top_r, top_r if forward else base,
                                  None if host is None else ("start" if forward else "end"))  # fmt: skip
        return found

    def openable(self, item: Item) -> set[str]:
        return {"-end"} if _mm(item, "top_diameter", zero=True) <= TOL else {"+end", "-end"}

    def hollow(self, item: Item, layout: _Layout, key: tuple[str, int], base: Vec, up: str, lo: Vec, hi: Vec,
               shell: Item, thickness: float, floor: float | None, open_faces: frozenset[str]) -> None:  # fmt: skip
        """A hollowed cone (shell.md, "cone"): the hollow a cone ``thickness`` in from the side square to it, its ends'
        walls in from its ends; where the cone comes to a point, so does the hollow. Its ends keep their walls under
        them; its side, an open end's rim and the inside take nothing yet."""
        faces = layout.faces[key]
        r0, r1, length = _mm(item, "base_diameter") / 2, _mm(item, "top_diameter", zero=True) / 2, _mm(item, "length")
        if r1 <= TOL:
            raise PlaceError(shell.id, f"Forge hollows a cone with a flat top, not yet {item.id}, which comes to a point")
        walls = _walls(("+end", "-end") if r1 > TOL else ("-end",), shell, open_faces, floor, thickness)
        plus, minus = walls.get("+end", 0.0), walls.get("-end", 0.0)
        slant = fs.hypot(length, r1 - r0) / length

        def inside(s: float) -> float:  # the hollow's radius s along the axis from the -end
            return r0 + (r1 - r0) * s / length - thickness * slant

        top = length - plus if r1 > TOL else length * (1.0 - thickness * slant / r0)
        if top - minus <= TOL or inside(minus) <= TOL or (r1 > TOL and inside(top) <= TOL):
            raise PlaceError(shell.id, f"its walls leave no hollow inside {item.id}")
        for name, wall in (("+end", plus), ("-end", minus)):
            face = faces.get(name)
            if isinstance(face, FlatFace):
                faces[name] = FlatFace(name, face.centre, face.normal, face.axes, face.outline, Solid(wall))
        layout.close(key, "side", f"{shell.id} hollows it: Forge doesn't place on a hollow cone's side yet")
        k = _INDEX[up[1]]
        u = unit(up)
        widest = max(inside(minus), inside(top), 0.0)
        near, far = _add(base, u, minus), _add(base, u, top)
        h_lo, h_hi = list(lo), list(hi)
        for i in range(3):
            if i != k:
                middle = (lo[i] + hi[i]) / 2
                h_lo[i], h_hi[i] = middle - widest, middle + widest
        h_lo[k], h_hi[k] = min(near[k], far[k]), max(near[k], far[k])
        layout.hollows[key] = Hollow(item.id, key[1], shell.id, {**walls, "side": thickness}, open_faces,
                                     (h_lo[0], h_lo[1], h_lo[2]), (h_hi[0], h_hi[1], h_hi[2]))  # fmt: skip


ENTRY = Cone()
