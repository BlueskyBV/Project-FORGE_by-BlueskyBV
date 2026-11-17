"""Where the judge places a block: its entry in the ``place`` registry (its branches moved from ``place.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

from collections.abc import Mapping

from forge_spec.draft import Item

from forge_checks.items.place.protocol import Edges, PlaceKind
from forge_checks.outlines import TOL, Outline
from forge_checks.place import (
    _INDEX,
    DIRECTIONS,
    FLAT_AXES,
    Face,
    FlatFace,
    Hollow,
    Material,
    PlaceError,
    Solid,
    Vec,
    _box_body,
    _box_edges,
    _in_plane,
    _Layout,
    _mm,
    _walls,
    opposite,
)


class Block(PlaceKind):
    key = "block"

    leans = True

    def turnable(self, item: Item) -> bool:
        return True

    def footprint(
        self, item: Item, diameters: Mapping[str, float], axes: tuple[str, str]
    ) -> Outline:
        return Outline.rect(_mm(item, "length") / 2, _mm(item, "width") / 2)

    def body(self, item: Item, layout: _Layout, key: tuple[str, int], host: tuple[str, int, str] | None,
             point: Vec, up: str, axes: tuple[str, str], under: tuple[tuple[Outline, ...], Material] | None,
             faces: dict[str, Face]) -> tuple[Vec, Vec]:  # fmt: skip
        a1, a2 = axes
        sizes = {a1: _mm(item, "length"), a2: _mm(item, "width")}
        height = _mm(item, "height")
        return _box_body(item, point, up, sizes, height, under, faces)

    def edges(self, which: str, up: str) -> Edges:
        return _box_edges(which, up, True)

    def openable(self, item: Item) -> set[str]:
        return set(DIRECTIONS)

    def hollow(self, item: Item, layout: _Layout, key: tuple[str, int], base: Vec, up: str, lo: Vec, hi: Vec,
               shell: Item, thickness: float, floor: float | None, open_faces: frozenset[str]) -> None:  # fmt: skip
        faces = layout.faces[key]
        walls = _walls(DIRECTIONS, shell, open_faces, floor, thickness)
        h_lo = [lo[i] + walls.get("-" + "xyz"[i], 0.0) for i in range(3)]
        h_hi = [hi[i] - walls.get("+" + "xyz"[i], 0.0) for i in range(3)]
        if any(h_hi[i] - h_lo[i] <= TOL for i in range(3)):
            raise PlaceError(shell.id, f"its walls leave no hollow inside {item.id}")
        for d in DIRECTIONS:
            face = faces.get(d)
            if isinstance(face, FlatFace) and d in walls:
                faces[d] = FlatFace(
                    d,
                    face.centre,
                    face.normal,
                    face.axes,
                    face.outline,
                    Solid(walls[d]),
                )
            if d in open_faces:
                layout.close(
                    key,
                    f"inner {d}",
                    f"{shell.id} leaves its {d} open: it has no wall there",
                )
                continue
            k = _INDEX[d[1]]
            plane = FLAT_AXES[d[1]]
            centre = [(h_lo[i] + h_hi[i]) / 2 for i in range(3)]
            centre[k] = h_hi[k] if d[0] == "+" else h_lo[k]
            c = (centre[0], centre[1], centre[2])
            half = ((h_hi[_INDEX[plane[0]]] - h_lo[_INDEX[plane[0]]]) / 2,
                    (h_hi[_INDEX[plane[1]]] - h_lo[_INDEX[plane[1]]]) / 2)  # fmt: skip
            faces[f"inner {d}"] = FlatFace(f"inner {d}", c, opposite(d), plane, Outline.rect(*half, _in_plane(c, plane)),
                                           Solid(walls[d]))  # fmt: skip
        layout.hollows[key] = Hollow(item.id, key[1], shell.id, walls, open_faces,
                                     (h_lo[0], h_lo[1], h_lo[2]), (h_hi[0], h_hi[1], h_hi[2]))  # fmt: skip
        return


ENTRY = Block()
