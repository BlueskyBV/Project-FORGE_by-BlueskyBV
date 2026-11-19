"""What the check compiler holds for a pocket: its entry in the ``compile`` registry (its branches moved from ``compiler.py`` at stage 4b.0b's step 3)."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from forge_numeric import scalar as fs
from forge_numeric import vector as fv
from forge_spec.draft import Item
from forge_spec.ends import ThroughAll, ThroughEverything, UpToFace, end_of

from forge_checks.classes import RADIUS, general
from forge_checks.convex import convex_pieces
from forge_checks.items.compile._common import (
    _RAYS,
    _STRAIGHT,
    _mm,
    _t,
    _v,
    main_face_refs,
    side_end,
)
from forge_checks.items.compile.protocol import CompileKind
from forge_checks.kinds.depth import Open
from forge_checks.kinds.position import Centre, Corner, Middle, Position, Ref, RoundEdge
from forge_checks.kinds.size import Between
from forge_checks.kinds.surfaces import Plane, Round
from forge_checks.outlines import Arc as OutlineArc
from forge_checks.outlines import Outline, Segment
from forge_checks.place import Copy, section_of

if TYPE_CHECKING:
    from forge_checks.items.compile._context import CompileContext


class Pocket(CompileKind):
    key = "pocket"

    def checks(self, c: CompileContext, item: Item) -> None:
        shape = c._choice_value(item, "shape")
        if shape == "profile":
            _profile_checks(c, item)
            return
        for copy in c.copies(item):
            assert copy.axes is not None and copy.span is not None
            n = _v(copy.direction)
            depth, side = copy.span[1], side_end(copy)
            if shape == "circle":
                r = _mm(item.get("diameter")) / 2
                c.check(item, "diameter", "diameter", 2 * r, c.tol(item.get("diameter")),
                           Round(copy.point, _t(-n), r, 0.0, side, True), copy.index)  # fmt: skip
                c.size(item, r)
                c._cut_depth(item, copy, r, r, depth)
                continue
            if shape == "hexagon":
                # Across its flats between each pair of opposite walls; its floor within the circle in it.
                h = _mm(item.get("across_flats")) / 2
                walls = _hexagon_walls(c, copy, h)
                for j in range(3):
                    pair = Between(walls[j], walls[j + 3], _t(-_v(walls[j].normal)))
                    c.check(item, "across_flats", "size", 2 * h, c.tol(item.get("across_flats")), pair,
                            copy.index * 3 + j)  # fmt: skip
                c.size(item, h)
                c._cut_depth(item, copy, h, h, depth)
                continue
            sizes = {"length": copy.axes[0], "width": copy.axes[1]}
            half = {name: _mm(item.get(name)) / 2 for name in sizes}
            corner = (
                _mm(item.get("corner_radius"))
                if item.get("corner_radius") is not None
                else 0.0
            )
            for name, axis in sizes.items():
                a = _v(c.along(copy, axis))
                other_axis = copy.axes[1] if axis == copy.axes[0] else copy.axes[0]
                other = half["width" if name == "length" else "length"]
                ends = c._round_ends(item, copy, axis)
                span: Between | Position
                if ends is None:
                    across = _v(c.along(copy, other_axis))
                    walls = [
                        c.cut_wall(copy, s * a, half[name], across, other - corner)
                        for s in (1, -1)
                    ]
                    span = Between(walls[0], walls[1], _t(a))
                else:
                    # Ends rounded (all but) all across by its corners: from one's fitted arc to the other's.
                    span = Position(
                        _t(a), RoundEdge(ends[0], -1), RoundEdge(ends[1], 1)
                    )
                c.check(item, name, "size", 2 * half[name], c.tol(item.get(name)), span, copy.index)  # fmt: skip
                c.size(item, half[name])
            if corner > 0:
                e1, e2 = (
                    _v(c.along(copy, copy.axes[0])),
                    _v(c.along(copy, copy.axes[1])),
                )
                for k, (s1, s2) in enumerate(((1, 1), (-1, 1), (-1, -1), (1, -1))):
                    centre = (
                        _v(copy.point)
                        + s1 * (half["length"] - corner) * e1
                        + s2 * (half["width"] - corner) * e2
                    )
                    c.check(item, "corner_radius", "corner", corner, c.tol(item.get("corner_radius"), RADIUS),
                               Round(_t(centre), _t(-n), corner, 0.0, side, True), copy.index * 4 + k)  # fmt: skip
                c.size(item, corner)
            c._cut_depth(item, copy, min(half.values()), min(half.values()), depth,
                            (copy.axes[0], half["length"], half["width"]))  # fmt: skip
        c._choice(item, "shape")
        c._cut_fields(item)

    def main(self, c: CompileContext, item: Item, copy: Copy) -> Ref | None:
        if c._choice_value(item, "shape") != "circle":
            return None
        assert copy.span is not None
        r = _mm(item.get("diameter")) / 2
        return Centre(
            Round(copy.point, _t(-_v(copy.direction)), r, 0.0, side_end(copy), True)
        )

    def sides(
        self, c: CompileContext, item: Item, copy: Copy, axis: str
    ) -> tuple[Plane, Plane] | None:
        if copy.span is None or copy.axes is None:
            return None
        if c._choice_value(item, "shape") in ("circle", "profile"):
            return None
        if c._choice_value(item, "shape") == "hexagon":  # its flats square to the face's second axis; none to the first
            if axis != copy.axes[1]:
                return None
            walls = _hexagon_walls(c, copy, _mm(item.get("across_flats")) / 2)
            return walls[1], walls[4]
        if c._round_ends(item, copy, axis) is not None:
            return None
        a = _v(c.along(copy, axis))
        across = _v(
            c.along(copy, (copy.axes[1] if axis == copy.axes[0] else copy.axes[0]))
        )
        first = axis == copy.axes[0]
        half = _mm(item.get("length" if first else "width")) / 2
        other = _mm(item.get("width" if first else "length")) / 2
        corner = item.get("corner_radius")
        other -= _mm(corner) if corner is not None else 0.0
        return (
            c.cut_wall(copy, a, half, across, other),
            c.cut_wall(copy, -a, half, across, other),
        )

    def round_ends(
        self, c: CompileContext, item: Item, copy: Copy, axis: str
    ) -> tuple[Round, Round] | None:
        """A rectangular pocket's ends where its corners are rounded to (about) half its size across them: an end's corner on the other axis's + side."""
        if copy.span is None:
            return None
        assert copy.axes is not None
        n = _v(copy.direction)
        a = _v(c.along(copy, axis))
        corner = item.get("corner_radius")
        if c._choice_value(item, "shape") == "circle" or corner is None:
            return None
        r = _mm(corner)
        first = axis == copy.axes[0]
        half = _mm(item.get("length" if first else "width")) / 2
        other = _mm(item.get("width" if first else "length")) / 2
        if r <= 0 or 2 * (other - r) >= _STRAIGHT:
            return None
        # Each end's corner on the +other side (both reach the end alike).
        b = _v(c.along(copy, (copy.axes[1] if first else copy.axes[0])))
        ends = [Round(_t(_v(copy.point) + s * (half - r) * a + (other - r) * b), _t(-n), r, 0.0, side_end(copy),
                      True) for s in (-1, 1)]  # fmt: skip
        return ends[0], ends[1]

    def centre_ref(self, c: CompileContext, item: Item, copy: Copy, axis: str) -> Ref | None:
        corners = _hexagon_corners(c, item, copy, axis)
        if corners is not None:  # along its corners' axis: half way between them
            return Middle(*corners)
        return super().centre_ref(c, item, copy, axis)

    def edge_ref(self, c: CompileContext, item: Item, copy: Copy, axis: str, sign: float) -> Ref | None:
        corners = _hexagon_corners(c, item, copy, axis)
        if corners is not None:  # along its corners' axis: the corner on that side
            return corners[0] if sign > 0 else corners[1]
        return super().edge_ref(c, item, copy, axis, sign)

    def placed_by_its_outline(self, c: CompileContext, item: Item) -> bool:
        return c._choice_value(item, "shape") == "profile"

    def own_surface(self, c: CompileContext, item: Item, copy: Copy) -> Round | Plane | None:
        if copy.span is None:
            return None
        if c._choice_value(item, "shape") == "profile":
            return _profile_wall(c, item, copy)
        if c._choice_value(item, "shape") != "hexagon":
            return None
        return _hexagon_walls(c, copy, _mm(item.get("across_flats")) / 2)[1]  # its flat on its second axis' + side

    def face_refs(
        self, c: CompileContext, owner: Item, copy: Copy, face: str
    ) -> tuple[Ref, Ref, Ref] | None:
        if c._choice_value(owner, "shape") != "circle":
            return None
        return main_face_refs(c, owner, copy)


def _hexagon_walls(c: CompileContext, copy: Copy, h: float) -> list[Plane]:
    """A hexagonal pocket's six walls, ``h`` (half across its flats) from its centre, each facing back into it: their
    ways out at 30, 90, ..., 330 degrees from its first axis towards its second (two corners on its first axis,
    pocket.md), each a rectangle along its straight run but a quarter of it at each end, where its neighbours meet it."""
    assert copy.axes is not None
    e1, e2 = _v(c.along(copy, copy.axes[0])), _v(c.along(copy, copy.axes[1]))
    root = math.sqrt(3.0)
    # (cos, sin) of each way out, exactly: 30 degrees is (sqrt(3)/2, 1/2), 90 is (0, 1), and so on round.
    ways = [(root / 2, 0.5), (0.0, 1.0), (-root / 2, 0.5), (-root / 2, -0.5), (0.0, -1.0), (root / 2, -0.5)]
    half = h / root / 2  # half of a quarter-trimmed side's run: each side is 2h / sqrt(3) long
    return [c.cut_wall(copy, cw * e1 + sw * e2, h, -sw * e1 + cw * e2, half) for cw, sw in ways]


def _hexagon_corners(c: CompileContext, item: Item, copy: Copy, axis: str) -> tuple[Corner, Corner] | None:
    """A hexagonal pocket's two corners on its first axis, the + one first, where ``axis`` is that axis; else None."""
    if c._choice_value(item, "shape") != "hexagon" or copy.axes is None or axis != copy.axes[0]:
        return None
    walls = _hexagon_walls(c, copy, _mm(item.get("across_flats")) / 2)
    return Corner(walls[0], walls[5]), Corner(walls[2], walls[3])


def _profile_checks(c: CompileContext, item: Item) -> None:
    """A pocket of its own outline (pocket.md): its outline, and where it is, held by face accounting, as an
    extrusion's is (docs/V2-stage4.md, 6.6); its depth, from the face round its mouth to its floor over the box round
    its outline, or right through, open along its axis round a point well within it."""
    section = section_of(item)
    c._profile(item)
    inside = _well_within(section)
    reach = max(fs.hypot(p[0], p[1]) for side in section.pieces() for p in side.ends()) + max(section.half)
    for copy in c.copies(item):
        assert copy.axes is not None and copy.span is not None
        first, second = (_v(c.along(copy, a)) for a in copy.axes)
        n = _v(copy.direction)
        depth = copy.span[1]
        if isinstance(end_of(item), (ThroughAll, ThroughEverything)) or inside is None:
            if inside is None:
                c.skip(item, "depth", "no point is well within its outline: face accounting holds it",
                       "face accounting")  # fmt: skip
                continue
            (x, y), r = inside
            mouth = _v(copy.point) + x * first + y * second
            c.check(item, "depth", "depth", depth, None, Open(_t(mouth), _t(-n), depth, r), copy.index, _RAYS)
            continue
        (m1, m2), (h1, h2) = section.centre, section.half
        floor = Plane(_t(_v(copy.point) + m1 * first + m2 * second - depth * n), copy.direction, min(h1, h2))
        end = end_of(item)
        tolerance = general(depth) if isinstance(end, UpToFace) else c.tol(item.get("depth"))
        c._floor(item, "depth", copy, floor, depth, tolerance, reach)
    c._choice(item, "shape")
    c._cut_fields(item)


def _well_within(section: Outline) -> tuple[tuple[float, float], float] | None:
    """A point well within an outline and how far round it is all within: a convex piece's middle, half as far as
    the outline is from it; None where none is within it."""
    best: tuple[tuple[float, float], float] | None = None
    for polygon in convex_pieces(section).polygons:
        p = (sum(q[0] for q in polygon) / len(polygon), sum(q[1] for q in polygon) / len(polygon))
        if not section.contains(p, tol=0.0):
            continue
        room = min(side.distance(p) for side in section.pieces()) / 2
        if room > 0 and (best is None or room > best[1]):
            best = (p, room)
    return best


def _profile_wall(c: CompileContext, item: Item, copy: Copy) -> Plane | Round | None:
    """A wall of a pocket of its own outline, to count its copies by: its first straight side's, facing back into it,
    or, where it has none, its first arc's."""
    assert copy.axes is not None and copy.span is not None
    section = section_of(item)
    first, second = (_v(c.along(copy, a)) for a in copy.axes)
    n = _v(copy.direction)
    for side in section.pieces():
        if isinstance(side, Segment):
            (ax, ay), (bx, by) = side.a, side.b
            length = fs.hypot(bx - ax, by - ay)
            dx, dy = (bx - ax) / length, (by - ay) / length
            mx, my = (ax + bx) / 2, (ay + by) / 2
            out = (dy, -dx) if not section.contains((mx + 1e-6 * dy, my - 1e-6 * dx), tol=0.0) else (-dy, dx)
            way = out[0] * first + out[1] * second
            along = dx * first + dy * second
            at = float(fv.matmul(mx * first + my * second, way))
            return c.cut_wall(copy, way, at, along, length / 4)
    arc = next((side for side in section.pieces() if isinstance(side, OutlineArc)), None)
    if arc is None:
        return None
    centre = _v(copy.point) + arc.centre[0] * first + arc.centre[1] * second
    return Round(_t(centre), _t(-n), arc.radius, 0.0, side_end(copy), True)


ENTRY = Pocket()
