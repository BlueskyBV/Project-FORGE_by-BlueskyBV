"""Where the definitions put every item: the judge's own placement.

The oracle and the checks never use the placement solver's coordinates
(:mod:`forge_spec.placement`); they place every item again here, from the
spec's fields and the written definitions (docs/definitions: frame.md,
place.md and each kind's page), sharing no code with the solver (rule R2,
docs/V2-stage2.md section 5.1). At confirmation the two layouts are compared
(:func:`compare_layouts`), and any difference is a Forge bug: the part is
held, with both answers.

What it works out, for every copy of every item:

- its **frame**: the point it stands on or cuts in at, the way it grows or
  the way the face it cuts into faces, and the frame axes its sizes run
  along;
- its **faces**, each with its outline and the **material** under it, and
  the faces it doesn't have or that can't take anything, with the reason;
- for a cut, how deep it goes, ``through`` worked out from the material;
- for a hollowed body, its hollow;

and, for the whole part, the hole diameters the standard tables give and
the **order** the part is made in.

It is written for confirmed specs. Anything the definitions don't place (a
face the item lacks, an axis not on the face, a pattern missing a value) is
a :class:`PlaceError`, never a guess.

Lengths are in millimetres in the frame, angles in degrees.
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Protocol

from forge_spec.draft import (
    AxisPosition,
    Choice,
    Counterbore,
    Countersink,
    EdgeSet,
    Faces,
    Fit,
    Item,
    On,
    PartSpec,
    Pattern,
    Place,
    Profile,
    Text,
    Through,
)
from forge_spec.font import missing_letters, text_width
from forge_spec.schema import KINDS, Category
from forge_spec.tables import lookup_fit
from forge_spec.values import Count, Value

from .letters import ink_box
from .outlines import (
    TOL,
    Arc,
    Outline,
    Piece,
    Segment,
    nearest_common,
    overlap,
    turned_range,
)

__all__ = [
    "DIRECTIONS",
    "FLAT_AXES",
    "TURN_AXES",
    "Copy",
    "Difference",
    "Dome",
    "FlatFace",
    "Hollow",
    "Less",
    "Material",
    "Over",
    "PlaceError",
    "Placed",
    "RoundSide",
    "Solid",
    "Step",
    "Taper",
    "Turned",
    "body_edges",
    "compare_layouts",
    "least",
    "material_at",
    "most",
    "place",
    "section_of",
    "turn",
]

Vec = tuple[float, float, float]
Point = tuple[float, float]

_INDEX = {"x": 0, "y": 1, "z": 2}
DIRECTIONS = ("+x", "-x", "+y", "-y", "+z", "-z")

#: A flat face's first and second axes, by the frame axis it faces along (frame.md, "Faces").
FLAT_AXES: Mapping[str, tuple[str, str]] = {
    "z": ("x", "y"),
    "x": ("y", "z"),
    "y": ("x", "z"),
}
#: Round a side, the axes 0 and 90 degrees point along, by the side's axis (place.md).
TURN_AXES: Mapping[str, tuple[str, str]] = {
    "z": ("x", "y"),
    "x": ("y", "z"),
    "y": ("z", "x"),
}
#: An angle this close to a quarter turn (in degrees) is the quarter turn.
QUARTER_SNAP = 1e-9


class PlaceError(ValueError):
    """Something the definitions don't place; ``at`` is the item."""

    def __init__(self, at: str, message: str) -> None:
        super().__init__(f"{at}: {message}")
        self.at = at
        self.message = message


# ----------------------------------------------------------------------
# Directions and turns
# ----------------------------------------------------------------------
def unit(direction: str) -> Vec:
    v = [0.0, 0.0, 0.0]
    v[_INDEX[direction[1]]] = 1.0 if direction[0] == "+" else -1.0
    return (v[0], v[1], v[2])


def opposite(direction: str) -> str:
    return ("-" if direction[0] == "+" else "+") + direction[1]


def direction_of(v: Vec) -> str | None:
    """The frame direction ``v`` is, if it is one exactly."""
    for direction in DIRECTIONS:
        if v == unit(direction):
            return direction
    return None


def turn(degrees: float) -> tuple[float, float]:
    """The cosine and sine of an angle, exact at quarter turns and accurate between them.

    >>> turn(90), turn(-180), turn(450)
    ((0.0, 1.0), (-1.0, 0.0), (0.0, 1.0))
    >>> turn(60)[0] == 0.5 or abs(turn(60)[0] - 0.5) < 1e-16
    True
    """
    if not math.isfinite(degrees):
        raise ValueError(f"an angle is a finite number, not {degrees}")
    reduced = math.fmod(degrees, 360.0)
    quarters = round(reduced / 90.0)
    rest = reduced - 90.0 * quarters
    if abs(rest) <= QUARTER_SNAP:
        rest = 0.0
    c, s = (
        (1.0, 0.0)
        if rest == 0.0
        else (math.cos(math.radians(rest)), math.sin(math.radians(rest)))
    )
    for _ in range(quarters % 4):
        c, s = -s, c
    return (c + 0.0, s + 0.0)


def _add(a: Vec, b: Vec, scale: float = 1.0) -> Vec:
    return (a[0] + scale * b[0], a[1] + scale * b[1], a[2] + scale * b[2])


def _on_axis(point: Vec, axis: str, value: float) -> Vec:
    v = list(point)
    v[_INDEX[axis]] = value
    return (v[0], v[1], v[2])


def _in_plane(point: Vec, axes: tuple[str, str]) -> Point:
    return (point[_INDEX[axes[0]]], point[_INDEX[axes[1]]])


# ----------------------------------------------------------------------
# The material under a flat face (frame.md, "The material under a face")
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class Solid:
    """The same depth of material everywhere under the face."""

    depth: float


@dataclass(frozen=True)
class Taper:
    """A cone's end: ``own`` deep out to radius ``flat`` from ``centre``, falling straight to 0 at ``edge``."""

    centre: Point
    flat: float
    edge: float
    own: float

    def at(self, radius: float) -> float:
        if radius <= self.flat:
            return self.own
        return max(self.own * (self.edge - radius) / (self.edge - self.flat), 0.0)


@dataclass(frozen=True)
class Dome:
    """A dome's flat face: the dome's height over each point, √(radius² - distance²)."""

    centre: Point
    radius: float

    def at(self, distance: float) -> float:
        return math.sqrt(max(self.radius * self.radius - distance * distance, 0.0))


@dataclass(frozen=True)
class Turned:
    """A turned part's flat end: at each distance from ``centre`` (its axis), from the end down the line there to where it leaves the half outline ``section`` (distance, height), the end at ``height``.

    Where that line runs right through, what the part stands on is under it
    too: at least ``extra`` and at most ``most_extra`` (the least and most of
    its host's material under its foot).
    """

    centre: Point
    section: Outline
    height: float
    top: bool
    extra: float = 0.0
    most_extra: float = 0.0

    def at(self, distance: float) -> float:
        return self.range(distance, distance)[0]

    def range(self, near: float, far: float) -> tuple[float, float]:
        lo, hi = turned_range(
            self.section, self.height, self.top, near, far, self.extra
        )
        if self.most_extra != self.extra:
            hi = turned_range(
                self.section, self.height, self.top, near, far, self.most_extra
            )[1]
        return lo, hi


@dataclass(frozen=True)
class Over:
    """The far face of a standing item: its own material, and where it is over its host's face, the host's.

    The host's adds where the item's own runs right down to its foot: within
    ``over`` for a block's, a cylinder's or an extrusion's (a cone stands on
    its host only within its smaller end, one of ``over``, where its own
    height is whole); for a revolution's, where the line runs right through
    it besides (its :class:`Turned`'s ``extra``).
    """

    own: Solid | Taper | Turned
    over: tuple[Outline, ...]
    host: Material


def _plus(own: Solid | Taper | Turned, host: float) -> Solid | Turned:
    """An item's own material with ``host`` more under it where it runs right down to its foot, within its ``over``."""
    if isinstance(own, Turned):
        return replace(own, extra=own.extra + host, most_extra=own.most_extra + host)
    return Solid((own.depth if isinstance(own, Solid) else own.own) + host)


@dataclass(frozen=True)
class Less:
    """A pocket's floor: the material under the face it was cut into, less its depth."""

    base: Material
    depth: float


Material = Solid | Taper | Dome | Turned | Over | Less


def material_at(material: Material, p: Point) -> float:
    """The material under one point of a face."""
    if isinstance(material, Solid):
        return material.depth
    if isinstance(material, (Taper, Dome, Turned)):
        return material.at(math.dist(p, material.centre))
    if isinstance(material, Less):
        return material_at(material.base, p) - material.depth
    if all(o.contains(p) for o in material.over):
        return material_at(_plus(material.own, material_at(material.host, p)), p)
    return material_at(material.own, p)


def most(material: Material, mouth: Sequence[Outline]) -> float:
    """The most material anywhere in the region every outline of ``mouth`` covers: how deep ``through`` goes."""
    if isinstance(material, Solid):
        return material.depth
    if isinstance(material, (Taper, Dome)):
        near = nearest_common(material.centre, mouth)
        if near is None:
            raise ValueError("most() of an empty region")
        return material.at(near)
    if isinstance(material, Turned):
        near = nearest_common(material.centre, mouth)
        if near is None:
            raise ValueError("most() of an empty region")
        far = min(m.farthest(material.centre) for m in mouth)
        return material.range(near, max(far, near))[1]
    if isinstance(material, Less):
        return most(material.base, mouth) - material.depth
    found = most(material.own, mouth)
    region = [*mouth, *material.over]
    if overlap(region):
        found = max(
            found, most(_plus(material.own, most(material.host, region)), region)
        )
    return found


def least(material: Material, mouth: Outline) -> float:
    """The least material anywhere under ``mouth``: whether a blind cut fits, or breaks through."""
    if isinstance(material, Solid):
        return material.depth
    if isinstance(material, (Taper, Dome)):
        return material.at(mouth.farthest(material.centre))
    if isinstance(material, Turned):
        return material.range(
            mouth.nearest(material.centre), mouth.farthest(material.centre)
        )[0]
    if isinstance(material, Less):
        return least(material.base, mouth) - material.depth
    if all(mouth.within(o) for o in material.over):
        return least(_plus(material.own, least(material.host, mouth)), mouth)
    return least(material.own, mouth)


# ----------------------------------------------------------------------
# Faces
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class FlatFace:
    """A flat face: where it is, which way it faces, its axes, its outline, and the material under it.

    The outline is in the frame's coordinates along the face's two axes, so
    it is centred on the face's centre there.
    """

    name: str
    centre: Vec
    normal: str
    axes: tuple[str, str]
    outline: Outline
    material: Material

    @property
    def half(self) -> Point:
        return self.outline.half


@dataclass(frozen=True)
class RoundSide:
    """A round side: the outside of a rod or tube (``outward``), or a bore or a hollow's inside.

    ``start`` is the centre of its end at the smaller coordinate along its
    axis. ``other`` is the radius of the wall's other surface: a tube's bore
    from outside, its outside from the bore; 0 for a solid rod.
    """

    name: str
    axis: str
    start: Vec
    length: float
    radius: float
    outward: bool
    other: float

    @property
    def material(self) -> float:
        """The material a cut along the radius meets: a solid rod's diameter, or the wall."""
        if self.outward and self.other == 0.0:
            return 2 * self.radius
        return abs(self.radius - self.other)


Face = FlatFace | RoundSide


# ----------------------------------------------------------------------
# What is placed
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class Copy:
    """One copy of one item, placed.

    ``point``: a body's base centre (its -end's, or a ball's lowest point
    when it is the first body); a feature's centre on the face it is on
    (round a side, the point of the side's surface). ``direction``: the way
    a body or standing feature grows, or the way the face a cut goes into
    faces (along the radius, round a side). ``axes``: the frame axes its
    length and width run along (round a side, around it and along it), or
    None for a hole round a side. ``lo``, ``hi``: the box round what a body
    or standing feature adds. ``span``: how far a cut reaches along
    -``direction`` from its point, from where it starts (0, or the side's
    axis inside a bore) to its depth, ``through`` worked out. ``foot``: how
    far a feature standing on a rod's outside reaches back past its point,
    its foot following the curve under its edges (in its box).
    """

    item: str
    index: int
    host: tuple[str, int, str] | None
    point: Vec
    direction: Vec
    axes: tuple[str, str] | None
    lo: Vec | None = None
    hi: Vec | None = None
    span: tuple[float, float] | None = None
    foot: float = 0.0


@dataclass(frozen=True)
class Hollow:
    """The hollow a shell makes in one copy of a body.

    ``walls``: each closed face's wall thickness; an open face has none.
    ``lo``, ``hi``: the box round the hollow.
    """

    item: str
    index: int
    shell: str
    walls: Mapping[str, float]
    open: frozenset[str]
    lo: Vec
    hi: Vec


@dataclass(frozen=True)
class Step:
    """One step of making the part: an item, or for a rounding made in parts, its edges at this step.

    ``edges`` maps a copy of the rounded body to the edges (each named by its
    two faces) made at this step; None for every edge the item names.
    """

    item: str
    edges: Mapping[int, tuple[tuple[str, str], ...]] | None = None


@dataclass(frozen=True)
class Placed:
    """Every item placed as the definitions say."""

    kinds: Mapping[str, str]
    copies: Mapping[str, tuple[Copy, ...]]
    faces: Mapping[tuple[str, int], Mapping[str, Face]]
    closed: Mapping[tuple[str, int], Mapping[str, str]]
    order: tuple[Step, ...]
    diameters: Mapping[str, float]
    hollows: Mapping[tuple[str, int], Hollow]

    def face(self, host: tuple[str, int, str]) -> Face:
        return self.faces[(host[0], host[1])][host[2]]


# ----------------------------------------------------------------------
# Reading fields
# ----------------------------------------------------------------------
def _mm(item: Item, name: str, *, zero: bool = False) -> float:
    """A size of the item as it is made (the middle of its tolerance), in mm: more than 0 (a cone's top may be 0, a point)."""
    value = item.get(name)
    if not isinstance(value, Value):
        raise PlaceError(item.id, f"its {name} is not a length")
    size = value.made_in("mm")
    if not (size >= 0 if zero else size > 0) or not math.isfinite(size):
        raise PlaceError(item.id, f"its {name} is {size:g} mm: a size can't be 0")
    return size


def _mm_or(item: Item, name: str, default: float | None = None) -> float | None:
    value = item.get(name)
    return value.made_in("mm") if isinstance(value, Value) else default


def _length(value: Value) -> float:
    """A length as it is made: the middle of its tolerance (sizes.md)."""
    return value.made_in("mm")


def _angle(value: Value) -> float:
    """An angle as it is made: the middle of its tolerance."""
    return value.made_in("deg")


def _choice(item: Item, name: str) -> str | None:
    value = item.get(name)
    return value.value if isinstance(value, Choice) else None


def _place(item: Item) -> Place | None:
    value = item.get("place")
    return value if isinstance(value, Place) else None


def _on(item: Item) -> On | None:
    value = item.get("on")
    return value if isinstance(value, On) else None


def _through(item: Item) -> bool:
    return isinstance(item.get("depth"), Through)


def _depends_on(item: Item) -> set[str]:
    """What must be made first (frame.md, "The order"): what it stands on or cuts into,
    is concentric with, or hollows, rounds or threads."""
    found: set[str] = set()
    on = _on(item)
    if on is not None:
        found.add(on.item)
    place = _place(item)
    if place is not None and place.concentric:
        found.add(place.concentric)
    of = item.get("of")
    if isinstance(of, str):
        found.add(of)
    edges = item.get("edges")
    if isinstance(edges, EdgeSet):
        found.add(edges.of)
        if edges.where_meets:
            found.add(edges.where_meets)
    return found


def _sequence(spec: PartSpec) -> list[Item]:
    """Every item that isn't a change to another, in the order made: each time, the earliest
    in the spec whose dependencies are all made."""
    makes = [i for i in spec.items if KINDS[i.kind].category is not Category.MODIFY]
    position = {item.id: n for n, item in enumerate(makes)}
    known = {item.id for item in spec.items}
    waiting: dict[str, set[str]] = {}
    for item in makes:
        needs = _depends_on(item) - {item.id}
        missing = needs - known
        if missing:
            raise PlaceError(
                item.id, f"it depends on {sorted(missing)}, which aren't in the spec"
            )
        waiting[item.id] = {n for n in needs if n in position}
    ready = [position[i] for i, needs in waiting.items() if not needs]
    heapq.heapify(ready)
    done: list[Item] = []
    while ready:
        item = makes[heapq.heappop(ready)]
        done.append(item)
        for other, needs in waiting.items():
            if item.id in needs:
                needs.discard(item.id)
                if not needs:
                    heapq.heappush(ready, position[other])
    if len(done) < len(makes):
        loop = [i.id for i in makes if i not in done]
        raise PlaceError(loop[0], f"items depend on each other in a loop: {loop}")
    return done


# ----------------------------------------------------------------------
# Edge sets of bodies and standing features (each kind's page, "Edges")
# ----------------------------------------------------------------------
#: The rims each round item's edge sets name, by the two faces each lies between.
_RIMS: Mapping[str, Mapping[str, tuple[tuple[str, str], ...]]] = {
    "cylinder": {"top": (("+end", "side"),), "bottom": (("-end", "side"),)},
    "cone": {"top": (("+end", "side"),), "bottom": (("-end", "side"),)},
    "boss": {"top": (("+end", "side"),)},
    "tube": {
        "top": (("+end", "side"), ("+end", "bore")),
        "bottom": (("-end", "side"), ("-end", "bore")),
        "outer": (("+end", "side"), ("-end", "side")),
        "bore": (("+end", "bore"), ("-end", "bore")),
    },
    "sphere": {"bottom": (("-end", "surface"),)},
    # An outline's: round its ends, and along its axis where the outline has a corner (extrusion.md,
    # revolution.md); each pair stands for every edge of its run there.
    "extrusion": {
        "top": (("+end", "side"),),
        "bottom": (("-end", "side"),),
        "vertical": (("side", "side"),),
        "all": (("side", "side"), ("+end", "side"), ("-end", "side")),
    },
    "revolution": {"top": (("+end", "side"),), "bottom": (("-end", "side"),)},
}


def body_edges(kind: str, which: str, up: str) -> tuple[tuple[str, str], ...]:
    """The edges an edge set names on a body or standing feature, each by the two faces it lies between.

    ``up`` is the way the item rises. A ``joint`` isn't the item's alone and
    is not listed here.

    >>> body_edges("block", "top", "+z")
    (('+z', '+x'), ('+z', '-x'), ('+z', '+y'), ('+z', '-y'))
    >>> len(body_edges("block", "all", "-y"))
    12
    >>> body_edges("tube", "bore", "+z")
    (('+end', 'bore'), ('-end', 'bore'))
    """
    if kind in ("block", "post", "rib", "tab"):
        down = opposite(up)
        sides = [d for d in DIRECTIONS if d[1] != up[1]]
        vertical = tuple(
            (a, b) for n, a in enumerate(sides) for b in sides[n + 1 :] if a[1] != b[1]
        )
        sets: dict[str, tuple[tuple[str, str], ...]] = {
            "vertical": vertical,
            "top": tuple((up, s) for s in sides),
        }
        if kind == "block":
            sets["bottom"] = tuple((down, s) for s in sides)
            sets["all"] = sets["vertical"] + sets["top"] + sets["bottom"]
        return sets.get(which, ())
    rims = _RIMS.get(kind, {})
    if which == "both" and kind in ("cylinder", "cone", "tube"):
        return rims["top"] + rims["bottom"]
    return rims.get(which, ())


# ----------------------------------------------------------------------
# The placement
# ----------------------------------------------------------------------
class _Layout:
    """The placement being worked out."""

    def __init__(self, spec: PartSpec) -> None:
        self.spec = spec
        self.items = {item.id: item for item in spec.items}
        self.copies: dict[str, tuple[Copy, ...]] = {}
        self.faces: dict[tuple[str, int], dict[str, Face]] = {}
        self.closed: dict[tuple[str, int], dict[str, str]] = {}
        self.diameters: dict[str, float] = {}
        self.hollows: dict[tuple[str, int], Hollow] = {}
        self.shells: dict[str, Item] = {}

    def close(self, key: tuple[str, int], face: str, why: str) -> None:
        self.faces.setdefault(key, {}).pop(face, None)
        self.closed.setdefault(key, {})[face] = why


def place(spec: PartSpec) -> Placed:
    """Place every item of a confirmed spec as the definitions say."""
    layout = _Layout(spec)
    for item in spec.items:
        if item.kind == "shell":
            _read_shell(item, layout)
        if item.kind == "hole":
            layout.diameters[item.id] = _hole_diameter(item)
    sequence = _sequence(spec)
    first = True
    for item in sequence:
        on = _on(item)
        category = KINDS[item.kind].category
        if category is Category.BODY and on is None:
            if not first:
                raise PlaceError(
                    item.id,
                    "only the first body sits on the origin; it must stand on a face",
                )
            layout.copies[item.id] = (_first_body(item, layout),)
        else:
            if first:
                raise PlaceError(
                    item.id, "the first item made is a body that sits on the origin"
                )
            if on is None:
                raise PlaceError(item.id, "it says no face it is on")
            layout.copies[item.id] = _on_hosts(item, on, layout)
        first = False
    return Placed(
        kinds={item.id: item.kind for item in spec.items},
        copies=dict(layout.copies),
        faces={k: dict(v) for k, v in layout.faces.items()},
        closed={k: dict(v) for k, v in layout.closed.items()},
        order=_order(sequence, layout),
        diameters=dict(layout.diameters),
        hollows=dict(layout.hollows),
    )


def _read_shell(shell: Item, layout: _Layout) -> None:
    of = shell.get("of")
    target = layout.items.get(of) if isinstance(of, str) else None
    if target is None or not isinstance(of, str):
        raise PlaceError(shell.id, f"it hollows {of!r}, which isn't in the spec")
    if target.kind not in ("block", "cylinder", "sphere"):
        raise PlaceError(
            shell.id,
            f"a shell hollows a block, a cylinder or a sphere, not a {target.kind}",
        )
    if of in layout.shells:
        raise PlaceError(
            shell.id, f"{of} is already hollowed by {layout.shells[of].id}"
        )
    layout.shells[of] = shell


def _hole_diameter(item: Item) -> float:
    diameter = item.get("diameter")
    if isinstance(diameter, Value):
        return _length(diameter)
    if isinstance(diameter, Fit):
        entry = lookup_fit(diameter.fit, diameter.for_, diameter.grade or "normal")
        if entry is None:
            raise PlaceError(
                item.id, f"no {diameter.fit} entry for {diameter.for_!r} in the tables"
            )
        return entry.size_mm
    raise PlaceError(item.id, "its diameter is neither a size nor a standard fit")


def _first_body(item: Item, layout: _Layout) -> Copy:
    """The first body, on the origin (frame.md, "The frame")."""
    up = "+z"
    if item.kind in ("cylinder", "tube", "cone", "extrusion", "revolution"):
        up = "+" + (_choice(item, "axis") or "z")
    origin = (0.0, 0.0, 0.0)
    return _body(item, layout, 0, None, origin, up, FLAT_AXES[up[1]], None)


# ----------------------------------------------------------------------
# Positions on a face (place.md)
# ----------------------------------------------------------------------
def _footprint(
    item: Item, diameters: Mapping[str, float], axes: tuple[str, str]
) -> Outline:
    """The item's outline on a flat face with these axes, centred on the origin of the face's coordinates.

    For a hole, its widest circle (its counterbore's or countersink's).
    """
    kind = item.kind
    a1, a2 = axes

    def sized(along: str | None, long: float, short: float) -> Outline:
        if along not in axes:
            raise PlaceError(
                item.id,
                f"it runs along {along}, which isn't one of the face's axes {axes}",
            )
        return (
            Outline.rect(long / 2, short / 2)
            if along == a1
            else Outline.rect(short / 2, long / 2)
        )

    if kind == "hole":
        d = diameters[item.id]
        for extra in (item.get("counterbore"), item.get("countersink")):
            if isinstance(extra, (Counterbore, Countersink)):
                d = max(d, _length(extra.diameter))
        return Outline.disc(d / 2)
    if kind == "boss" or (kind == "pocket" and _choice(item, "shape") == "circle"):
        return Outline.disc(_mm(item, "diameter") / 2)
    if kind == "pocket":
        h1, h2 = _mm(item, "length") / 2, _mm(item, "width") / 2
        r = _mm_or(item, "corner_radius", 0.0) or 0.0
        if r > min(h1, h2) + TOL:
            raise PlaceError(
                item.id,
                f"a {r:g} mm corner radius doesn't fit a {2 * h1:g} x {2 * h2:g} mm pocket",
            )
        return Outline.rect(h1, h2, corners=(r, r, r, r))
    if kind in ("block", "post", "region"):
        return Outline.rect(_mm(item, "length") / 2, _mm(item, "width") / 2)
    if kind == "rib":
        return sized(
            _choice(item, "along"), _mm(item, "length"), _mm(item, "thickness")
        )
    if kind == "tab":
        thin = _choice(item, "thickness_along")
        if thin not in axes:
            raise PlaceError(
                item.id,
                f"its thickness runs along {thin}, which isn't one of the face's axes {axes}",
            )
        return sized(
            a2 if thin == a1 else a1, _mm(item, "width"), _mm(item, "thickness")
        )
    if kind == "slot":
        along = _choice(item, "along")
        length, width = _mm(item, "length"), _mm(item, "width")
        if along not in axes:
            raise PlaceError(
                item.id,
                f"it runs along {along}, which isn't one of the face's axes {axes}",
            )
        if _choice(item, "ends") == "round":
            return Outline.stadium(length, width, along_first=along == a1)
        return sized(along, length, width)
    if kind == "text":
        return Outline.rect(_text_length(item) / 2, _mm(item, "height") / 2)
    if kind in ("cylinder", "boss"):
        return Outline.disc(_mm(item, "diameter") / 2)
    if kind == "sphere":
        return Outline.disc(_mm(item, "diameter") / 2)
    if kind == "cone":
        return Outline.disc(_mm(item, "base_diameter") / 2)
    if kind == "tube":
        return Outline.disc(_mm(item, "outer_diameter") / 2)
    if kind == "extrusion":
        return section_of(item)
    if kind == "revolution":
        return _base(item)
    raise PlaceError(item.id, f"a {kind} has no footprint on a face")


def section_of(item: Item) -> Outline:
    """An extrusion's outline, or a revolution's half outline, as written: its sides in turn, an arc anticlockwise from where it starts turning."""
    profile = item.get("profile")
    if not isinstance(profile, Profile):
        raise PlaceError(item.id, "it has no outline")
    sides: list[Piece] = []
    here = profile.start
    for segment in profile.segments:
        if segment.centre is None:
            sides.append(Segment(here, segment.to))
        else:
            c = segment.centre
            first = math.atan2(here[1] - c[1], here[0] - c[0])
            last = math.atan2(segment.to[1] - c[1], segment.to[0] - c[0])
            sweep = ((first - last) if segment.clockwise else (last - first)) % (
                2 * math.pi
            )
            whole = (
                sweep <= 1e-12
            )  # an arc back to where it starts goes all the way round
            sweep = 2 * math.pi if whole else sweep
            start = last if segment.clockwise and not whole else first
            sides.append(Arc(c, math.dist(here, c), start, sweep))
        here = segment.to
    return Outline.profile(sides)


def _turned_end(section: Outline, top: bool) -> tuple[float, float, float] | None:
    """A revolution's end: its height, inner and outer radius, where its half outline runs straight across the axis at its greatest (least) height and nothing else reaches it; None where it doesn't."""
    height = section.centre[1] + (section.half[1] if top else -section.half[1])
    flat = [q for q in section.pieces() if isinstance(q, Segment) and abs(q.a[1] - height) <= TOL
            and abs(q.b[1] - height) <= TOL and abs(q.a[0] - q.b[0]) > TOL]  # fmt: skip
    if len(flat) != 1:
        return None
    end = flat[0]
    for q in section.pieces():
        if q is end:
            continue
        points = [*q.ends(), *(q.quarters() if isinstance(q, Arc) else ())]
        if any(
            abs(p[1] - height) <= TOL
            and min(math.dist(p, e) for e in end.ends()) > 1e-6
            for p in points
        ):
            return None
    inner, outer = sorted((end.a[0], end.b[0]))
    return height, max(inner, 0.0), outer


def _base(item: Item) -> Outline:
    """What of a revolution meets the face it stands on: its end at height 0, a disc as wide as its outside."""
    end = _turned_end(section_of(item), False)
    if end is None or abs(end[0]) > TOL:
        raise PlaceError(item.id, "standing on a face, it must meet it: its outline runs straight across the axis "
                         "at height 0")  # fmt: skip
    return Outline.disc(end[2])


def _extent(
    item: Item, foot: Outline
) -> tuple[tuple[float, float], tuple[float, float]]:
    """How far an item reaches back and forth along a face's two axes from its point: its footprint's box (a revolution's: its widest)."""
    if item.kind == "revolution":
        widest = section_of(item)
        r = widest.centre[0] + widest.half[0]
        return (-r, r), (-r, r)
    (c1, c2), (h1, h2) = foot.centre, foot.half
    return (c1 - h1, c1 + h1), (c2 - h2, c2 + h2)


def _covering(
    item: Item, diameters: Mapping[str, float], face: FlatFace
) -> Outline | None:
    """What an item covers on a flat face, centred on the origin of the face's coordinates: its footprint, or a line of letters' ink's box (None: spaces alone).

    A line of letters is placed by its box (text.md), but its ink reaches
    past it (a j's tail, an f's hook): its ink must lie on the face
    (docs/V2-stage4.md, 7.1). The letters run left to right along up (the
    face's second axis) cross outward.
    """
    if item.kind != "text":
        return _footprint(item, diameters, face.axes)
    length = _text_length(item)
    text = item.get("text")
    assert isinstance(text, Text)
    height = _mm(item, "height")
    box = ink_box(text.text, height)
    if box is None:
        return None
    (x0, y0), (x1, y1) = box
    up, out = unit("+" + face.axes[1]), unit(face.normal)
    right = (
        up[1] * out[2] - up[2] * out[1],
        up[2] * out[0] - up[0] * out[2],
        up[0] * out[1] - up[1] * out[0],
    )
    sign = right[_INDEX[face.axes[0]]]
    centre = (sign * ((x0 + x1) / 2 - length / 2), (y0 + y1) / 2 - height / 2)
    return Outline.rect((x1 - x0) / 2, (y1 - y0) / 2, centre)


def _text_length(item: Item) -> float:
    """The length of a line of letters in the pinned font (text.md)."""
    text = item.get("text")
    if not isinstance(text, Text):
        raise PlaceError(item.id, "it has no letters")
    lacking = missing_letters(text.text)
    if lacking:
        raise PlaceError(item.id, f"the pinned font has no {lacking}")
    return text_width(text.text, _mm(item, "height"))


def _anchor(
    item: Item, position: AxisPosition | None, half: float, reach: tuple[float, float]
) -> float:
    """Where along one axis of the face (from its centre) a position puts an item's point, its outline reaching ``reach`` back and forth from it."""
    if position is None or position.mode == "centred":
        return 0.0
    if position.distance is None:
        raise PlaceError(item.id, f"a {position.mode} position needs its distance")
    distance = _length(position.distance)
    if position.mode == "offset":
        return distance
    if position.mode != "side" or position.side is None:
        raise PlaceError(
            item.id,
            f"a position is centred, offset or from a side, not {position.mode!r}",
        )
    back, forth = reach if position.to == "edge" else (0.0, 0.0)
    return (
        -half + distance - back if position.side[0] == "-" else half - distance - forth
    )


#: Pattern values and counts that run along a frame axis, named by it (place.md, "Patterns").
_ALONG: Mapping[str, str] = {
    **{f"{prefix}_{a}": a for prefix in ("inset", "pitch", "count") for a in "xyz"},
    **{a: a for a in "xyz"},
}


def _pattern_values(
    item: Item, pattern: Pattern
) -> tuple[dict[str, float], dict[str, int]]:
    values = {
        name: (_angle(v) if name in ("start", "step") else _length(v))
        for name, v in pattern.values.items()
    }
    counts = {name: c.n for name, c in pattern.counts.items()}
    if counts.get("each", 1) != 1:
        raise PlaceError(
            item.id, "a pattern places one copy at each of its points, for now"
        )
    return values, counts


def _needs(
    item: Item, pattern: Pattern, have: Mapping[str, object], *names: str
) -> None:
    missing = [n for n in names if n not in have]
    if missing:
        raise PlaceError(
            item.id, f"its {pattern.kind} pattern needs {missing} on this face"
        )


def _flat_positions(item: Item, face: FlatFace, layout: _Layout) -> list[Point]:
    """Every copy's centre on a flat face, in the face's coordinates, in the order they are made."""
    place = _place(item)
    a1, a2 = face.axes
    axes_given = dict(place.axes) if place else {}
    pattern = place.pattern if place else None
    if place is not None and place.angle is not None:
        raise PlaceError(
            item.id, "an angle places an item round a round side, not on a flat face"
        )
    for axis in axes_given:
        if axis not in face.axes:
            raise PlaceError(
                item.id, f"a position along {axis}, which face {face.name} doesn't have"
            )
    centre = _in_plane(face.centre, face.axes)
    foot = _footprint(item, layout.diameters, face.axes)
    reach = _extent(item, foot)
    half = face.half
    if pattern is None:
        return [(
            centre[0] + _anchor(item, axes_given.get(a1), half[0], reach[0]),
            centre[1] + _anchor(item, axes_given.get(a2), half[1], reach[1]),
        )]  # fmt: skip
    values, counts = _pattern_values(item, pattern)
    for name in (*values, *counts):
        runs = _ALONG.get(name)
        if runs is not None and runs not in face.axes:
            raise PlaceError(
                item.id,
                f"its {pattern.kind} pattern's {name} runs along {runs}, which face {face.name} doesn't have",
            )
    fixed: set[str] = set()
    if pattern.kind == "corners":
        fixed = {a1, a2}
    elif pattern.kind == "ends" and pattern.axis is not None:
        fixed = {pattern.axis}
    clash = sorted(set(axes_given) & fixed)
    if clash:
        raise PlaceError(
            item.id,
            f"its {pattern.kind} pattern sets where copies are along {clash[0]}",
        )
    kind = pattern.kind
    if kind in ("corners", "ends") and face.outline.shape != "rect":
        raise PlaceError(
            item.id, f"a {kind} pattern needs a rectangular face; {face.name} isn't one"
        )
    if kind == "corners":
        _needs(item, pattern, values, f"inset_{a1}", f"inset_{a2}")
        c1, c2 = half[0] - values[f"inset_{a1}"], half[1] - values[f"inset_{a2}"]
        return [
            (centre[0] + s1 * c1, centre[1] + s2 * c2)
            for s1 in (-1, 1)
            for s2 in (-1, 1)
        ]
    if kind in ("ends", "row") and pattern.axis not in face.axes:
        raise PlaceError(
            item.id,
            f"its {kind} runs along {pattern.axis}, which face {face.name} doesn't have",
        )
    if kind in ("circle", "arc"):
        for axis, position in axes_given.items():
            if position.mode == "side" and position.to == "edge":
                raise PlaceError(
                    item.id,
                    f"a {kind} of copies is measured to its centre along {axis}, not to an edge",
                )
    offsets: list[Point]
    if kind == "rectangle":
        _needs(item, pattern, values, a1, a2)
        offsets = [
            (s1 * values[a1] / 2, s2 * values[a2] / 2)
            for s1 in (-1, 1)
            for s2 in (-1, 1)
        ]
    elif kind == "ends":
        _needs(item, pattern, values, "inset")
        k = 0 if pattern.axis == a1 else 1
        c = half[k] - values["inset"]
        offsets = [(-c, 0.0), (c, 0.0)] if k == 0 else [(0.0, -c), (0.0, c)]
    elif kind == "row":
        _needs(item, pattern, {**values, **counts}, "pitch", "count")
        steps = [
            (k - (counts["count"] - 1) / 2) * values["pitch"]
            for k in range(counts["count"])
        ]
        offsets = (
            [(s, 0.0) for s in steps]
            if pattern.axis == a1
            else [(0.0, s) for s in steps]
        )
    elif kind == "grid":
        _needs(
            item,
            pattern,
            {**values, **counts},
            f"pitch_{a1}",
            f"pitch_{a2}",
            f"count_{a1}",
            f"count_{a2}",
        )
        n1, n2 = counts[f"count_{a1}"], counts[f"count_{a2}"]
        p1, p2 = values[f"pitch_{a1}"], values[f"pitch_{a2}"]
        offsets = [
            ((i - (n1 - 1) / 2) * p1, (j - (n2 - 1) / 2) * p2)
            for i in range(n1)
            for j in range(n2)
        ]
    elif kind in ("circle", "arc"):
        _needs(
            item,
            pattern,
            {**values, **counts},
            "diameter",
            "count",
            *(("step",) if kind == "arc" else ()),
        )
        n, radius, start = (
            counts["count"],
            values["diameter"] / 2,
            values.get("start", 0.0),
        )
        step = 360.0 / n if kind == "circle" else values["step"]
        offsets = [
            (radius * c, radius * s)
            for c, s in (turn(start + k * step) for k in range(n))
        ]
    else:
        raise PlaceError(item.id, f"an unknown pattern {kind!r}")
    anchor = [0.0, 0.0]
    for k, axis in enumerate(face.axes):
        given = axes_given.get(axis)
        if kind == "ends" and axis == pattern.axis:
            continue
        anchor[k] = _anchor(item, given, half[k], reach[k])
        if (
            given is not None
            and given.mode == "side"
            and kind in ("rectangle", "row", "grid")
        ):
            # From an edge, measured to the nearest copy along that axis (place.md, "Patterns").
            along = [o[k] for o in offsets]
            anchor[k] -= (
                min(along) if given.side and given.side[0] == "-" else max(along)
            )
    return [
        (centre[0] + anchor[0] + d1, centre[1] + anchor[1] + d2) for d1, d2 in offsets
    ]


def _concentric(item: Item, face: FlatFace, host: tuple[str, int, str], host_copies: int,
                layout: _Layout) -> list[Point]:  # fmt: skip
    """Where a concentric item goes: where its partner's axis passes through the face (place.md)."""
    place = _place(item)
    assert place is not None and place.concentric is not None
    if place.axes or place.pattern or place.angle is not None:
        raise PlaceError(
            item.id,
            "concentric gives no position along the axes, no angle and no pattern",
        )
    partner = place.concentric
    others = layout.copies.get(partner)
    if not others:
        raise PlaceError(
            item.id, f"it is concentric with {partner!r}, which isn't placed"
        )
    if partner == host[0]:
        chosen = [others[host[1]]]
    elif host_copies == 1 or len(others) == 1:
        chosen = list(
            others
        )  # every copy of the partner on the one host, or the one partner on each
    elif len(others) == host_copies:
        chosen = [others[host[1]]]
    else:
        raise PlaceError(item.id, f"{partner} has {len(others)} copies and {host[0]} {host_copies}: "
                         "the spec must say which goes with which")  # fmt: skip
    normal = unit(face.normal)
    found = []
    for other in chosen:
        if (
            abs(
                abs(sum(a * b for a, b in zip(other.direction, normal, strict=True)))
                - 1.0
            )
            > 1e-12
        ):
            raise PlaceError(
                item.id, f"{partner}'s axis isn't at right angles to face {face.name}"
            )
        found.append(_in_plane(other.point, face.axes))
    return found


def _on_hosts(item: Item, on: On, layout: _Layout) -> tuple[Copy, ...]:
    """Every copy of an item, on every copy of the face it is on, numbered in the order made."""
    hosts = layout.copies.get(on.item)
    if hosts is None:
        raise PlaceError(item.id, f"it is on {on.item!r}, which isn't placed before it")
    declared = KINDS[layout.items[on.item].kind].faces
    if on.face not in declared:
        raise PlaceError(
            item.id, f"a {layout.items[on.item].kind} has no face {on.face!r}"
        )
    made: list[Copy] = []
    for host_copy in hosts:
        key = (on.item, host_copy.index)
        face = layout.faces.get(key, {}).get(on.face)
        if face is None:
            why = layout.closed.get(key, {}).get(on.face, "it has no such face")
            raise PlaceError(
                item.id, f"{on.item}'s {on.face} can't take anything: {why}"
            )
        host = (on.item, host_copy.index, on.face)
        if isinstance(face, RoundSide):
            made += _round_copies(item, face, host, layout, len(made))
        else:
            made += _flat_copies(item, face, host, len(hosts), layout, len(made))
    count = item.get("count")
    if isinstance(count, Count) and count.n != len(made):
        raise PlaceError(
            item.id, f"its count is {count.n}, but it is placed {len(made)} times"
        )
    return tuple(made)


def _lies_on(item: Item, face: FlatFace, at: Point, layout: _Layout) -> None:
    """Refuse a cut or a standing feature that doesn't lie wholly on its face, and a body that doesn't meet it (place.md, "When it doesn't fit").

    On a ring, a cut may instead cover the whole central opening (a recess
    round the bore's end, as a counterbore is), within the ring's outside.
    """
    covering = _covering(item, layout.diameters, face)
    if covering is None:
        return  # no ink: nothing to lie on the face
    foot = covering.moved(*at)
    outline = face.outline
    if KINDS[item.kind].category is Category.BODY:
        if not overlap([foot, outline]):
            raise PlaceError(item.id, f"at {at}, it doesn't meet the face it stands on")
        return
    if foot.within(outline):
        return
    if outline.shape == "ring" and KINDS[item.kind].category is Category.CUT:
        outside = Outline.disc(outline.half[0], outline.centre)
        opening = Outline.disc(outline.inner, outline.centre)
        if foot.within(outside) and opening.within(foot):
            return
    raise PlaceError(
        item.id,
        f"at {at}, it doesn't lie wholly on the face it is on: it runs past its edge",
    )


def _flat_copies(item: Item, face: FlatFace, host: tuple[str, int, str], host_copies: int,
                 layout: _Layout, first: int) -> list[Copy]:  # fmt: skip
    place = _place(item)
    if place is not None and place.concentric:
        positions = _concentric(item, face, host, host_copies, layout)
    else:
        positions = _flat_positions(item, face, layout)
    category = KINDS[item.kind].category
    k = _INDEX[face.normal[1]]
    made: list[Copy] = []
    for n, (p1, p2) in enumerate(positions):
        point = _on_axis(_on_axis(face.centre, face.axes[0], p1), face.axes[1], p2)
        assert point[k] == face.centre[k]
        _lies_on(item, face, (p1, p2), layout)
        index = first + n
        if category is Category.CUT:
            made.append(_flat_cut(item, face, host, index, point, layout))
        else:
            made.append(
                _standing(
                    item, face, host, index, point, face.normal, face.axes, layout
                )
            )
    return made


# ----------------------------------------------------------------------
# Cuts
# ----------------------------------------------------------------------
def _mouth(item: Item, layout: _Layout, face: FlatFace, at: Point) -> Outline:
    """The outline a cut goes in through: a hole's own circle, a line of letters' ink's box, or the cut's outline."""
    if item.kind == "hole":
        return Outline.disc(layout.diameters[item.id] / 2, at)
    covering = _covering(item, layout.diameters, face)
    if (
        covering is None
    ):  # letters with no ink take nothing: their line's box stands for them
        covering = _footprint(item, layout.diameters, face.axes)
    return covering.moved(*at)


def _flat_cut(item: Item, face: FlatFace, host: tuple[str, int, str], index: int, point: Vec,
              layout: _Layout) -> Copy:  # fmt: skip
    at = _in_plane(point, face.axes)
    mouth = _mouth(item, layout, face, at)
    embossed = item.kind == "text" and _choice(item, "mode") == "emboss"
    if _through(item):
        if item.kind == "text":
            raise PlaceError(item.id, "letters are cut to a depth, never through")
        depth = most(face.material, [mouth])
        if depth <= TOL:
            raise PlaceError(
                item.id, "there is no material under its mouth to cut through"
            )
    else:
        depth = _mm(item, "depth")
    copy = Copy(item.id, index, host, point, unit(face.normal), face.axes,
                span=(-depth, 0.0) if embossed else (0.0, depth))  # fmt: skip
    if item.kind == "pocket":
        _pocket_floor(item, face, index, point, mouth, depth, layout)
    return copy


def _pocket_floor(item: Item, face: FlatFace, index: int, point: Vec, mouth: Outline, depth: float,
                  layout: _Layout) -> None:  # fmt: skip
    """A pocket's floor, a face of its own (pocket.md)."""
    key = (item.id, index)
    layout.faces.setdefault(key, {})
    if _through(item):
        layout.close(key, "bottom", "it goes through: it has no floor")
        return
    if depth >= least(face.material, mouth) - TOL:
        layout.close(
            key, "bottom", "it is as deep as the material under it: it has no floor"
        )
        return
    if face.outline.shape == "ring" and not mouth.within(face.outline):
        layout.close(
            key,
            "bottom",
            "it covers the ring's opening: its floor has the bore through it",
        )
        return
    centre = _add(point, unit(face.normal), -depth)
    layout.faces[key]["bottom"] = FlatFace(
        "bottom", centre, face.normal, face.axes, mouth, Less(face.material, depth)
    )


def _side_through(item: Item, side: RoundSide, radius: float) -> float:
    """How deep a hole through a round side goes, from its point (hole.md)."""
    if side.outward and side.other == 0.0:
        return 2 * side.radius  # across the axis and out of the far side
    if side.outward:
        if radius >= side.other - TOL:
            raise PlaceError(
                item.id,
                "a hole as wide as the bore it goes into: through one wall, or both?",
            )
        return side.radius - math.sqrt(side.other * side.other - radius * radius)
    return side.other - side.radius  # out through the wall from inside


# ----------------------------------------------------------------------
# Round sides (place.md, "On a round side")
# ----------------------------------------------------------------------
def _round_copies(item: Item, side: RoundSide, host: tuple[str, int, str], layout: _Layout,
                  first: int) -> list[Copy]:  # fmt: skip
    category = KINDS[item.kind].category
    if item.kind != "hole" and category is not Category.ADD:
        raise PlaceError(
            item.id,
            f"only holes, bosses, posts, tabs and ribs go on a round side, not a {item.kind}",
        )
    place = _place(item)
    axis = side.axis
    if place is not None and place.concentric:
        raise PlaceError(item.id, "nothing is concentric on a round side, for now")
    pattern = place.pattern if place else None
    if pattern is not None and pattern.kind not in ("circle", "arc"):
        raise PlaceError(
            item.id,
            f"round a side, only a circle or arc of copies, not a {pattern.kind}",
        )
    positions = dict(place.axes) if place else {}
    others = sorted(a for a in positions if a != axis)
    if others:
        raise PlaceError(
            item.id,
            f"on a round side, a position along its axis {axis} only, not {others[0]}",
        )
    start = _angle(place.angle) if place and place.angle is not None else 0.0
    angles = [start]
    if pattern is not None:
        values, counts = _pattern_values(item, pattern)
        extra = sorted(set(values) - ({"step"} if pattern.kind == "arc" else set()))
        if extra:
            raise PlaceError(item.id, f"round a side, a {pattern.kind} takes only a count"
                             + (" and a step" if pattern.kind == "arc" else "") + f", not {extra}")  # fmt: skip
        _needs(
            item,
            pattern,
            {**values, **counts},
            "count",
            *(("step",) if pattern.kind == "arc" else ()),
        )
        step = 360.0 / counts["count"] if pattern.kind == "circle" else values["step"]
        angles = [start + k * step for k in range(counts["count"])]
    zero, quarter = (unit("+" + a) for a in TURN_AXES[axis])
    made = []
    for n, angle in enumerate(angles):
        c, s = turn(angle)
        radial = _add(_add((0.0, 0.0, 0.0), zero, c), quarter, s)
        direction = (
            radial
            if side.outward
            else (-radial[0] + 0.0, -radial[1] + 0.0, -radial[2] + 0.0)
        )
        if item.kind == "hole":
            axes = None
            reach_along = _footprint(item, layout.diameters, ("x", "y")).half[0]
        else:
            up = direction_of(direction)
            if up is None:
                raise PlaceError(
                    item.id,
                    "a standing feature stands round a side only where it faces along a frame axis",
                )
            around = next(a for a in "xyz" if a not in (up[1], axis))
            axes = (around, axis)
            reach_along = _footprint(item, layout.diameters, axes).half[1]
        along = _anchor(
            item, positions.get(axis), side.length / 2, (-reach_along, reach_along)
        )
        if abs(along) + reach_along > side.length / 2 + TOL:
            raise PlaceError(
                item.id,
                f"{along:g} mm along the side from its middle, it runs past the side's end",
            )
        middle = side.start[_INDEX[axis]] + side.length / 2 + along
        point = _add(_on_axis(side.start, axis, middle), radial, side.radius)
        index = first + n
        if item.kind == "hole":
            made.append(_round_hole(item, side, host, index, point, direction, layout))
        else:
            assert axes is not None and up is not None
            made.append(_standing(item, side, host, index, point, up, axes, layout))
    return made


def _round_hole(item: Item, side: RoundSide, host: tuple[str, int, str], index: int, point: Vec,
                direction: Vec, layout: _Layout) -> Copy:  # fmt: skip
    radius = layout.diameters[item.id] / 2
    depth = _side_through(item, side, radius) if _through(item) else _mm(item, "depth")
    begins = (
        0.0 if side.outward else -side.radius
    )  # inside a bore, it starts at the side's axis
    return Copy(item.id, index, host, point, direction, None, span=(begins, depth))


# ----------------------------------------------------------------------
# Bodies and standing features
# ----------------------------------------------------------------------
def _standing(item: Item, face: Face, host: tuple[str, int, str], index: int, point: Vec, up: str,
              axes: tuple[str, str], layout: _Layout) -> Copy:  # fmt: skip
    if KINDS[item.kind].category is Category.BODY:
        if isinstance(face, RoundSide):
            raise PlaceError(item.id, "a body stands on a flat face")
        axis = _choice(item, "axis")
        if item.kind in (
            "cylinder",
            "tube",
            "cone",
            "extrusion",
            "revolution",
        ) and axis not in (None, up[1]):
            raise PlaceError(
                item.id,
                f"it stands on a face facing {up}, so it runs along {up[1]}, not {axis}",
            )
    return _body(item, layout, index, host, point, up, axes, face)


def _host_material(face: Face | None) -> tuple[tuple[Outline, ...], Material] | None:
    """Where a standing item's far face has its host's material under it too, and that material."""
    if face is None:
        return None
    if isinstance(face, RoundSide):
        return (), Solid(face.material)
    return (face.outline,), face.material


def _far(own: Solid | Taper | Turned, host: tuple[tuple[Outline, ...], Material] | None,
         within: tuple[Outline, ...] = ()) -> Material:  # fmt: skip
    """The material under a standing item's far face (frame.md)."""
    if host is None:
        return own
    over, material = host
    if not over:  # a round side: under the whole far face
        assert isinstance(own, Solid) and isinstance(material, Solid)
        return Solid(own.depth + material.depth)
    return Over(own, (*within, *over), material)


def _outlined(item: Item, layout: _Layout, key: tuple[str, int], point: Vec, up: str, axes: tuple[str, str],
              under: tuple[tuple[Outline, ...], Material] | None, faces: dict[str, Face]) -> tuple[Vec, Vec]:  # fmt: skip
    """An extrusion's or a revolution's bounds and flat ends (extrusion.md, revolution.md).

    An extrusion: its outline along ``axes`` from ``point``, pushed ``length``
    along ``up``; its two ends that outline, the length under each (and under
    the far one, its host's where it is over its host's face). A revolution:
    its half outline turned about ``up`` through ``point``, heights along it;
    an end where the outline runs straight across the axis at its greatest
    (least) height alone, a disc or a ring, the material under it the
    outline's own (:class:`Turned`), and under its far end, standing on a
    face, the host's too where it is over the host's face and the line runs
    right through it (:class:`Over`).
    Their sides take nothing yet.
    """
    a1, a2 = axes
    plane = FLAT_AXES[up[1]]
    u = unit(up)
    at = _in_plane(point, (a1, a2))
    section = section_of(item)
    (c1, c2), (h1, h2) = section.centre, section.half
    if item.kind == "extrusion":
        length = _mm(item, "length")
        outline = section.moved(*at)
        middle = _on_axis(
            _on_axis(point, a1, at[0] + c1), a2, at[1] + c2
        )  # a face's centre: its box's
        faces["+end"] = FlatFace(
            "+end",
            _add(middle, u, length),
            up,
            plane,
            outline,
            _far(Solid(length), under),
        )
        faces["-end"] = FlatFace("-end", middle, opposite(up), plane, outline, Solid(length))  # fmt: skip
        ends = (_add(_on_axis(_on_axis(point, a1, at[0] + c1 - h1), a2, at[1] + c2 - h2), u, 0.0),
                _add(_on_axis(_on_axis(point, a1, at[0] + c1 + h1), a2, at[1] + c2 + h2), u, length))  # fmt: skip
    else:
        r = c1 + h1
        if section.centre[0] - h1 < -TOL:
            raise PlaceError(
                item.id,
                "a revolution's outline is a half outline: it reaches across its axis",
            )
        for name, top in (("+end", True), ("-end", False)):
            end = _turned_end(section, top)
            if end is None:
                layout.close(key, name, f"its outline doesn't run straight across its axis at its "
                             f"{'greatest' if top else 'least'} height: it has no flat {name}")  # fmt: skip
                continue
            height, inner, outer = end
            centre = _add(point, u, height)
            outline = (
                Outline.ring(outer, inner, at)
                if inner > TOL
                else Outline.disc(outer, at)
            )
            own = Turned(at, section, height, top)
            faces[name] = FlatFace(name, centre, up if top else opposite(up), plane, outline,
                                   _far(own, under) if top else own)  # fmt: skip
        ends = (_add(_on_axis(_on_axis(point, a1, at[0] - r), a2, at[1] - r), u, c2 - h2),
                _add(_on_axis(_on_axis(point, a1, at[0] + r), a2, at[1] + r), u, c2 + h2))  # fmt: skip
    layout.close(
        key, "side", "its side is its outline swept: nothing is placed on it, for now"
    )
    lo = (
        min(ends[0][0], ends[1][0]),
        min(ends[0][1], ends[1][1]),
        min(ends[0][2], ends[1][2]),
    )
    hi = (
        max(ends[0][0], ends[1][0]),
        max(ends[0][1], ends[1][1]),
        max(ends[0][2], ends[1][2]),
    )
    return lo, hi


def _box(
    point: Vec, up: str, sizes: Mapping[str, float], height: float
) -> tuple[Vec, Vec]:
    lo, hi = list(point), list(point)
    for axis, size in sizes.items():
        k = _INDEX[axis]
        lo[k], hi[k] = point[k] - size / 2, point[k] + size / 2
    k = _INDEX[up[1]]
    end = point[k] + (height if up[0] == "+" else -height)
    lo[k], hi[k] = min(point[k], end), max(point[k], end)
    return (lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2])


def _box_faces(lo: Vec, hi: Vec, across: Mapping[str, float]) -> dict[str, FlatFace]:
    faces = {}
    for direction in DIRECTIONS:
        k = _INDEX[direction[1]]
        a1, a2 = FLAT_AXES[direction[1]]
        centre = [(lo[i] + hi[i]) / 2 for i in range(3)]
        centre[k] = hi[k] if direction[0] == "+" else lo[k]
        c = (centre[0], centre[1], centre[2])
        half = (
            (hi[_INDEX[a1]] - lo[_INDEX[a1]]) / 2,
            (hi[_INDEX[a2]] - lo[_INDEX[a2]]) / 2,
        )
        faces[direction] = FlatFace(direction, c, direction, (a1, a2), Outline.rect(*half, _in_plane(c, (a1, a2))),
                                    Solid(across[direction[1]]))  # fmt: skip
    return faces


def _body(item: Item, layout: _Layout, index: int, host: tuple[str, int, str] | None, point: Vec,
          up: str, axes: tuple[str, str], face: Face | None) -> Copy:  # fmt: skip
    """A body or standing feature: its bounds, its faces and the material under them."""
    kind = item.kind
    key = (item.id, index)
    on_side = isinstance(face, RoundSide)
    under = _host_material(face)
    faces: dict[str, Face] = {}
    a1, a2 = axes
    u = unit(up)
    if kind in ("block", "post", "region", "rib", "tab"):
        if kind == "rib":
            along = _choice(item, "along")
            if along not in axes:
                raise PlaceError(
                    item.id,
                    f"it runs along {along}, which isn't one of the face's axes {axes}",
                )
            sizes = {
                along: _mm(item, "length"),
                (a2 if along == a1 else a1): _mm(item, "thickness"),
            }
            height = _mm(item, "height")
        elif kind == "tab":
            thin = _choice(item, "thickness_along")
            if thin not in axes:
                raise PlaceError(
                    item.id,
                    f"its thickness runs along {thin}, which isn't one of the face's axes {axes}",
                )
            sizes = {
                thin: _mm(item, "thickness"),
                (a2 if thin == a1 else a1): _mm(item, "width"),
            }
            height = _mm(item, "length")
        else:
            sizes = {a1: _mm(item, "length"), a2: _mm(item, "width")}
            height = _mm(item, "height")
        lo, hi = _box(point, up, sizes, height)
        if kind != "region":
            across = {**sizes, up[1]: height}
            faces.update(_box_faces(lo, hi, across))
            top = faces[up]
            assert isinstance(top, FlatFace)
            faces[up] = FlatFace(
                up, top.centre, up, top.axes, top.outline, _far(Solid(height), under)
            )
            if kind == "tab" and _choice(item, "end") == "round":
                _round_tab(item, faces, key, point, up, sizes, height, layout)
    elif kind in ("cylinder", "boss", "tube", "cone"):
        length = _mm(item, "height") if kind == "boss" else _mm(item, "length")
        if kind == "cone":
            base, top_r = (
                _mm(item, "base_diameter") / 2,
                _mm(item, "top_diameter", zero=True) / 2,
            )
        else:
            base = _mm(item, "outer_diameter" if kind == "tube" else "diameter") / 2
            top_r = base
        inner = _mm(item, "inner_diameter") / 2 if kind == "tube" else 0.0
        if kind == "tube" and not 0 < inner < base:
            raise PlaceError(item.id, "a tube's bore is narrower than its outside")
        widest = max(base, top_r)
        lo, hi = _box(point, up, {a1: 2 * widest, a2: 2 * widest}, length)
        far_end = _add(point, u, length)
        plane = FLAT_AXES[up[1]]  # an end has the axes of the direction it faces
        small, large = min(base, top_r), max(base, top_r)

        def end_outline(centre: Vec, r: float) -> Outline:
            at = _in_plane(centre, plane)
            return Outline.ring(r, inner, at) if inner else Outline.disc(r, at)

        if top_r > 0:
            own: Solid | Taper = Solid(length)
            if top_r > base:
                own = Taper(_in_plane(far_end, plane), small, large, length)
            within = (
                (Outline.disc(small, _in_plane(far_end, plane)),)
                if top_r > base
                else ()
            )
            faces["+end"] = FlatFace("+end", far_end, up, plane, end_outline(far_end, top_r),
                                     _far(own, under, within))  # fmt: skip
        else:
            layout.close(key, "+end", "it comes to a point: it has no +end")
        if (
            kind != "boss"
        ):  # a boss's foot is joined to the face, and is no face of its own
            bottom: Material = Solid(length)
            if base > top_r:
                bottom = Taper(_in_plane(point, plane), small, large, length)
            faces["-end"] = FlatFace(
                "-end", point, opposite(up), plane, end_outline(point, base), bottom
            )
        start = point if up[0] == "+" else far_end
        if kind == "cone":
            layout.close(
                key,
                "side",
                "a cone's side is tapered: nothing is placed on it, for now",
            )
        else:
            faces["side"] = RoundSide("side", up[1], start, length, base, True, inner)
        if kind == "tube":
            faces["bore"] = RoundSide("bore", up[1], start, length, inner, False, base)
    elif kind == "sphere":
        radius = _mm(item, "diameter") / 2
        if _choice(item, "portion") == "upper_half":
            lo, hi = _box(point, up, {a1: 2 * radius, a2: 2 * radius}, radius)
            plane = FLAT_AXES[up[1]]
            faces["-end"] = FlatFace("-end", point, opposite(up), plane, Outline.disc(radius, _in_plane(point, plane)),
                                     Dome(_in_plane(point, plane), radius))  # fmt: skip
        else:
            centre = point if host is not None else _add(point, u, radius)
            lo = (centre[0] - radius, centre[1] - radius, centre[2] - radius)
            hi = (centre[0] + radius, centre[1] + radius, centre[2] + radius)
            layout.close(key, "-end", "a whole ball has no flat face")
        layout.close(
            key,
            "surface",
            "a ball's surface is curved: nothing is placed on it, for now",
        )
    elif kind in ("extrusion", "revolution"):
        lo, hi = _outlined(item, layout, key, point, up, axes, under, faces)
    else:
        raise PlaceError(item.id, f"a {kind} doesn't stand on a face")
    foot = 0.0
    if on_side and isinstance(face, RoundSide) and face.outward:
        foot = _foot(face, item, axes)
        k = _INDEX[up[1]]
        low, high = list(lo), list(hi)
        if up[0] == "+":
            low[k] -= foot
        else:
            high[k] += foot
        lo, hi = (low[0], low[1], low[2]), (high[0], high[1], high[2])
    layout.faces[key] = {**layout.faces.get(key, {}), **faces}
    if host is not None:
        joined = (
            "-end"
            if kind in ("cylinder", "tube", "cone", "sphere", "extrusion", "revolution")
            else opposite(up)
        )
        if joined in layout.faces[key]:
            layout.close(key, joined, f"it is joined to {host[0]} by this face")
    if on_side:
        far = "+end" if kind == "boss" else up
        for name in list(layout.faces[key]):
            if name != far:
                layout.close(
                    key,
                    name,
                    "it stands round a side: only its far face takes anything, for now",
                )
    if item.id in layout.shells:
        _hollow(item, layout, key, point, up, lo, hi)
    for name in KINDS[kind].faces:
        if (
            name.startswith("inner ")
            and name not in layout.faces[key]
            and name not in layout.closed.get(key, {})
        ):
            layout.close(key, name, f"only a hollowed {kind} has inner faces")
    return Copy(item.id, index, host, point, u, axes, lo, hi, foot=foot)


def _foot(side: RoundSide, item: Item, axes: tuple[str, str]) -> float:
    """How far a feature standing on a rod's outside reaches back past its point, at its edges."""
    across = _footprint(item, {}, axes).half[0]  # half its size round the side
    if across >= side.radius:
        raise PlaceError(item.id, "it is as wide as the round side it stands on")
    return side.radius - math.sqrt(side.radius * side.radius - across * across)


def _round_tab(item: Item, faces: dict[str, Face], key: tuple[str, int], point: Vec, up: str,
               sizes: Mapping[str, float], length: float, layout: _Layout) -> None:  # fmt: skip
    """A round-ended tab's faces (tab.md): its far end is curved, its narrow sides stop where
    the rounding starts, and its broad faces have the half-circle's outline."""
    thin = _choice(item, "thickness_along")
    assert thin is not None and thin in sizes  # checked where its sizes were read
    wide = next(a for a in sizes if a != thin)
    radius = sizes[wide] / 2
    if length < radius - TOL:
        raise PlaceError(
            item.id, "a round-ended tab sticks out at least half its width"
        )
    layout.close(key, up, "its end is round: nothing is placed on it, for now")
    faces.pop(up, None)
    straight = length - radius
    for side in ("+" + wide, "-" + wide):
        if straight <= TOL:
            faces.pop(side, None)
            layout.close(key, side, "it is all round end: it has no flat narrow side")
            continue
        lo, hi = _box(point, up, sizes, straight)
        narrow = _box_faces(lo, hi, {**sizes, up[1]: straight})[side]
        faces[side] = narrow
    for side in ("+" + thin, "-" + thin):
        broad = faces[side]
        assert isinstance(broad, FlatFace)
        k = broad.axes.index(up[1])  # the face's axis the tab sticks out along
        sign = 1 if up[0] == "+" else -1
        h = broad.outline.half
        corners = tuple(
            radius if (q1, q2)[k] == sign else 0.0
            for q1, q2 in ((1, 1), (-1, 1), (-1, -1), (1, -1))
        )
        rounded = Outline.rect(
            h[0],
            h[1],
            broad.outline.centre,
            (corners[0], corners[1], corners[2], corners[3]),
        )
        faces[side] = FlatFace(
            side, broad.centre, broad.normal, broad.axes, rounded, broad.material
        )


# ----------------------------------------------------------------------
# Hollows (shell.md)
# ----------------------------------------------------------------------
def _hollow(
    item: Item,
    layout: _Layout,
    key: tuple[str, int],
    base: Vec,
    up: str,
    lo: Vec,
    hi: Vec,
) -> None:
    """Hollow one copy of a body: its walls as the material under its faces, its open faces
    closed, its inside faces, and the hollow."""
    shell = layout.shells[item.id]
    thickness = _mm(shell, "thickness")
    floor = _mm(shell, "floor") if shell.get("floor") is not None else None
    opened = shell.get("open")
    open_faces = frozenset(opened.faces) if isinstance(opened, Faces) else frozenset()
    kind = item.kind
    dome = kind == "sphere" and _choice(item, "portion") == "upper_half"
    allowed = {
        "block": set(DIRECTIONS),
        "cylinder": {"+end", "-end"},
        "sphere": {"-end"} if dome else set(),
    }[kind]
    if not open_faces <= allowed:
        raise PlaceError(shell.id, f"a shell of a {kind} can leave open {sorted(allowed) or 'nothing'}, "
                         f"not {sorted(open_faces - allowed)}")  # fmt: skip
    faces = layout.faces[key]
    for name in sorted(open_faces):
        layout.close(key, name, f"{shell.id} leaves it open")

    def other_end(name: str) -> str:
        return {"+end": "-end", "-end": "+end"}.get(name) or opposite(name)

    if kind == "sphere":
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
    names = DIRECTIONS if kind == "block" else ("+end", "-end")
    floored = [
        name
        for name in names
        if name not in open_faces and other_end(name) in open_faces
    ]
    if floor is not None and not floored:
        raise PlaceError(
            shell.id, "a floor is the wall opposite an open face, and there is none"
        )
    walls = {
        name: (floor if floor is not None and name in floored else thickness)
        for name in names
        if name not in open_faces
    }
    if kind == "block":
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
    # A cylinder.
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


# ----------------------------------------------------------------------
# The order the part is made in (frame.md)
# ----------------------------------------------------------------------
def _order(sequence: Sequence[Item], layout: _Layout) -> tuple[Step, ...]:
    """Each item in the order made: a hollowed body whole (itself, its own edges' roundings,
    its hollow, its rim's roundings), then every other rounding, chamfer and thread."""
    steps: list[Step] = []
    rounds = [i for i in layout.spec.items if i.kind in ("fillet", "chamfer")]
    for item in sequence:
        steps.append(Step(item.id))
        shell = layout.shells.get(item.id)
        if shell is None:
            continue
        opened = shell.get("open")
        open_faces = set(opened.faces) if isinstance(opened, Faces) else set()
        before: list[Step] = []
        after: list[Step] = []
        for rounding in rounds:
            edges = rounding.get("edges")
            if (
                not isinstance(edges, EdgeSet)
                or edges.of != item.id
                or edges.which == "joint"
            ):
                continue
            own: dict[int, tuple[tuple[str, str], ...]] = {}
            rim: dict[int, tuple[tuple[str, str], ...]] = {}
            for copy in layout.copies[item.id]:
                up = direction_of(copy.direction)
                assert up is not None
                named = body_edges(item.kind, edges.which, up)
                if not named:
                    raise PlaceError(
                        rounding.id, f"{item.id} has no {edges.which} edges"
                    )
                mine = tuple(e for e in named if not open_faces & set(e))
                theirs = tuple(e for e in named if open_faces & set(e))
                if mine:
                    own[copy.index] = mine
                if theirs:
                    rim[copy.index] = theirs
            if own:
                before.append(Step(rounding.id, own))
            if rim:
                after.append(Step(rounding.id, rim))
        steps += [*before, Step(shell.id), *after]
    made = {s.item for s in steps}
    steps += [
        Step(i.id)
        for i in layout.spec.items
        if i.kind in ("fillet", "chamfer", "thread") and i.id not in made
    ]
    return tuple(steps)


# ----------------------------------------------------------------------
# Comparing with the solver's layout
# ----------------------------------------------------------------------
class SolverCopy(Protocol):
    """What :func:`compare_layouts` reads of one of the solver's copies."""

    @property
    def item(self) -> str: ...
    @property
    def index(self) -> int: ...
    @property
    def origin(self) -> tuple[float, float, float]: ...
    @property
    def normal(self) -> tuple[float, float, float]: ...
    @property
    def host(self) -> tuple[str, int, str] | None: ...
    @property
    def face_axes(self) -> tuple[str, str] | None: ...
    @property
    def lo(self) -> tuple[float, float, float] | None: ...
    @property
    def hi(self) -> tuple[float, float, float] | None: ...


class SolverLayout(Protocol):
    """What :func:`compare_layouts` reads of the solver's layout (it never imports the solver)."""

    @property
    def instances(self) -> Mapping[str, Sequence[SolverCopy]]: ...
    @property
    def order(self) -> Sequence[str]: ...
    @property
    def diameters(self) -> Mapping[str, float]: ...
    @property
    def cavities(
        self,
    ) -> Mapping[
        tuple[str, int], tuple[tuple[float, float, float], tuple[float, float, float]]
    ]: ...
    @property
    def faces(self) -> Mapping[tuple[str, int], Mapping[str, object]]: ...


@dataclass(frozen=True)
class Difference:
    """Where the definitions' placement and the solver's disagree."""

    at: str
    what: str
    placed: str
    solver: str

    def __str__(self) -> str:
        return f"{self.at}: {self.what}: the definitions say {self.placed}, the solver {self.solver}"


#: How far apart two answers may be and still agree (mm, and for unit vectors).
SAME = 1e-6


def _numbers(values: Iterable[object]) -> list[float] | None:
    found = []
    for x in values:
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            return None
        found.append(float(x))
    return found


def _near(a: Iterable[object], b: Iterable[object]) -> bool:
    """Two lists of numbers, the same within :data:`SAME`."""
    pa, pb = _numbers(a), _numbers(b)
    return (
        pa is not None
        and pb is not None
        and len(pa) == len(pb)
        and all(abs(x - y) <= SAME for x, y in zip(pa, pb, strict=True))
    )


def _show(v: object) -> str:
    if isinstance(v, tuple) and all(isinstance(x, float) for x in v):
        return "(" + ", ".join(f"{x:.9g}" for x in v) + ")"
    return repr(v)


def _from_point(copy: Copy) -> tuple[Vec, Vec] | None:
    """A copy's box from where it stands, as the solver keeps it: without a foot that follows a rod's curve."""
    if copy.lo is None or copy.hi is None:
        return None
    lo, hi = list(copy.lo), list(copy.hi)
    for k in range(3):
        if copy.direction[k] > 0:
            lo[k] += copy.foot
        elif copy.direction[k] < 0:
            hi[k] -= copy.foot
    return (lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2])


def compare_layouts(placed: Placed, layout: SolverLayout) -> tuple[Difference, ...]:
    """Every difference between the definitions' placement and the solver's.

    Compared: the items placed, every copy's count, order, host, point,
    direction, axes and box; hole diameters; the make order; hollows; and
    every face that can take something, with its centre, direction, axes,
    shape and size, or its round side's axis, start, length and radius.
    """
    found: list[Difference] = []

    def differ(at: str, what: str, mine: object, theirs: object) -> None:
        found.append(Difference(at, what, _show(mine), _show(theirs)))

    if set(placed.copies) != set(layout.instances):
        differ(
            "layout", "items placed", sorted(placed.copies), sorted(layout.instances)
        )
    for item_id, copies in placed.copies.items():
        theirs = list(layout.instances.get(item_id, ()))
        if len(theirs) != len(copies):
            differ(item_id, "copies", len(copies), len(theirs))
            continue
        for mine, other in zip(copies, theirs, strict=True):
            at = f"{item_id}/{mine.index + 1}"
            if mine.index != other.index:
                differ(at, "number", mine.index, other.index)
            if mine.host != other.host:
                differ(at, "host", mine.host, other.host)
            if not _near(mine.point, other.origin):
                differ(at, "point", mine.point, other.origin)
            if not _near(mine.direction, other.normal):
                differ(at, "direction", mine.direction, other.normal)
            if other.face_axes is not None and mine.axes != other.face_axes:
                differ(at, "axes", mine.axes, other.face_axes)
            box = _from_point(mine)
            if (
                other.lo is not None
                and other.hi is not None
                and not (box and _near(box[0], other.lo) and _near(box[1], other.hi))
            ):
                differ(at, "box", box, (other.lo, other.hi))
            _compare_faces(placed, layout, (item_id, mine.index), at, differ)
    for item_id, diameter in placed.diameters.items():
        if (
            abs(diameter - layout.diameters.get(item_id, math.nan)) > SAME
            or item_id not in layout.diameters
        ):
            differ(item_id, "diameter", diameter, layout.diameters.get(item_id))
    order = [step.item for step in placed.order]
    if order != list(layout.order):
        differ("layout", "the order made", order, list(layout.order))
    for key, hollow in placed.hollows.items():
        cavity = layout.cavities.get(key)
        if placed.kinds[key[0]] == "sphere":
            continue  # the solver keeps no box for a ball's hollow
        if cavity is None or not (
            _near(hollow.lo, cavity[0]) and _near(hollow.hi, cavity[1])
        ):
            differ(f"{key[0]}/{key[1] + 1}", "hollow", (hollow.lo, hollow.hi), cavity)
    for key in layout.cavities:
        if key not in placed.hollows:
            differ(f"{key[0]}/{key[1] + 1}", "hollow", None, layout.cavities[key])
    return tuple(found)


_SHAPES = {"rect": "rect", "disc": "disc", "ring": "annulus", "profile": "profile"}


def _profile_gap(face: FlatFace, other: object) -> float:
    """How far apart a face's outline of sides and the solver's are: the most their signed distances differ, at a grid over its box and at its sides' ends."""
    profile, centre = getattr(other, "profile", None), getattr(other, "centre", None)
    if profile is None or centre is None:
        return math.inf
    k1, k2 = (_INDEX[a] for a in face.axes)
    o1, o2 = centre[k1], centre[k2]
    (c1, c2), (h1, h2) = face.outline.centre, face.outline.half
    points = [p for q in face.outline.pieces() for p in q.ends()]
    points += [
        (c1 + h1 * (i / 4 - 1) * 1.1, c2 + h2 * (j / 4 - 1) * 1.1)
        for i in range(9)
        for j in range(9)
    ]
    return max(abs(face.outline.signed_distance(p) - float(profile.signed_distance((p[0] - o1, p[1] - o2))))
               for p in points)  # fmt: skip


def _compare_faces(placed: Placed, layout: SolverLayout, key: tuple[str, int], at: str,
                   differ: _Differ) -> None:  # fmt: skip
    mine = placed.faces.get(key, {})
    theirs = layout.faces.get(key, {})
    if set(mine) != set(theirs):
        differ(at, "faces that take something", sorted(mine), sorted(theirs))
    for name in sorted(set(mine) & set(theirs)):
        face, other = mine[name], theirs[name]
        here = f"{at}/{name}"
        checks: tuple[tuple[str, object, object], ...]
        if isinstance(face, FlatFace):
            if not hasattr(other, "half"):
                differ(here, "kind of face", "flat", type(other).__name__)
                continue
            checks = (
                ("centre", face.centre, getattr(other, "centre", None)),
                ("normal", face.normal, getattr(other, "normal", None)),
                ("axes", face.axes, getattr(other, "axes", None)),
                ("shape", _SHAPES[face.outline.shape], getattr(other, "shape", None)),
                ("half", face.outline.half, getattr(other, "half", None)),
                (
                    "inner radius",
                    face.outline.inner,
                    getattr(other, "inner_radius", None),
                ),
                ("corners", face.outline.corners, getattr(other, "corners", None)),
            )
            if face.outline.shape == "profile" and _profile_gap(face, other) > SAME:
                differ(
                    here,
                    "outline",
                    f"{_profile_gap(face, other):.3g} mm from the solver's",
                    "",
                )
        else:
            if not hasattr(other, "radius"):
                differ(here, "kind of face", "round", type(other).__name__)
                continue
            checks = (
                ("axis", face.axis, getattr(other, "axis", None)),
                ("start", face.start, getattr(other, "start", None)),
                ("length", face.length, getattr(other, "length", None)),
                ("radius", face.radius, getattr(other, "radius", None)),
                ("outward", face.outward, getattr(other, "outward", None)),
            )
        for what, a, b in checks:
            if (
                isinstance(a, tuple)
                and isinstance(b, tuple)
                and _numbers(a) is not None
            ):
                same = _near(a, b)
            elif isinstance(a, float) and isinstance(b, (int, float)):
                same = abs(a - b) <= SAME
            else:
                same = a == b
            if not same:
                differ(here, what, a, b)


class _Differ(Protocol):
    def __call__(self, at: str, what: str, mine: object, theirs: object) -> None: ...
