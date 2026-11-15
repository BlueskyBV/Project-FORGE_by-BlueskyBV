"""What the spec checks of several kinds share (the ``checks`` role's leaf: it imports neither the kinds' modules, but for the registry when asked, nor ``checks.py``).

Moved from ``checks.py`` at stage 4b.0b's step 3, unchanged but for each
kind's branch, which is its own module's, and what another kind publishes,
asked of the registry.
"""

from __future__ import annotations

from typing import Protocol

from forge_spec.draft import EdgeSet, Faces, Item, On, PartSpec
from forge_spec.geometry import (
    EPS,
    FlatFace,
    SideFace,
    disc,
    most_material_under,
    outline_on_face,
)
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
    return most_material_under(
        face, (disc(0.0),), point[i1] - face.centre[i1], point[i2] - face.centre[i2]
    )


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
    shell = layout.shells.get(target.id)
    if shell is not None:
        thickness = shell.get("thickness")
        opened = shell.get("open")
        open_faces = opened.faces if isinstance(opened, Faces) else ()
        # A rim's outside and inside edges are both rounded: two in the wall's thickness.
        if isinstance(thickness, Value) and rim_rounded(target, edges.which, open_faces, layout) \
                and size > mm(thickness) / 2 + 1e-9:  # fmt: skip
            c.problem("question", at + pointer(size_name),
                     f"a {size:g} mm {item.kind} on both edges of the {mm(thickness):g} mm wall at the open rim of "
                     f"{target.id} doesn't fit (at most {mm(thickness) / 2:g} mm): which edges get it, or how big "
                     "may the rim's be?", size_value, thickness)  # fmt: skip


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
        if not outline_on_face(face, _outline(target, layout, face.axes), p1, p2):
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
