"""What the two-draft comparison of several kinds shares (the ``compare`` role's leaf: it imports neither the kinds' modules, but for the registry when asked, nor ``compare.py``).

Moved from ``compare.py`` at stage 4b.0b's step 3, unchanged but for each
kind's branch, which is its own module's: the features a draft is reduced
to, the vector helpers, and what cuts, rims and roundings share.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from forge_spec.draft import Choice, Counterbore, Countersink, EdgeSet, Item
from forge_spec.ends import Blind, ThroughAll, end_of
from forge_spec.geometry import EPS, FlatFace, SideFace, Vec, bbox, material_at
from forge_spec.items.solve._common import degrees
from forge_spec.placement import Instance, Layout, _outline, mm
from forge_spec.values import Value

_INDEX = {"x": 0, "y": 1, "z": 2}


@dataclass(frozen=True)
class Feature:
    """One shape a draft builds, placed in the frame.

    ``shape`` is what is compared ("box", "rod", "round cut", "edge"...),
    never the kind of item that made it. ``sizes`` is its extent along x, y
    and z, or None; ``point`` where it is (a solid's centre, a cut's mouth,
    an edge's middle), or None for what has no place of its own. When
    ``line`` is set, the point may be anywhere on the line through it along
    its first direction: a cut right through is that line. ``directions``
    turn with the part, each signed (a blind hole goes into the material)
    or not (a rod has no front). ``detail`` doesn't turn: a diameter, a
    depth, a radius, the letters.

    ``index``, ``item`` and ``kind`` are the item it comes from, so a
    difference is said of it; ``field`` is the item's field it shows, where
    it is one ("inner_diameter" for a tube's bore).
    """

    index: int
    item: str
    kind: str
    shape: str
    sizes: Vec | None
    point: Vec | None
    detail: tuple[object, ...] = ()
    directions: tuple[tuple[Vec, bool], ...] = ()
    line: bool = False
    field: str = ""
    #: For a rounded edge, a hollow or a thread: the item it is on. Where that
    #: item differs, these follow it, and aren't differences of their own.
    of: str = ""


def _r(x: float) -> float:
    return round(x, 6) + 0.0


def _neg(v: Vec) -> Vec:
    return (-v[0], -v[1], -v[2])


def _add(a: Vec, b: Vec, scale: float = 1.0) -> Vec:
    return (a[0] + b[0] * scale, a[1] + b[1] * scale, a[2] + b[2] * scale)


def _sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _mid(a: Vec, b: Vec) -> Vec:
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2)


def _axis(k: int, length: float = 1.0) -> Vec:
    return (
        length if k == 0 else 0.0,
        length if k == 1 else 0.0,
        length if k == 2 else 0.0,
    )


def _up(copy: Instance) -> int:
    """The frame axis a body or standing feature grows along (every one is axis-aligned)."""
    return max(range(3), key=lambda k: abs(copy.normal[k]))


def _choice(item: Item, name: str) -> str | None:
    value = item.get(name)
    return value.value if isinstance(value, Choice) else None


def _length(item: Item, name: str) -> float | None:
    value = item.get(name)
    return mm(value) if isinstance(value, Value) else None


def _face_direction(face: str, copy: Instance) -> Vec:
    """The way a named face of a body faces: "+z" up; a round body's "+end" the way it grows."""
    if face in ("+end", "-end"):
        return copy.normal if face == "+end" else _neg(copy.normal)
    if len(face) == 2 and face[0] in "+-" and face[1] in _INDEX:
        return _axis(_INDEX[face[1]], 1.0 if face[0] == "+" else -1.0)
    return (0.0, 0.0, 0.0)  # pragma: no cover - a shell opens named faces


#: One edge: its middle, its direction, what it is, and its extent.
_Edge = tuple[Vec, Vec, tuple[object, ...], Vec | None]


def _box_edges(copy: Instance, which: str) -> Iterable[_Edge]:
    assert copy.lo is not None and copy.hi is not None
    lo, hi, up = copy.lo, copy.hi, _up(copy)
    top = hi[up] if copy.normal[up] > 0 else lo[up]
    for k in range(3):  # the four edges along each axis
        if (which == "vertical") != (k == up) and which != "all":
            continue
        a, b = (x for x in range(3) if x != k)
        for ca, cb in itertools.product((lo[a], hi[a]), (lo[b], hi[b])):
            at = {a: ca, b: cb}
            if which in ("top", "bottom") and (at[up] == top) != (which == "top"):
                continue
            middle = [0.0, 0.0, 0.0]
            middle[k], middle[a], middle[b] = (lo[k] + hi[k]) / 2, ca, cb
            yield (
                (middle[0], middle[1], middle[2]),
                _axis(k),
                ("edge",),
                _axis(k, hi[k] - lo[k]),
            )


def cut_material(copy: Instance, layout: Layout) -> float | None:
    """The material a cut's copy goes into at its point: under it on a flat face, a round side's wall; None with no face."""
    host = copy.host
    face = (
        layout.faces.get((host[0], host[1]), {}).get(host[2])
        if host is not None
        else None
    )
    if isinstance(face, FlatFace):
        i1, i2 = (_INDEX[a] for a in face.axes)
        material = material_at(
            face,
            copy.origin[i1] - face.centre[i1],
            copy.origin[i2] - face.centre[i2],
            0.0,
        )
    elif isinstance(face, SideFace):
        material = face.wall
    else:  # pragma: no cover - a placed cut has its face
        return None
    return material


def cut_features(n: int, item: Item, copy: Instance, layout: Layout, material: float,
                 diameter: float | None, corner: Callable[[float, float], float]) -> list[Feature]:  # fmt: skip
    """A cut by its mouth and depth, or right through by its line; its counterbore and countersink at the mouth.

    ``diameter`` a round cut's (None: a square-edged one, its outline across
    the face, ``corner`` how its corners are rounded, seen looking into it).
    """
    kind = item.kind
    mouth, into = copy.origin, _neg(copy.normal)
    end = end_of(item)
    deep = mm(end.depth) if isinstance(end, Blind) else material
    through = isinstance(end, ThroughAll) or deep >= material - EPS
    deep = min(deep, material)
    head: tuple[object, ...]
    tail: tuple[object, ...]
    if diameter is not None:
        shape, sizes, head, tail = "round cut", (0.0, 0.0, 0.0), (_r(diameter),), ()
    else:  # a rectangle, a slot: its outline across the face, and how its corners are rounded
        assert copy.face_axes is not None
        h1, h2 = bbox(_outline(item, layout, copy.face_axes))
        extent = [0.0, 0.0, 0.0]
        extent[_INDEX[copy.face_axes[0]]], extent[_INDEX[copy.face_axes[1]]] = (
            2 * h1,
            2 * h2,
        )
        shape, sizes, head, tail = (
            "square cut",
            (extent[0], extent[1], extent[2]),
            (),
            (_r(corner(h1, h2)),),
        )
    field = "diameter" if shape == "round cut" else ""
    found = [
        Feature(n, item.id, kind, shape, sizes, mouth, (*head, "through", *tail), ((into, False),), line=True,
                field=field)
        if through
        else Feature(n, item.id, kind, shape, sizes, mouth, (*head, "blind", _r(deep), *tail), ((into, True),),
                     field=field)
    ]  # fmt: skip
    bore, sink = item.get("counterbore"), item.get("countersink")
    if isinstance(bore, Counterbore):
        found.append(Feature(n, item.id, kind, "rim", None, mouth,
                             ("counterbore", _r(mm(bore.diameter)), _r(mm(bore.depth))), ((into, True),),
                             field="counterbore"))  # fmt: skip
    if isinstance(sink, Countersink):
        found.append(Feature(n, item.id, kind, "rim", None, mouth,
                             ("countersink", _r(mm(sink.diameter)), _r(degrees(sink.angle))), ((into, True),),
                             field="countersink"))  # fmt: skip
    return found


def corner_rounded(item: Item, h1: float, h2: float) -> float:
    """How a square-edged cut's corners are rounded, seen looking into it: its corner radius, at most its half sizes."""
    return min(_length(item, "corner_radius") or 0.0, h1, h2)


#: Which ends of a round thing each set of its edges is at.
RIM_ENDS = {
    "top": ("+",),
    "bottom": ("-",),
    "both": ("+", "-"),
    "outer": ("+", "-"),
    "bore": ("+", "-"),
}


def rims(
    copy: Instance, which: str, radii: Callable[[str, float], tuple[float, ...]]
) -> Iterable[_Edge]:
    """A round thing's edges: the rims at its ends, ``radii(end, outer)`` each end's (its outer radius, but a cone's and a tube's)."""
    assert copy.lo is not None and copy.hi is not None
    up = _up(copy)
    centre = _mid(copy.lo, copy.hi)
    outer = (copy.hi[(up + 1) % 3] - copy.lo[(up + 1) % 3]) / 2
    for end in RIM_ENDS.get(which, ()):
        grows = copy.normal[up] > 0
        level = copy.hi[up] if (end == "+") == grows else copy.lo[up]
        rim = list(centre)
        rim[up] = level
        for r in radii(end, outer):
            if r > EPS:
                yield (
                    (rim[0], rim[1], rim[2]),
                    _axis(up),
                    ("rim",),
                    (2 * r, 2 * r, 2 * r),
                )


def rounding_features(n: int, item: Item, layout: Layout, field: str) -> list[Feature]:
    """A fillet's or a chamfer's features, by each edge it touches: ``field`` its size's (a radius, a size)."""
    kind = item.kind
    edges = item.get("edges")
    size = _length(item, field)
    if (
        not isinstance(edges, EdgeSet) or size is None
    ):  # pragma: no cover - a checked draft has both
        return []
    return [Feature(n, item.id, kind, "edge", extent, middle, (kind, _r(size), *what), ((along, False),),
                    field=field, of=edges.of)
            for middle, along, what, extent in _edges(edges, layout)]  # fmt: skip


def _edges(edges: EdgeSet, layout: Layout) -> Iterable[_Edge]:
    """Each edge an edge set names, on every copy of its item.

    A box's edges are its twelve, by where they lie: "vertical" along the
    way it stands, "top" and "bottom" round the faces at each end of it. A
    round thing's are its rims, at each end; a cut's is its mouth (and a
    pocket's "bottom" its floor's outline); a joint is where the item meets
    the one it stands on, or that stands on it.
    """
    from forge_spec.items.compare import COMPARE

    item = layout.items.get(edges.of)
    if item is None:  # pragma: no cover - a checked draft names its item
        return
    which = edges.which
    for copy in layout.instances.get(edges.of, ()):
        if which == "joint":
            yield from _joint(copy, edges.where_meets, layout)
        elif copy.lo is None or copy.hi is None:
            yield from COMPARE[item.kind].cut_edges(item, copy, which, layout)
        else:
            yield from COMPARE[item.kind].edges(item, copy, which)


def _joint(copy: Instance, other: str | None, layout: Layout) -> Iterable[_Edge]:
    """Where one item meets another: at the foot of whichever stands on the other."""
    feet = [copy] if copy.host is not None and copy.host[0] == other else []
    feet += [
        c
        for c in layout.instances.get(other or "", ())
        if c.host is not None and c.host[0] == copy.item
    ]
    for foot in feet:
        if foot.lo is None or foot.hi is None:
            continue
        up = _up(foot)
        span = [foot.hi[k] - foot.lo[k] if k != up else 0.0 for k in range(3)]
        yield foot.origin, foot.normal, ("joint",), (span[0], span[1], span[2])


def cut_rim(
    item: Item, copy: Instance, which: str, outline: tuple[object, ...]
) -> Iterable[_Edge]:
    """A cut's rounded or chamfered edge, its outline ``outline``: its mouth's, or a pocket's floor's."""
    at = copy.origin
    if which == "bottom":
        at = _add(copy.origin, _neg(copy.normal), _length(item, "depth") or 0.0)
    yield at, copy.normal, ("mouth" if which == "top" else "floor", *outline), None
