"""Two drafts of one brief, compared by the part they describe (plan, section 4.2).

Published work found that items two independent readings of a document agree
on are right far more often than the ones they disagree on: disagreement is a
good misread detector. So a brief may be drafted twice, and where the drafts
differ, the person is asked. Agreement proves nothing (two drafts from one
model share blind spots); it only means nothing was found.

The drafts are compared by what they would build, never by how they are
written: their ids, their order, the kinds they use for one shape (a post or
a block standing on a plate; a tube, or a rod with a hole down it), the faces
they name and the way the part is turned may all differ while the part is
the same. Each draft's layout (:mod:`forge_spec.placement`) is reduced to
features, each one shape of the part placed in the frame:

- a solid: a box, a rod, a cone, a ball or a dome, a round-ended tab, a
  region's envelope, with its sizes, its centre and the way it points;
- a cut: a round or a square-edged one, by its mouth and how deep it goes,
  or, right through, by the line it runs along (where it enters is then no
  matter: one hole through a plate is one, drilled from either side); a
  counterbore or countersink by its own place, at the mouth it widens; and
  letters by where they are and which way they read;
- each rounded or chamfered edge, a hollow and its openings, a thread on its
  rod: by where each is on the part.

The second is turned every way a solid can be turned (the 24 rotations,
never a mirror image, which is another part) and moved every way that lines
one of its shapes up with one of the first's, and the way that matches most
is kept: so a size that differs moves nothing else. What is left unmatched
is the difference, each paired with its likeliest counterpart and said of the
first draft's item and field where it can be, so the person can answer there.
A rounding, a hollow or a thread that only follows a changed item is no
difference of its own. Shapes are compared one by one: a solid split into
others (one block, or two stacked flush) reads as a difference until the
compiled parts are compared as geometry (stage 4), and the person answers
it "right as drafted".

- :func:`differences`: the questions the second draft raises about the first.
- :func:`features`: a layout reduced to what it builds.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .checks import SpecReport
from .draft import (
    Choice,
    Counterbore,
    Countersink,
    Designation,
    EdgeSet,
    Faces,
    Item,
    Text,
    Through,
)
from .geometry import EPS, FlatFace, SideFace, Vec, bbox, material_at
from .placement import Instance, Layout, _outline, degrees, mm
from .problems import pointer
from .schema import KINDS, Category
from .values import Value

__all__ = ["Difference", "Feature", "differences", "features"]

#: How close two sizes or places must be to be the same, in mm (and two unit
#: directions, in each component).
TOLERANCE = 1e-3
_INDEX = {"x": 0, "y": 1, "z": 2}
_BOXES = ("block", "post", "rib")
_RODS = ("cylinder", "boss")
_ROUND = ("cylinder", "boss", "tube", "cone", "sphere")


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


@dataclass(frozen=True)
class Difference:
    """Where the second draft reads the brief otherwise: said of the first draft's field, or of the spec."""

    at: str
    message: str


# ----------------------------------------------------------------------
# What a layout builds
# ----------------------------------------------------------------------
def features(report: SpecReport) -> tuple[Feature, ...]:
    """Every shape a checked draft builds: its solids, its cuts, and its rounded edges, hollows and threads."""
    spec, layout = report.spec, report.layout
    if spec is None or layout is None:
        return ()
    found: list[Feature] = []
    for n, item in enumerate(spec.items):
        category = KINDS[item.kind].category
        if category is Category.MODIFY:
            found += _modifier(n, item, layout)
            continue
        for copy in layout.instances.get(item.id, ()):
            if category is Category.CUT:
                found += _cut(n, item, copy, layout)
            elif copy.lo is not None and copy.hi is not None:
                found += _solid(n, item, copy)
    return tuple(found)


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


def _dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


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


def _solid(n: int, item: Item, copy: Instance) -> list[Feature]:
    assert copy.lo is not None and copy.hi is not None
    lo, hi, kind = copy.lo, copy.hi, item.kind
    sizes, centre = _sub(hi, lo), _mid(lo, hi)
    up = _up(copy)
    across = (hi[(up + 1) % 3] - lo[(up + 1) % 3]) / 2
    axis = (copy.normal, False)
    if kind in _BOXES or (kind == "tab" and _choice(item, "end") != "round"):
        return [Feature(n, item.id, kind, "box", sizes, centre)]
    if kind == "tab":
        width = _length(item, "width") or 0.0
        return [
            Feature(
                n,
                item.id,
                kind,
                "round-ended tab",
                sizes,
                centre,
                (_r(width),),
                ((copy.normal, True),),
            )
        ]
    if kind == "region":
        describe = item.get("describe")
        wall = _length(item, "min_wall")
        return [Feature(n, item.id, kind, "region", sizes, centre,
                        (describe.text if isinstance(describe, Text) else None,
                         None if wall is None else _r(wall)))]  # fmt: skip
    if kind in _RODS:
        return [
            Feature(
                n,
                item.id,
                kind,
                "rod",
                sizes,
                centre,
                (_r(2 * across),),
                (axis,),
                field="diameter",
            )
        ]
    if kind == "tube":
        inner = _length(item, "inner_diameter") or 0.0
        return [Feature(n, item.id, kind, "rod", sizes, centre, (_r(2 * across),), (axis,), field="outer_diameter"),
                # A tube is a rod with a bore right through: as built, one shape.
                Feature(n, item.id, kind, "round cut", (0.0, 0.0, 0.0), centre, (_r(inner), "through"),
                        (axis,), line=True, field="inner_diameter")]  # fmt: skip
    if kind == "cone":
        base, top = (
            _length(item, "base_diameter") or 0.0,
            _length(item, "top_diameter") or 0.0,
        )
        return [
            Feature(
                n,
                item.id,
                kind,
                "cone",
                sizes,
                centre,
                (_r(base), _r(top)),
                ((copy.normal, True),),
            )
        ]
    if kind == "sphere":
        diameter = _r(_length(item, "diameter") or 0.0)
        if _choice(item, "portion") == "upper_half":
            return [
                Feature(
                    n,
                    item.id,
                    kind,
                    "dome",
                    sizes,
                    copy.origin,
                    (diameter,),
                    ((copy.normal, True),),
                )
            ]
        return [Feature(n, item.id, kind, "ball", sizes, centre, (diameter,))]
    return [
        Feature(n, item.id, kind, kind, sizes, centre)
    ]  # pragma: no cover - every placed kind is above


def _cut(n: int, item: Item, copy: Instance, layout: Layout) -> list[Feature]:
    """A cut by its mouth and depth, or right through by its line; its counterbore and countersink at the mouth."""
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
        return []
    kind = item.kind
    mouth, into = copy.origin, _neg(copy.normal)
    if kind == "text":
        assert copy.face_axes is not None
        # Letters read the right way round from outside the face: up is the
        # face's second axis, and they run along up x outward
        # (docs/definitions/text.md), so text on a -z face runs along -x.
        rises = _axis(_INDEX[copy.face_axes[1]])
        out = copy.normal
        reads = (
            rises[1] * out[2] - rises[2] * out[1],
            rises[2] * out[0] - rises[0] * out[2],
            rises[0] * out[1] - rises[1] * out[0],
        )
        letters = item.get("text")
        return [Feature(n, item.id, kind, "text", None, mouth,
                        (letters.text if isinstance(letters, Text) else None, _choice(item, "mode"),
                         _r(_length(item, "height") or 0.0), _r(_length(item, "depth") or 0.0)),
                        ((copy.normal, True), (reads, True), (rises, True)))]  # fmt: skip
    depth = item.get("depth")
    deep = mm(depth) if isinstance(depth, Value) else material
    through = isinstance(depth, Through) or deep >= material - EPS
    deep = min(deep, material)
    head: tuple[object, ...]
    tail: tuple[object, ...]
    if kind == "hole" or (kind == "pocket" and _choice(item, "shape") == "circle"):
        diameter = (
            layout.diameters.get(item.id, 0.0)
            if kind == "hole"
            else _length(item, "diameter") or 0.0
        )
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
            (_r(_corner(item, h1, h2)),),
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


def _corner(item: Item, h1: float, h2: float) -> float:
    """How a square-edged cut's corners are rounded, seen looking into it: a round-ended slot's are half its width."""
    if item.kind == "slot":
        width, length = _length(item, "width") or 0.0, _length(item, "length") or 0.0
        return (
            width / 2 if _choice(item, "ends") == "round" and length >= width else 0.0
        )
    return min(_length(item, "corner_radius") or 0.0, h1, h2)


def _modifier(n: int, item: Item, layout: Layout) -> list[Feature]:
    """Rounds and chamfers by each edge they touch, a hollow by its cavity, a thread by its rod."""
    kind = item.kind
    if kind in ("fillet", "chamfer"):
        edges = item.get("edges")
        size = _length(item, "radius" if kind == "fillet" else "size")
        if (
            not isinstance(edges, EdgeSet) or size is None
        ):  # pragma: no cover - a checked draft has both
            return []
        field = "radius" if kind == "fillet" else "size"
        return [Feature(n, item.id, kind, "edge", extent, middle, (kind, _r(size), *what), ((along, False),),
                        field=field, of=edges.of)
                for middle, along, what, extent in _edges(edges, layout)]  # fmt: skip
    of = item.get("of")
    if not isinstance(of, str):  # pragma: no cover - a checked draft names its body
        return []
    found: list[Feature] = []
    for copy in layout.instances.get(of, ()):
        if copy.lo is None or copy.hi is None:
            continue
        if kind == "shell":
            opened = item.get("open")
            faces = opened.faces if isinstance(opened, Faces) else ()
            ways = tuple((_face_direction(face, copy), True) for face in faces)
            cavity = layout.cavities.get((of, copy.index))
            if cavity is not None:
                found.append(Feature(n, item.id, kind, "hollow", _sub(cavity[1], cavity[0]), _mid(*cavity),
                                     ("hollow", len(faces)), ways, field="thickness", of=of))  # fmt: skip
            else:  # a ball's or a dome's: its walls, as given
                thickness, floor = _length(item, "thickness"), _length(item, "floor")
                found.append(Feature(n, item.id, kind, "hollow", None, _mid(copy.lo, copy.hi),
                                     ("hollow ball", _r(thickness or 0.0), None if floor is None else _r(floor),
                                      len(faces)), ways, field="thickness", of=of))  # fmt: skip
        elif kind == "thread":
            designation = item.get("designation")
            length = _length(item, "length")
            rod = max(copy.hi[k] - copy.lo[k] for k in range(3) if k != _up(copy))
            found.append(Feature(n, item.id, kind, "thread", None, _mid(copy.lo, copy.hi),
                                 (designation.text if isinstance(designation, Designation) else None,
                                  _choice(item, "hand"), None if length is None else _r(length), _r(rod)),
                                 ((copy.normal, False),), field="designation", of=of))  # fmt: skip
    return found


def _face_direction(face: str, copy: Instance) -> Vec:
    """The way a named face of a body faces: "+z" up; a round body's "+end" the way it grows."""
    if face in ("+end", "-end"):
        return copy.normal if face == "+end" else _neg(copy.normal)
    if len(face) == 2 and face[0] in "+-" and face[1] in _INDEX:
        return _axis(_INDEX[face[1]], 1.0 if face[0] == "+" else -1.0)
    return (0.0, 0.0, 0.0)  # pragma: no cover - a shell opens named faces


#: One edge: its middle, its direction, what it is, and its extent.
_Edge = tuple[Vec, Vec, tuple[object, ...], Vec | None]


def _edges(edges: EdgeSet, layout: Layout) -> Iterable[_Edge]:
    """Each edge an edge set names, on every copy of its item.

    A box's edges are its twelve, by where they lie: "vertical" along the
    way it stands, "top" and "bottom" round the faces at each end of it. A
    round thing's are its rims, at each end; a cut's is its mouth (and a
    pocket's "bottom" its floor's outline); a joint is where the item meets
    the one it stands on, or that stands on it.
    """
    item = layout.items.get(edges.of)
    if item is None:  # pragma: no cover - a checked draft names its item
        return
    which = edges.which
    for copy in layout.instances.get(edges.of, ()):
        if which == "joint":
            yield from _joint(copy, edges.where_meets, layout)
        elif copy.lo is None or copy.hi is None:
            yield from _cut_edges(item, copy, which, layout)
        elif item.kind in _ROUND:
            yield from _rims(item, copy, which)
        else:
            yield from _box_edges(copy, which)


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


def _rims(item: Item, copy: Instance, which: str) -> Iterable[_Edge]:
    """A round thing's edges: the rims at its ends, the outer and the bore's for a tube."""
    assert copy.lo is not None and copy.hi is not None
    up = _up(copy)
    ends = {
        "top": ("+",),
        "bottom": ("-",),
        "both": ("+", "-"),
        "outer": ("+", "-"),
        "bore": ("+", "-"),
    }
    centre = _mid(copy.lo, copy.hi)
    outer = (copy.hi[(up + 1) % 3] - copy.lo[(up + 1) % 3]) / 2
    for end in ends.get(which, ()):
        grows = copy.normal[up] > 0
        level = copy.hi[up] if (end == "+") == grows else copy.lo[up]
        radii: tuple[float, ...] = (outer,)
        if item.kind == "cone":
            radii = (
                (
                    _length(item, "top_diameter" if end == "+" else "base_diameter")
                    or 0.0
                )
                / 2,
            )
        elif item.kind == "tube":
            inner = (_length(item, "inner_diameter") or 0.0) / 2
            radii = {"outer": (outer,), "bore": (inner,)}.get(which, (outer, inner))
        rim = list(centre)
        rim[up] = level
        for r in radii:
            if r > EPS:
                yield (
                    (rim[0], rim[1], rim[2]),
                    _axis(up),
                    ("rim",),
                    (2 * r, 2 * r, 2 * r),
                )


def _cut_edges(
    item: Item, copy: Instance, which: str, layout: Layout
) -> Iterable[_Edge]:
    """A cut's rounded or chamfered edge: its mouth's outline, or a pocket's floor's."""
    outline: tuple[object, ...] = (
        (_r(layout.diameters.get(item.id, 0.0)),) if item.kind == "hole" else ()
    )
    if copy.face_axes is not None and item.kind != "hole":
        h1, h2 = bbox(_outline(item, layout, copy.face_axes))
        outline = (_r(2 * h1), _r(2 * h2))
    at = copy.origin
    if which == "bottom":
        at = _add(copy.origin, _neg(copy.normal), _length(item, "depth") or 0.0)
    yield at, copy.normal, ("mouth" if which == "top" else "floor", *outline), None


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


# ----------------------------------------------------------------------
# Turning one draft onto the other
# ----------------------------------------------------------------------
Rotation = tuple[
    tuple[int, int, int], tuple[int, int, int]
]  # (where each axis comes from, its sign)


def _rotations() -> tuple[Rotation, ...]:
    """The 24 rotations of a solid, the identity first: each axis goes to an axis, signed.

    A turn keeps the part's handedness: its determinant, the permutation's
    parity times the signs, is +1. A mirror image (-1) is another part.
    """
    found: list[Rotation] = []
    for perm in itertools.permutations(range(3)):
        swaps = sum(1 for i in range(3) for j in range(i + 1, 3) if perm[i] > perm[j])
        for signs in itertools.product((1, -1), repeat=3):
            if (-1) ** swaps * signs[0] * signs[1] * signs[2] == 1:
                found.append(
                    ((perm[0], perm[1], perm[2]), (signs[0], signs[1], signs[2]))
                )
    return tuple(found)


_ROTATIONS = _rotations()


def _turn(rotation: Rotation, v: Vec) -> Vec:
    perm, signs = rotation
    return (signs[0] * v[perm[0]], signs[1] * v[perm[1]], signs[2] * v[perm[2]])


@dataclass(frozen=True)
class _Move:
    """A turn, then a shift: where the second draft's frame lies in the first's."""

    rotation: Rotation
    shift: Vec


_STILL = _Move(_ROTATIONS[0], (0.0, 0.0, 0.0))


@dataclass(frozen=True)
class _Placed:
    """A feature in the first draft's frame: its sizes, its directions, and the point that stands for its place."""

    feature: Feature
    sizes: Vec | None
    directions: tuple[tuple[Vec, bool], ...]
    key: Vec | None


def _placed(feature: Feature, move: _Move) -> _Placed:
    sizes: Vec | None = None
    if feature.sizes is not None:
        turned = _turn(move.rotation, feature.sizes)
        sizes = (abs(turned[0]), abs(turned[1]), abs(turned[2]))
    directions = tuple(
        (_turn(move.rotation, d), signed) for d, signed in feature.directions
    )
    key = (
        None
        if feature.point is None
        else _add(_turn(move.rotation, feature.point), move.shift)
    )
    if key is not None and feature.line and directions:
        # A line stands for its place by its point nearest the frame's origin.
        u = directions[0][0]
        key = _add(key, u, -_dot(key, u))
    return _Placed(feature, sizes, directions, key)


def _close(a: object, b: object) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) <= TOLERANCE
    return a == b


def _alike(a: Sequence[object], b: Sequence[object]) -> bool:
    return len(a) == len(b) and all(_close(x, y) for x, y in zip(a, b, strict=True))


def _same(a: _Placed, b: _Placed, *, places: bool = True) -> bool:
    """Whether two placed features are one shape: alike, sized, pointing and (``places``) placed alike."""
    fa, fb = a.feature, b.feature
    if fa.shape != fb.shape or fa.line != fb.line or not _alike(fa.detail, fb.detail):
        return False
    if (a.sizes is None) != (b.sizes is None) or (a.key is None) != (b.key is None):
        return False
    if (
        a.sizes is not None
        and b.sizes is not None
        and any(abs(a.sizes[k] - b.sizes[k]) > TOLERANCE for k in range(3))
    ):
        return False
    if len(a.directions) != len(b.directions):
        return False
    for (u, signed), (v, _) in zip(a.directions, b.directions, strict=True):
        apart = max(abs(u[k] - v[k]) for k in range(3))
        if signed and apart > TOLERANCE:
            return False
        if (
            not signed
            and min(apart, max(abs(u[k] + v[k]) for k in range(3))) > TOLERANCE
        ):
            return False
    if places and a.key is not None and b.key is not None:
        return all(abs(a.key[k] - b.key[k]) <= TOLERANCE for k in range(3))
    return True


Cell = tuple[str, tuple[int, int, int] | None]

#: The cells next to a cell, itself included: two places within TOLERANCE
#: of each other always lie in neighbouring cells.
_NEAR = tuple(itertools.product((-1, 0, 1), repeat=3))


def _cell(placed: _Placed) -> Cell:
    key, shape = placed.key, placed.feature.shape
    if key is None or not all(math.isfinite(c / TOLERANCE) for c in key):
        return (shape, None)
    return (
        shape,
        (
            round(key[0] / TOLERANCE),
            round(key[1] / TOLERANCE),
            round(key[2] / TOLERANCE),
        ),
    )


def _match(
    first: Sequence[_Placed], second: Sequence[Feature], move: _Move
) -> tuple[list[int], list[int]]:
    """Pair the features one to one, the second's moved onto the first's; return each draft's left unpaired.

    The second's features are filed by shape and place, so each of the
    first's is tried only against those near it: a pattern of hundreds of
    holes compares in about as many steps, not hundreds squared.
    """
    moved = [_placed(f, move) for f in second]
    cells: dict[Cell, list[int]] = {}
    for j, b in enumerate(moved):
        cells.setdefault(_cell(b), []).append(j)
    taken: set[int] = set()
    unpaired: list[int] = []
    for i, a in enumerate(first):
        here = _cell(a)
        near = [here] if here[1] is None else [
            (here[0], (here[1][0] + d[0], here[1][1] + d[1], here[1][2] + d[2])) for d in _NEAR
        ]  # fmt: skip
        partner = next(
            (
                j
                for cell in near
                for j in cells.get(cell, ())
                if j not in taken and _same(a, moved[j])
            ),
            None,
        )
        if partner is None:
            unpaired.append(i)
        else:
            taken.add(partner)
    return unpaired, [j for j in range(len(second)) if j not in taken]


def _centre(report: SpecReport) -> Vec:
    extent = report.layout.extent() if report.layout is not None else None
    return _mid(*extent) if extent is not None else (0.0, 0.0, 0.0)


def _signature(f: Feature) -> str:
    """What a feature is, but not where: its shape, its sizes (unturned, sorted) and its detail."""
    sizes = sorted(_r(x) for x in f.sizes) if f.sizes is not None else None
    return repr((f.shape, sizes, f.detail))


def _moves(
    a: Sequence[Feature], b: Sequence[Feature], first: SpecReport, second: SpecReport
) -> list[_Move]:
    """Every way worth trying to lay the second draft on the first.

    For each of the 24 turns: as both drafts place their first body (on the
    origin), centred on each other, and with each of a few of the first's
    shapes lined up with each like shape of the second's. Lining shapes up
    is what lets one size differ without moving everything else.
    """
    signatures: dict[str, list[Feature]] = {}
    for f in a:
        if f.point is not None and not f.line and not f.of:
            signatures.setdefault(_signature(f), []).append(f)
    # The rarest shapes first: each lines the drafts up in the fewest ways.
    anchors = [
        fs[0]
        for _, fs in sorted(signatures.items(), key=lambda kv: (len(kv[1]), kv[0]))[:4]
    ]
    candidates = [f for f in b if f.point is not None and not f.line and not f.of]
    centres = (_centre(first), _centre(second))
    found: list[_Move] = []
    seen: set[tuple[Rotation, tuple[int, int, int]]] = set()
    for rotation in _ROTATIONS:
        shifts = [(0.0, 0.0, 0.0), _sub(centres[0], _turn(rotation, centres[1]))]
        turned = _Move(rotation, (0.0, 0.0, 0.0))
        for anchor in anchors:
            here = _placed(anchor, _STILL)
            assert here.key is not None
            for other in candidates:
                there = _placed(other, turned)
                if there.key is not None and _same(here, there, places=False):
                    shifts.append(_sub(here.key, there.key))
        for shift in shifts:
            key = (
                rotation,
                (
                    round(shift[0] / TOLERANCE),
                    round(shift[1] / TOLERANCE),
                    round(shift[2] / TOLERANCE),
                ),
            )
            if key not in seen:
                seen.add(key)
                found.append(_Move(rotation, shift))
    return found


def _best(
    a: Sequence[Feature], b: Sequence[Feature], moves: Sequence[_Move]
) -> tuple[list[int], list[int]]:
    """The fewest features left unpaired over every move: weighed first on the solids alone, when there are many."""
    first = [_placed(f, _STILL) for f in a]
    if len(moves) > 6 and len(a) + len(b) > 64:
        solids_a = [
            p
            for p in first
            if p.feature.sizes is not None and not p.feature.line and not p.feature.of
        ]
        solids_b = [f for f in b if f.sizes is not None and not f.line and not f.of]

        def left(move: _Move) -> int:
            unpaired = _match(solids_a, solids_b, move)
            return len(unpaired[0]) + len(unpaired[1])

        moves = sorted(moves, key=left)[:6]
    best: tuple[list[int], list[int]] | None = None
    for move in moves:
        unpaired = _match(first, b, move)
        if best is None or len(unpaired[0]) + len(unpaired[1]) < len(best[0]) + len(
            best[1]
        ):
            best = unpaired
        if not unpaired[0] and not unpaired[1]:
            break
    assert best is not None
    return best


# ----------------------------------------------------------------------
# The differences
# ----------------------------------------------------------------------
def differences(first: SpecReport, second: SpecReport) -> tuple[Difference, ...]:
    """What the second draft builds otherwise than the first, said of the first's items and fields.

    Empty when the two build the same part, however each is written or
    turned. Neither draft is taken as right: the person settles each one.
    Only drafts the person could confirm are compared: one with a fault is
    the writer's to fix first, and one that can't be made (CAN'T, UNABLE)
    ends its run; neither builds anything yet (ValueError).
    """
    for report in (first, second):
        if report.spec is None or any(
            p.kind in ("fault", "cant", "unable") for p in report.problems
        ):
            raise ValueError(
                "only drafts that check clean, and can be made, are compared"
            )
    a, b = features(first), features(second)
    found: dict[str, list[str]] = {}
    if a or b:
        only_first, only_second = _best(a, b, _moves(a, b, first, second))
        left_a, left_b = [a[i] for i in only_first], [b[j] for j in only_second]
        pairs = _pairs(left_a, left_b)
        # Roundings, hollows and threads follow the item they are on: where
        # it differs, they move or grow with it, and say nothing new.
        changed = {
            left_a[i].item for i, _ in pairs if i is not None and not left_a[i].of
        }
        for i, j in pairs:
            if i is not None and j is not None:
                if left_a[i].of in changed and _what(left_a[i]) == _what(left_b[j]):
                    continue
                at, said = _contrast(left_a[i], left_b[j], first)
                found.setdefault(at, []).append(said)
            elif i is not None and left_a[i].shape == "rim":
                rim = left_a[i]
                found.setdefault(pointer("items", rim.index, rim.field), []).append(
                    f"{rim.item} has a {rim.field} ({_rim(rim)}) here, none in the second draft")  # fmt: skip
            elif i is not None:
                mine = left_a[i]
                found.setdefault(pointer("items", mine.index), []).append(
                    f"the second draft has no {mine.kind} like {mine.item}{_describe(mine)}")  # fmt: skip
            elif j is not None:
                extra = left_b[j]
                found.setdefault("", []).append(
                    f"the second draft has a {extra.kind}{_describe(extra)} that this one hasn't")  # fmt: skip
    ours, theirs = (_material(r) for r in (first, second))
    if _named(ours) != _named(theirs):
        found.setdefault(pointer("requirements", "material"), []).append(
            f"the material is {repr(ours) if ours else 'not given'} here, "
            f"{repr(theirs) if theirs else 'not given'} in the second draft")  # fmt: skip
    return tuple(
        Difference(at, "; ".join(dict.fromkeys(messages)))
        for at, messages in found.items()
    )


def _what(f: Feature) -> str:
    """What a follower is, whatever its place and size: a rounding of one radius on one kind of edge."""
    return repr((f.shape, f.kind, f.detail, len(f.directions)))


def _pairs(
    mine: Sequence[Feature], theirs: Sequence[Feature]
) -> list[tuple[int | None, int | None]]:
    """Each unpaired feature of the first with its likeliest counterpart in the second, or none.

    Of one shape, the likeliest differ in the fewest ways (their detail,
    their size), then lie nearest: so a hole that moved is said to have
    moved, not to have changed size with another that moved too.
    """
    costs: list[tuple[int, float, int, int]] = []
    if len(mine) * len(theirs) <= 40_000:
        for i, f in enumerate(mine):
            for j, g in enumerate(theirs):
                if f.shape == g.shape or (
                    f.kind == g.kind and "rim" not in (f.shape, g.shape)
                ):
                    ways, far = _apart(f, g)
                    costs.append((ways + 2 * (f.shape != g.shape), far, i, j))
        costs.sort()
    else:  # too many to weigh each against each: in order, shape by shape
        costs = [(0, 0.0, i, j) for i, j in zip(range(len(mine)), range(len(theirs)), strict=False)
                 if mine[i].shape == theirs[j].shape]  # fmt: skip
    used_i: set[int] = set()
    used_j: set[int] = set()
    found: list[tuple[int | None, int | None]] = []
    for _, _, i, j in costs:
        if i not in used_i and j not in used_j:
            used_i.add(i)
            used_j.add(j)
            found.append((i, j))
    found.sort(key=lambda p: p[0] if p[0] is not None else -1)
    found += [(i, None) for i in range(len(mine)) if i not in used_i]
    found += [(None, j) for j in range(len(theirs)) if j not in used_j]
    return found


def _apart(f: Feature, g: Feature) -> tuple[int, float]:
    """In how many ways two features of one shape differ, and how far apart they lie (each in its own frame)."""
    ways = int(not _alike(f.detail, g.detail))
    if f.sizes is not None and g.sizes is not None:
        ways += int(sorted(_r(x) for x in f.sizes) != sorted(_r(x) for x in g.sizes))
    far = (
        math.dist(f.point, g.point)
        if f.point is not None and g.point is not None
        else 0.0
    )
    return ways, far


def _material(report: SpecReport) -> str:
    material = report.spec.requirements.material if report.spec is not None else None
    return material.text if material is not None else ""


def _named(text: str) -> str:
    """A material's name as compared: "PETG", "petg" and "PETG " are one."""
    return " ".join(text.split()).casefold()


def _contrast(mine: Feature, other: Feature, report: SpecReport) -> tuple[str, str]:
    """Where two features of one shape differ, as a pointer into the first draft, and how."""
    here = pointer("items", mine.index)
    name, shape = mine.item, mine.shape
    if shape in ("round cut", "rod") and not _close(mine.detail[0], other.detail[0]):
        return here + pointer(mine.field or "diameter"), (
            f"{name} is Ø{_mm(mine.detail[0])} here, Ø{_mm(other.detail[0])} in the second draft")  # fmt: skip
    if shape in ("round cut", "square cut"):
        if mine.line != other.line or not _close(_cut_depth(mine), _cut_depth(other)):
            return here + pointer(
                "depth"
            ), f"{name} goes {_depth(mine)} here, {_depth(other)} in the second draft"
        if shape == "square cut" and not _close(mine.detail[-1], other.detail[-1]):
            field = "corner_radius" if mine.kind == "pocket" else "ends"
            return here + pointer(field), (f"{name}'s corners are rounded to {_mm(mine.detail[-1])} here, "
                                           f"{_mm(other.detail[-1])} in the second draft")  # fmt: skip
    if shape == "edge":
        if not _close(mine.detail[1], other.detail[1]):
            return here + pointer(mine.field), (f"{name}'s {mine.field} is {_mm(mine.detail[1])} here, "
                                                f"{_mm(other.detail[1])} in the second draft")  # fmt: skip
        return here + pointer(
            "edges"
        ), f"{name} rounds other edges in the second draft: check which the brief means"
    if shape != other.shape:  # one item kind, built two ways: a square or a round end
        if mine.kind == "tab":
            ends = {"box": "square", "round-ended tab": "round"}
            return here + pointer("end"), (f"{name}'s end is {ends.get(shape, shape)} here, "
                                           f"{ends.get(other.shape, other.shape)} in the second draft")  # fmt: skip
        return here, f"{name} is a {shape} here, a {other.shape} in the second draft"
    if shape == "rim":
        if _alike(mine.detail, other.detail):
            return here + pointer(
                mine.field
            ), f"{name}'s {mine.field} is on another side in the second draft"
        return here + pointer(mine.field), (f"{name}'s {mine.field} is {_rim(mine)} here, {_rim(other)} in the "
                                            "second draft")  # fmt: skip
    if shape == "region":
        for k, field in enumerate(("describe", "min_wall")):
            if not _close(mine.detail[k], other.detail[k]):
                return here + pointer(field), (f"{name}'s {field} is {_shown(mine.detail[k])} here, "
                                               f"{_shown(other.detail[k])} in the second draft")  # fmt: skip
    if shape == "text":
        for k, field in enumerate(("text", "mode", "height", "depth")):
            if not _close(mine.detail[k], other.detail[k]):
                return here + pointer(field), (f"{name}'s {field} is {_shown(mine.detail[k])} here, "
                                               f"{_shown(other.detail[k])} in the second draft")  # fmt: skip
        return here + pointer(
            "place"
        ), f"{name} sits or reads another way in the second draft: check the brief"
    if shape == "hollow":
        if (
            mine.sizes is not None
            and other.sizes is not None
            and _box(mine.sizes) != _box(other.sizes)
        ):
            return here, (f"the hollow {name} leaves is {_box(mine.sizes)} here, {_box(other.sizes)} in the second "
                          "draft")  # fmt: skip
        return here + pointer(
            "open"
        ), f"{name} is open on other faces in the second draft: check the brief"
    if not _alike(mine.detail, other.detail):
        return (
            here,
            f"{name} is {_details(mine)} here, {_details(other)} in the second draft",
        )
    if (
        mine.sizes is not None
        and other.sizes is not None
        and (sorted(_r(x) for x in mine.sizes) != sorted(_r(x) for x in other.sizes))
    ):
        return (
            here,
            f"{name} is {_box(mine.sizes)} here, {_box(other.sizes)} in the second draft",
        )
    placed = (
        report.spec is not None and report.spec.items[mine.index].get("on") is not None
    )
    return (here + pointer("place") if placed else here), (
        f"{name} sits elsewhere, or points another way, in the second draft: check where the brief puts it")  # fmt: skip


def _rim(feature: Feature) -> str:
    """A counterbore or countersink in words: "Ø9, 1 mm deep", "Ø9 at 90°"."""
    kind, diameter, last = feature.detail[:3]
    if kind == "counterbore":
        return (
            f"\u00d8{diameter:g}, {last:g} mm deep"
            if isinstance(diameter, float) and isinstance(last, float)
            else "?"
        )
    return (
        f"\u00d8{diameter:g} at {last:g}\u00b0"
        if isinstance(diameter, float) and isinstance(last, float)
        else "?"
    )


def _cut_depth(feature: Feature) -> object:
    """How deep a cut goes: None right through."""
    if feature.line:
        return None
    return feature.detail[feature.detail.index("blind") + 1]


def _mm(x: object) -> str:
    return f"{x:g} mm" if isinstance(x, float) else str(x)


def _shown(x: object) -> str:
    if isinstance(x, float):
        return f"{x:g} mm"
    return "none" if x is None else repr(x) if isinstance(x, str) else str(x)


def _depth(feature: Feature) -> str:
    deep = _cut_depth(feature)
    return "right through" if deep is None else f"{_mm(deep)} deep"


def _box(sizes: Iterable[float]) -> str:
    return " x ".join(f"{x:.6g}" for x in sizes if x > EPS) + " mm"


def _describe(feature: Feature) -> str:
    if feature.sizes is None or not any(x > EPS for x in feature.sizes):
        return f" ({_details(feature)})"
    return f" ({_box(feature.sizes)})"


def _details(feature: Feature) -> str:
    shown = [
        f"{x:g}" if isinstance(x, float) else str(x)
        for x in feature.detail
        if x not in (None, ())
    ]
    return ", ".join(shown) or feature.kind
