"""What the spec checks of several kinds share (the ``checks`` role's leaf: it imports neither the kinds' modules, but for the registry when asked, nor ``checks.py``).

Moved from ``checks.py`` at stage 4b.0b's step 3, unchanged but for each
kind's branch, which is its own module's, and what another kind publishes,
asked of the registry.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import replace
from typing import Protocol

from forge_spec.draft import EdgeSet, Faces, Item, On, PartSpec, Place
from forge_spec.geometry import (
    EPS,
    ConeFace,
    FlatFace,
    SideFace,
    bbox,
    disc,
    shapes_overlap,
)
from forge_spec.outline import Line, Shape
from forge_spec.placement import (
    Layout,
    _outline,
    edges_of,
    footing_values,
    height_of,
    mm,
)
from forge_spec.problems import pointer
from forge_spec.schema import KINDS
from forge_spec.values import Value


class Collect(Protocol):
    """What a kind's check reports through: the spec checks' collector."""

    def fault(self, at: str, message: str) -> None: ...

    def add(self, kind: str, at: str, message: str) -> None: ...

    def problem(self, kind: str, at: str, message: str, *values: object) -> None: ...


def size_of(item: Item, name: str) -> float | None:
    value = item.get(name)
    return mm(value) if isinstance(value, Value) else None


def material_of_cut(cut: Item, layout: Layout) -> float | None:
    """The material under a cut's first copy's point, on a flat face: how deep a cut through it goes there."""
    copies = layout.instances.get(cut.id) or []
    if not copies or copies[0].host is None:
        return None
    host_item, host_index, face_name = copies[0].host
    face = layout.faces.get((host_item, host_index), {}).get(face_name)
    if not isinstance(face, FlatFace):
        return None
    i1, i2 = ("xyz".index(a) for a in face.axes)
    point = copies[0].origin
    return face.most_material_under((disc(0.0),), (point[i1] - face.centre[i1], point[i2] - face.centre[i2]))


def rim_rounded(
    target: Item, which: str, open_faces: tuple[str, ...], layout: Layout
) -> bool:
    """Whether the edges rounded include the rim of a face the shell leaves open.

    An edge borders an open face when either face it lies between is open
    (:func:`forge_spec.placement.edges_of`, from the way the body really
    stands). Such an edge is the rim's: its outside and inside edges are both
    rounded, after the hollow (docs/definitions/frame.md).
    """
    copies = layout.instances.get(target.id) or []
    normal = copies[0].normal if copies else (0.0, 0.0, 1.0)
    k = max(range(3), key=lambda i: abs(normal[i]))
    up = ("+" if normal[k] > 0 else "-") + "xyz"[k]
    return any(set(open_faces) & set(pair) for pair in edges_of(target.kind, which, up))


def joint_room(spec: PartSpec, target: Item, meets: str | None, layout: Layout, at: str,
                c: Collect) -> tuple[float, list[object]] | None:  # fmt: skip
    """How big a rounding can fill the inside corner where two items meet, and what binds it.

    One must stand on the other. Where the standing item sits inside the
    face, the rounding runs up its side and out over the face: it can be no
    bigger than the item's height or the face left beyond it. Where the item
    hangs over the face's edge, the corner is under the overhang: no bigger
    than the overhang or the host's own side below the edge. Flush sides have no
    corner. The rounding must fit all along the joint, so the smallest of
    these bounds it.
    """
    other = spec.item(meets) if meets is not None else None
    if other is None:
        c.fault(at + pointer("edges", "where_meets"), f"no item {meets!r}")
        return None
    for standing, host in ((target, other), (other, target)):
        on = standing.get("on")
        if isinstance(on, On) and on.item == host.id:
            break
    else:
        c.fault(at + pointer("edges", "where_meets"),
                f"{target.id} and {other.id} don't meet: a joint is where one stands on the other")  # fmt: skip
        return None
    height = height_of(standing)
    if height is None:
        return None
    rising: list[object] = [standing.get(height[1])]
    best: tuple[float, list[object]] | None = None
    flush: FlatFace | None = None
    for copy in layout.instances.get(standing.id, ()):
        if copy.host is None or copy.lo is None or copy.hi is None:
            continue
        face = layout.faces.get((copy.host[0], copy.host[1]), {}).get(copy.host[2])
        if not isinstance(face, FlatFace):
            best = smaller(
                best, (height[0], rising)
            )  # on a round side: its height bounds it
            continue
        flush = face
        for k, axis in enumerate(face.axes):
            i = "xyz".index(axis)
            edges = (face.centre[i] - face.half[k], face.centre[i] + face.half[k])
            reach = layout.values_of(face.axis_sources[k]) + footing_values(
                standing, face.axes, k
            )
            for sign, gap in (
                ("-", copy.lo[i] - edges[0]),
                ("+", edges[1] - copy.hi[i]),
            ):
                if gap > EPS:
                    best = smaller(best, (gap, reach))
                    best = smaller(best, (height[0], rising))
                elif gap < -EPS:
                    best = smaller(best, (-gap, reach))
                    below = side_below(
                        layout, (copy.host[0], copy.host[1]), face, sign + axis
                    )
                    if below is not None:
                        best = smaller(best, below)
    if best is None and flush is not None:
        values = layout.values_of(flush.sources) + [
            v for k in (0, 1) for v in footing_values(standing, flush.axes, k)
        ]
        c.problem("cant", at + pointer("edges"),
                 f"{standing.id} is flush with every edge of the {on.face} face of {host.id}: "
                 "where they meet there is no inside corner to round", *values)  # fmt: skip
    return best


def side_below(
    layout: Layout, host: tuple[str, int], face: FlatFace, side_name: str
) -> tuple[float, list[object]] | None:
    """How far the host's side runs down from the edge of ``face`` an item hangs over, and what sets it.

    Under an overhang the rounding runs down the host's own side, so the
    side's height bounds it: a post's height, not the plate's under it.
    """
    faces = layout.faces.get(host, {})
    normal_axis = face.normal[1]
    side = faces.get(side_name) or faces.get("side")
    if isinstance(side, FlatFace) and normal_axis in side.axes:
        k = side.axes.index(normal_axis)
        return 2 * side.half[k], layout.values_of(side.axis_sources[k])
    if isinstance(side, SideFace) and side.axis == normal_axis:
        return side.length, layout.values_of(side.length_sources)
    return None


def smaller(
    best: tuple[float, list[object]] | None, other: tuple[float, list[object]]
) -> tuple[float, list[object]]:
    return other if best is None or other[0] < best[0] else best


def check_rounding(
    spec: PartSpec, item: Item, at: str, layout: Layout, c: Collect, size_name: str
) -> None:
    """A fillet's or a chamfer's size, against the edges it rounds: ``size_name`` its own field (a radius, a size)."""
    from forge_spec.items.checks import SPEC_CHECKS

    edges = item.get("edges")
    if not isinstance(edges, EdgeSet):
        return
    target = spec.item(edges.of)
    if target is None:
        c.fault(at + pointer("edges", "of"), f"no item {edges.of!r} to round")
        return
    allowed = KINDS[target.kind].edges
    if edges.which not in allowed:
        c.fault(at + pointer("edges", "which"),
                f"a {target.kind}'s edges are {list(allowed)}, not {edges.which!r}" if allowed
                else f"a {target.kind} has no edges to round")  # fmt: skip
        return
    missing = SPEC_CHECKS[target.kind].edges_missing(target, edges.which, layout)
    if missing is not None:
        kind, why = missing
        c.problem(
            kind,
            at + pointer("edges", "which"),
            why,
            *(v for v in (item.get("radius"), item.get("size")) if v),
        )
        return
    size_value = item.get(size_name)
    joint: tuple[float, list[object]] | None = None
    if edges.which == "joint":
        found = joint_room(spec, target, edges.where_meets, layout, at, c)
        if found is None:
            return
        joint = found
    if not isinstance(size_value, Value):
        return
    size = mm(size_value)
    if joint is not None:
        if size > joint[0] + 1e-9:
            c.problem("cant", at + pointer(size_name),
                     f"a {size:g} mm {item.kind} doesn't fit where {target.id} meets {edges.where_meets} "
                     f"(at most {joint[0]:g} mm)", size_value, *joint[1])  # fmt: skip
        else:
            joint_reached_into(spec, item, target, edges, size, layout, at, c)
        return
    limit = (
        None
        if edges.which == "joint"
        else SPEC_CHECKS[target.kind].rounding_limit(target, edges.which, layout)
    )
    names = ("length", "width", "height", "diameter", "outer_diameter", "inner_diameter",
             "base_diameter", "top_diameter", "thickness", "depth", "corner_radius")  # fmt: skip
    dims = [v for v in (target.get(n) for n in names) if isinstance(v, Value)]

    if limit is not None and size > limit + 1e-9:
        c.problem("cant", at + pointer(size_name),
                 f"a {size:g} mm {item.kind} doesn't fit on {target.id}'s {edges.which} edges "
                 f"(at most {limit:g} mm)", size_value, *dims)  # fmt: skip
        return
    if earlier_roundings(spec, item, target, edges, size, size_name, at, c):
        return
    reached_into(spec, item, target, edges, size, size_name == "size", layout, at, c)
    after_thread(spec, item, target, edges, layout, at, c)
    shell = layout.shells.get(target.id)
    if shell is not None:
        thickness = shell.get("thickness")
        opened = shell.get("open")
        open_faces = opened.faces if isinstance(opened, Faces) else ()
        # A rim's outside and inside edges are both rounded: two in the wall's thickness. Each half of it, they
        # meet in the middle, rounding the rim right over or bevelling it to a ridge: not made yet (OpenCascade
        # can't make the two meet).
        wall = mm(thickness) if isinstance(thickness, Value) else None
        half = None if wall is None else wall / 2
        if half is not None and rim_rounded(target, edges.which, open_faces, layout) and size > half - 1e-9:
            whole = size <= half + 1e-9
            c.problem("question", at + pointer(size_name),
                     f"a {size:g} mm {item.kind} on both edges of the {wall:g} mm wall at the open rim of "
                     + (f"{target.id} {'rounds' if size_name == 'radius' else 'bevels'} it right over, the two "
                        f"meeting in its middle, which Forge doesn't make yet (each less than {half:g} mm leaves a "
                        "flat between them): " if whole else
                        f"{target.id} doesn't fit (at most {half:g} mm): ")
                     + "which edges get it, or how big may the rim's be?", size_value, thickness)  # fmt: skip


def _rounded_face(face: FlatFace, name: str, pairs: list[tuple[str, str]], size: float,
                  bevel: bool) -> tuple[FlatFace, tuple[float, float]] | None:  # fmt: skip
    """A body's flat face as a rounding (a bevel) of its edges leaves it, made after what is on it, and where its old
    centre is from the new one; None where it takes none of the face. A rectangle's side along a rounded edge is
    ``size`` further in, a corner where a rounded edge square to it ends is rounded (bevelled) by ``size``; a disc's
    rim, ``size`` in. (Faces at right angles: a block's, a cylinder's ends and its side.)"""
    if face.shape == "disc":
        if not any(name in pair for pair in pairs):
            return None
        r = face.half[0] - size
        return (replace(face, half=(r, r)), (0.0, 0.0)) if r > EPS else None
    if face.shape != "rect" or any(face.corners):
        return None
    a1, a2 = face.axes
    lo, hi = [-face.half[0], -face.half[1]], [face.half[0], face.half[1]]
    corners: dict[tuple[int, int], float] = {}
    for a, b in pairs:
        if name in (a, b):  # along one of its sides: that side further in
            other = b if a == name else a
            if other[1] in (a1, a2):
                k = (a1, a2).index(other[1])
                if other[0] == "+":
                    hi[k] -= size
                else:
                    lo[k] += size
        elif {a[1], b[1]} == {a1, a2}:  # square to it, at a corner
            first, second = (a, b) if a[1] == a1 else (b, a)
            corners[(1 if first[0] == "+" else -1, 1 if second[0] == "+" else -1)] = size
    if hi[0] - lo[0] <= EPS or hi[1] - lo[1] <= EPS:
        return None
    middle = ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2)
    half = ((hi[0] - lo[0]) / 2, (hi[1] - lo[1]) / 2)
    if not corners and (lo[0], lo[1], hi[0], hi[1]) == (-face.half[0], -face.half[1], face.half[0], face.half[1]):
        return None
    quadrants = ((1, 1), (-1, 1), (-1, -1), (1, -1))
    if not bevel:
        radii = tuple(min(corners.get(q, 0.0), *half) for q in quadrants)
        return replace(face, half=half, corners=(radii[0], radii[1], radii[2], radii[3])), middle
    points: list[tuple[float, float]] = []
    for s1, s2 in quadrants:  # anticlockwise, each corner cut by its bevel's legs
        c1, c2 = s1 * half[0], s2 * half[1]
        cut = min(corners.get((s1, s2), 0.0), *half)
        if cut <= 0.0:
            points.append((c1, c2))
        elif s1 == s2:
            points += [(c1, c2 - s2 * cut), (c1 - s1 * cut, c2)]
        else:
            points += [(c1 - s1 * cut, c2), (c1, c2 - s2 * cut)]
    outline = Shape(tuple(Line(p, q) for p, q in zip(points, [*points[1:], points[0]], strict=True) if p != q))
    return replace(face, shape="profile", profile=outline, half=half), middle


def reached_into(spec: PartSpec, item: Item, target: Item, edges: EdgeSet, size: float, bevel: bool, layout: Layout,
                 at: str, c: Collect) -> None:  # fmt: skip
    """What is on a face a rounding (a bevel) of a body's edges takes some of, made before it: asked about.

    A rounding is made after what is on the faces either side of its edge
    (frame.md): where a hole's mouth, or what stands there, comes within its
    size of the edge, the ball rolling along the edge meets it, and the round
    isn't one (it runs into the hole, or cuts away what stands there).
    OpenCascade refuses to make most such roundings, and where it makes one
    the part is not what the definitions say. Asked, with the values that put
    it there: further in, or a smaller rounding. A block's faces, a
    cylinder's and a cone's: their ends and their sides.
    """
    from forge_spec.items.solve import SOLVE
    from forge_spec.placement import _covered, _footing, _place_values, turned_outline

    copies = layout.instances.get(target.id) or []
    for copy in copies:
        k = max(range(3), key=lambda i: abs(copy.normal[i]))
        rising = copy.normal[k] > 0  # its -end at the smaller coordinate along its axis
        pairs = edges_of(target.kind, edges.which, ("+" if rising else "-") + "xyz"[k])
        faces = layout.faces.get((target.id, copy.index), {})
        side = next((f for f in faces.values() if isinstance(f, ConeFace) and f.local is None), None)
        for name, face in faces.items():
            ends = [a if b == name else b for a, b in pairs if name in (a, b)]
            if isinstance(face, (SideFace, ConeFace)) and face.local is None and ends:
                if isinstance(face, SideFace) and not face.outward:
                    continue
                axis = "xyz".index(face.axis)
                low, high = face.start[axis], face.start[axis] + face.length
                for end in ends:
                    at_start = (end == "-end") == rising
                    band = _cone_band(face, at_start, size, bevel)[1] if isinstance(face, ConeFace) else size
                    low, high = (low + band, high) if at_start else (low, high - band)
                for other in spec.items:
                    for inst in layout.instances.get(other.id) or []:
                        if inst.host != (target.id, copy.index, name):
                            continue
                        if inst.lo is not None and inst.hi is not None:  # what stands round it: its box along it
                            first, last = inst.lo[axis], inst.hi[axis]
                        else:  # a cut: its outline along it (a cone's: along its slope, seen along its axis)
                            parts = _outline(other, layout, (face.reference[0], face.axis))
                            along = bbox(parts)[1] if parts else 0.0
                            if isinstance(face, ConeFace):
                                along *= face.lean[0]
                            first, last = inst.origin[axis] - along, inst.origin[axis] + along
                        if first < low - EPS or last > high + EPS:
                            where = other.get("place")
                            along_values = [p.distance for a, p in where.axes.items() if a == face.axis] if isinstance(
                                where, Place) else []  # fmt: skip
                            _asked(item, other, inst.index, target, name, size, bevel, at, c, along_values)  # not round it
                            break
                continue
            if not isinstance(face, FlatFace) or face.local is not None or face.turn != 0.0:
                continue
            band = size
            if side is not None and face.shape == "disc" and ends:  # a cone's end: as far in as the round meets it
                axis = "xyz".index(side.axis)
                band = _cone_band(side, abs(face.centre[axis] - side.start[axis]) < EPS, size, bevel)[0]
            found = _rounded_face(face, name, pairs, band, bevel)
            if found is None:
                continue
            rounded, middle = found
            for other in spec.items:
                for inst in layout.instances.get(other.id) or []:
                    if inst.host != (target.id, copy.index, name):
                        continue
                    footing = _footing(other)
                    turned = turned_outline(other, layout, face.axes)
                    footprint = turned if turned is not None else footing if footing is not None else _covered(
                        other, layout, face)  # fmt: skip
                    if not footprint:
                        continue
                    p1, p2 = face.frame.on(inst.origin)
                    cut = SOLVE[other.kind].cut
                    if face.holds(footprint, (p1, p2), cut=cut) and not rounded.holds(
                            footprint, (p1 - middle[0], p2 - middle[1]), cut=cut):  # fmt: skip
                        _asked(item, other, inst.index, target, name, size, bevel, at, c, _place_values(other))
                        break


#: The edge sets one names, by name (edges.md): "all" a box's every edge, "both" a rod's two rims.
_SETS = {"all": frozenset({"vertical", "top", "bottom"}), "both": frozenset({"top", "bottom"})}


def earlier_roundings(spec: PartSpec, item: Item, target: Item, edges: EdgeSet, size: float, size_name: str, at: str,
                      c: Collect) -> bool:  # fmt: skip
    """A rounding (a bevel) against those of the same body before it in the spec (edges.md; frame.md: made in the
    spec's order). Edges another rounds already aren't there to round again: the writer's to fix (all of a box's
    edges rounded 2 mm, then its top edges 1 mm, wasn't built). Edges running round corners an earlier rounding has
    rounded follow them, so the round is no bigger than theirs (it would reach past its own middle: the judge can't
    make it); round corners another has bevelled, Forge doesn't round or bevel yet (built, the part failed its
    checks). Whether it said so."""
    mine = _SETS.get(edges.which, frozenset({edges.which}))
    bevel = size_name == "size"
    for other in spec.items[: spec.items.index(item)]:
        theirs_edges = other.get("edges")
        if not isinstance(theirs_edges, EdgeSet) or theirs_edges.of != target.id or theirs_edges.which == "joint":
            continue
        theirs = _SETS.get(theirs_edges.which, frozenset({theirs_edges.which}))
        if theirs & mine:
            c.fault(at + pointer("edges", "which"),
                    f"{item.id} {'bevels' if bevel else 'rounds'} {target.id}'s {', '.join(sorted(theirs & mine))} "
                    f"edges, which {other.id} has already: an edge is rounded or bevelled once")  # fmt: skip
            return True
        if "vertical" not in theirs or not mine & {"top", "bottom"}:
            continue
        their_size = other.get("size")
        if isinstance(their_size, Value):
            c.add("unable", at + pointer("edges", "which"),
                  f"Forge doesn't yet round or bevel edges running round corners another bevels: {item.id}'s "
                  f"{edges.which} edges of {target.id}, round the corners {other.id} bevels")  # fmt: skip
            return True
        radius = other.get("radius")
        if isinstance(radius, Value) and size > mm(radius) + 1e-9:
            c.problem("cant", at + pointer(size_name),
                      f"a {size:g} mm {item.kind} of {target.id}'s {edges.which} edges runs round its corners, which "
                      f"{other.id} rounds {mm(radius):g} mm: it can be no bigger than they are", item.get(size_name),
                      radius)  # fmt: skip
            return True
    return False


def after_thread(spec: PartSpec, item: Item, target: Item, edges: EdgeSet, layout: Layout, at: str,
                 c: Collect) -> None:  # fmt: skip
    """A rounding or a bevel of a rod's end its thread reaches, after the thread in the spec: the writer's to reorder.

    Roundings, bevels and threads are made last, in the spec's order
    (frame.md): made after the thread, it would round or bevel the thread's
    end, which OpenCascade can't (an M8 rod, its thread then its ends'
    chamfers, was accepted and not built). A thread is cut into a bevelled
    end: listed before the thread, it is made so.
    """
    copies = layout.instances.get(target.id) or []
    if not copies:
        return
    k = max(range(3), key=lambda i: abs(copies[0].normal[i]))
    ends = {e for pair in edges_of(target.kind, edges.which, ("+" if copies[0].normal[k] > 0 else "-") + "xyz"[k])
            for e in pair if e in ("+end", "-end")}  # fmt: skip
    rod = height_of(target)
    for thread in spec.items[: spec.items.index(item)]:
        if thread.get("of") != target.id or "designation" not in KINDS[thread.kind].field_names:
            continue
        length = thread.get("length")
        reached = {"+end"} | ({"-end"} if not isinstance(length, Value) or rod is None or mm(length) >= rod[0] - EPS
                              else set())  # fmt: skip
        if ends & reached:
            c.fault(at + pointer("edges"),
                    f"{item.id} {'bevels' if item.get('size') is not None else 'rounds'} the end of {target.id} its "
                    f"thread {thread.id} reaches, but comes after the thread in the spec: list it before {thread.id} "
                    "(a thread is cut into a bevelled or rounded end; the thread's own end can't be bevelled after)")  # fmt: skip
            return


def joint_reached_into(spec: PartSpec, item: Item, target: Item, edges: EdgeSet, size: float, layout: Layout,
                       at: str, c: Collect) -> None:  # fmt: skip
    """What is on a face round the foot of something standing there, within a joint's rounding (bevel) of it: asked
    about, as by a body's edge (:func:`reached_into`). The rounding fills the corner where it stands, out over the face
    by its size, after what is cut into the face or stands on it: a hole there would be filled over."""
    from forge_spec.placement import _covered, _footing, _place_values

    other_id = edges.where_meets
    meets = spec.item(other_id) if other_id is not None else None
    if meets is None:
        return
    on = target.get("on")
    standing, host = (target, meets) if isinstance(on, On) and on.item == meets.id else (meets, target)
    bevel = item.get("size") is not None
    for copy in layout.instances.get(standing.id) or []:
        if copy.host is None or copy.host[0] != host.id:
            continue
        face = layout.faces.get((copy.host[0], copy.host[1]), {}).get(copy.host[2])
        if not isinstance(face, FlatFace) or face.local is not None or face.turn != 0.0:
            continue
        foot = _covered(standing, layout, face)
        if not foot or _footing(standing) is not None:
            continue
        grown = [Shape.disc(p.centre, p.half[0] + size) if p.disc else
                 Shape.rect(p.centre, (p.half[0] + size, p.half[1] + size), (size, size, size, size)) for p in foot]  # fmt: skip
        here = face.frame.on(copy.origin)
        for other in spec.items:
            if other.id == standing.id:
                continue
            for inst in layout.instances.get(other.id) or []:
                if inst.host != copy.host:
                    continue
                parts = _covered(other, layout, face)
                if not parts:
                    continue
                there = face.frame.on(inst.origin)
                shapes = [(Shape.disc(p.centre, p.half[0]) if p.disc else Shape.rect(p.centre, p.half)).moved(*there)
                          for p in parts]  # fmt: skip
                feet = [Shape.disc(p.centre, p.half[0]) if p.disc else Shape.rect(p.centre, p.half) for p in foot]
                apart = not any(shapes_overlap(f.moved(*here), q) for f in feet for q in shapes)
                if apart and any(shapes_overlap(g.moved(*here), q) for g in grown for q in shapes):
                    _asked(item, other, inst.index, host, copy.host[2], size, bevel, at, c,
                           [*_place_values(other), *_place_values(standing)],
                           f"the foot of {standing.id}, whose joint {item.id} {'bevels' if bevel else 'rounds'}")  # fmt: skip
                    return


def _cone_band(cone: ConeFace, at_start: bool, size: float, bevel: bool) -> tuple[float, float]:
    """How far a rounding (a bevel) of a cone's rim at its start or its end reaches back from the edge: on its end, and
    along its axis on its side. A bevel's legs are its size; a round's, its radius over the tangent of half the angle
    the material makes there: 90 degrees less the cone's half angle at its wider end, more at its narrower
    (fillet.md: further back for faces at a narrower angle)."""
    here, there = (cone.start_radius, cone.end_radius) if at_start else (cone.end_radius, cone.start_radius)
    k = abs(cone.slope)
    q = math.sqrt(1.0 + k * k)
    t = k / (q + 1.0)  # the tangent of half the cone's half angle
    back = size if bevel else size * ((1.0 + t) / (1.0 - t) if here >= there else (1.0 - t) / (1.0 + t))
    return back, back / q  # along its slope, seen along its axis


def _asked(item: Item, other: Item, index: int, target: Item, face: str, size: float, bevel: bool, at: str,
           c: Collect, placed: Sequence[object] | None = None, edge: str | None = None) -> None:  # fmt: skip
    from forge_spec.items.solve._common import _item_values
    from forge_spec.placement import _outline_fields, _place_values

    what = "bevel" if bevel else "rounding"
    near = edge or f"an edge that {item.id} {'bevels' if bevel else 'rounds'}"
    c.problem("question", at,
              f"{other.id} copy {index + 1} on {target.id}'s {face} face is within {size:g} mm of {near}: the "
              f"{what}, made after it, would run into it. Should it be further from {'it' if edge else 'the edge'}, "
              f"or the {what} smaller?",
              item.get("size" if bevel else "radius"), *_item_values(other, *_outline_fields(other)),
              *(placed if placed is not None else _place_values(other)))  # fmt: skip


def base_edges_missing(
    target: Item, which: str, layout: Layout
) -> tuple[str, str] | None:
    """A body's base standing wholly on a face has no outside edges (docs/definitions/edges.md): asked whether its joint is meant."""
    if which != "bottom":
        return None
    copies = layout.instances.get(target.id) or []
    on = target.get("on")
    if not copies or not isinstance(on, On):
        return None
    for copy in copies:
        face = (
            layout.faces.get((copy.host[0], copy.host[1]), {}).get(copy.host[2])
            if copy.host
            else None
        )
        if not isinstance(face, FlatFace):
            return None
        i1, i2 = ("xyz".index(a) for a in face.axes)
        p1, p2 = copy.origin[i1] - face.centre[i1], copy.origin[i2] - face.centre[i2]
        if not face.holds(_outline(target, layout, face.axes), (p1, p2)):
            return None  # it overhangs: its base has outside edges there
    return "question", (
        f"{target.id} stands wholly on {on.item}'s {on.face} face, so its base has no outside edges: "
        f"round the inside corner where they meet ({target.id}'s joint with {on.item}) instead?"
    )


def box_rounding_limit(target: Item, which: str) -> float | None:
    """A box's edges (a block's, a post's): a radius up to its height and half its length and width; ``all`` halves the height too."""

    def s(name: str) -> float | None:
        return size_of(target, name)

    length, width, height = s("length"), s("width"), s("height")
    if length is None or width is None or height is None:
        return None
    across = min(length, width) / 2
    return {"vertical": across, "top": min(across, height), "bottom": min(across, height),
            "all": min(across, height / 2)}.get(which)  # fmt: skip


def rod_rounding_limit(target: Item, which: str) -> float | None:
    """A rod's end edges (a cylinder's, a boss's): limited by its radius and length."""

    def s(name: str) -> float | None:
        return size_of(target, name)

    diameter, length = s("diameter"), s("length") or s("height")
    if diameter is None or length is None:
        return None
    return {"top": min(diameter / 2, length), "bottom": min(diameter / 2, length),
            "both": min(diameter / 2, length / 2)}.get(which)  # fmt: skip


def cut_rounding_limit(target: Item, layout: Layout) -> float | None:
    """A cut's rim (a hole's, a slot's, a pocket's): limited by the material it is cut into."""

    def s(name: str) -> float | None:
        return size_of(target, name)

    material = material_of_cut(target, layout)
    depth = s("depth")
    deepest = (
        material
        if depth is None
        else min(depth, material)
        if material is not None
        else depth
    )
    return deepest
