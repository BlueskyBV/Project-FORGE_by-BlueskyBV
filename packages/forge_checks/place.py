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

import functools
import heapq
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Protocol

from forge_numeric import scalar as fs
from forge_spec.draft import (
    AxisPosition,
    Choice,
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
    axis_names,
)
from forge_spec.ends import ThroughAll, end_of
from forge_spec.font import missing_letters, text_width
from forge_spec.schema import KINDS
from forge_spec.tables import lookup_fit
from forge_spec.values import Count, Value

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
    "in_axes",
    "least",
    "material_at",
    "most",
    "place",
    "same_under",
    "section_of",
    "turn",
]

Vec = tuple[float, float, float]
Point = tuple[float, float]

_INDEX = {"x": 0, "y": 1, "z": 2}
DIRECTIONS = ("+x", "-x", "+y", "-y", "+z", "-z")
if TYPE_CHECKING:
    from .items.place.pattern import PatternPlace
    from .items.place.protocol import PlaceKind

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
        else (fs.cos(math.radians(rest)), fs.sin(math.radians(rest)))
    )
    for _ in range(quarters % 4):
        c, s = -s, c
    return (c + 0.0, s + 0.0)


def _add(a: Vec, b: Vec, scale: float = 1.0) -> Vec:
    return (a[0] + scale * b[0], a[1] + scale * b[1], a[2] + scale * b[2])


def _scale(a: Vec, k: float) -> Vec:
    return (k * a[0] + 0.0, k * a[1] + 0.0, k * a[2] + 0.0)


def in_axes(name: str, axes: tuple[str, str]) -> str:
    """An axis of a flat face as the frame names it: its own first, ``u``, and second, ``v``, are ``axes``' (place.md,
    "On a flat face"); the part's names are themselves."""
    return axes[0] if name == "u" else axes[1] if name == "v" else name


def _on_axis(point: Vec, axis: str, value: float) -> Vec:
    v = list(point)
    v[_INDEX[axis]] = value
    return (v[0], v[1], v[2])


def _in_plane(point: Vec, axes: tuple[str, str]) -> Point:
    return (point[_INDEX[axes[0]]], point[_INDEX[axes[1]]])


def _aligned(vector: Vec) -> tuple[int, bool] | None:
    """(which coordinate, whether the + way) of a vector that is exactly one of +-x, +-y, +-z; else None."""
    for k in range(3):
        if abs(vector[k]) == 1.0 and all(vector[j] == 0.0 for j in range(3) if j != k):
            return k, vector[k] > 0.0
    return None


@dataclass(frozen=True)
class FaceFrame:
    """A face's frame as the judge's placement reads it (4b.0c item 1a; V2-stage4b-0c.md, 3.3).

    ``origin`` is on the face; ``u`` and ``v`` its first and second axes
    (frame.md's table; round a side, the ways out at 0 and 90 degrees) and
    ``n`` its normal (round a side, its axis). Coordinates in its plane are
    measured along ``u`` and ``v`` from the part's origin, as the judge's
    outlines are, so a face's outline is centred on its centre's own; a
    point placed in the plane keeps the face's level along ``n``. An aligned
    frame is applied by choosing coordinates and their signs, never a product
    with 0 or 1, so its numbers are those the axis names gave; any other by
    its products (item 1b). The judge's own, made from the definitions (R2).
    """

    origin: Vec
    u: Vec
    v: Vec
    n: Vec

    @staticmethod
    def of_names(origin: Vec, u: str, v: str, n: str) -> FaceFrame:
        return FaceFrame(
            origin,
            unit(u if u[0] in "+-" else "+" + u),
            unit(v if v[0] in "+-" else "+" + v),
            unit(n if n[0] in "+-" else "+" + n),
        )

    @functools.cached_property
    def _axes(self) -> tuple[tuple[int, bool], ...] | None:
        found = (_aligned(self.u), _aligned(self.v), _aligned(self.n))
        return None if None in found else found  # type: ignore[return-value]

    def _along(self, point: Vec, j: int) -> float:
        axes = self._axes
        if axes is not None:
            k, plus = axes[j]
            return point[k] if plus else -point[k]
        d = (self.u, self.v, self.n)[j]
        return point[0] * d[0] + point[1] * d[1] + point[2] * d[2]

    def plane(self, point: Vec) -> Point:
        """Where ``point`` is in the face's plane: along ``u`` and ``v``, from the part's origin."""
        return (self._along(point, 0), self._along(point, 1))

    def level(self, point: Vec) -> float:
        """How far along ``n`` ``point`` is, from the part's origin."""
        return self._along(point, 2)

    def _set(self, point: Vec, j: int, value: float) -> Vec:
        axes = self._axes
        if axes is not None:
            k, plus = axes[j]
            found = list(point)
            found[k] = value if plus else -value
            return (found[0], found[1], found[2])
        d = (self.u, self.v, self.n)[j]
        return _add(point, d, value - self._along(point, j))

    def point(self, p1: float, p2: float) -> Vec:
        """The point of the face's plane at ``(p1, p2)`` in it (:meth:`plane`'s inverse there)."""
        return self._set(self._set(self.origin, 0, p1), 1, p2)

    def at_level(self, point: Vec, level: float) -> Vec:
        """``point`` moved along ``n`` to ``level``."""
        return self._set(point, 2, level)


@dataclass(frozen=True)
class Motion:
    """A rigid motion, the judge's own: a turn about the part's origin (its matrix, by rows), then a shift. A turned
    item's faces, and what is on them, are placed as with the item upright, then moved by it (place.md, "A turned
    item's faces")."""

    rows: tuple[Vec, Vec, Vec]
    shift: Vec

    @staticmethod
    def about(point: Vec, axis: Vec, by: Point) -> Motion:
        """The turn about the line through ``point`` along the unit ``axis``, by the angle whose cosine and sine are
        ``by``, right-handed about it."""
        c, s = by
        x, y, z = axis
        k = 1.0 - c
        rows = ((c + x * x * k, x * y * k - z * s, x * z * k + y * s),
                (y * x * k + z * s, c + y * y * k, y * z * k - x * s),
                (z * x * k - y * s, z * y * k + x * s, c + z * z * k))  # fmt: skip
        turned = Motion(rows, (0.0, 0.0, 0.0)).vector(point)
        return Motion(rows, (point[0] - turned[0], point[1] - turned[1], point[2] - turned[2]))

    def vector(self, d: Vec) -> Vec:
        r = self.rows
        return (r[0][0] * d[0] + r[0][1] * d[1] + r[0][2] * d[2] + 0.0,
                r[1][0] * d[0] + r[1][1] * d[1] + r[1][2] * d[2] + 0.0,
                r[2][0] * d[0] + r[2][1] * d[1] + r[2][2] * d[2] + 0.0)  # fmt: skip

    def point(self, p: Vec) -> Vec:
        return _add(self.vector(p), self.shift)

    def after(self, first: Motion) -> Motion:
        """This motion after ``first``."""
        r, q = self.rows, first.rows
        rows = tuple(tuple(r[i][0] * q[0][k] + r[i][1] * q[1][k] + r[i][2] * q[2][k] + 0.0 for k in range(3))
                     for i in range(3))  # fmt: skip
        return Motion(rows, self.point(first.shift))  # type: ignore[arg-type]

    def frame(self, f: FaceFrame) -> FaceFrame:
        return FaceFrame(self.point(f.origin), self.vector(f.u), self.vector(f.v), self.vector(f.n))

    def box(self, lo: Vec, hi: Vec) -> tuple[Vec, Vec]:
        corners = [self.point((x, y, z)) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
        return ((min(c[0] for c in corners), min(c[1] for c in corners), min(c[2] for c in corners)),
                (max(c[0] for c in corners), max(c[1] for c in corners), max(c[2] for c in corners)))  # fmt: skip


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


def same_under(face: FlatFace) -> float | None:
    """The material under a flat face where it is the same under all of it (frame.md): its own, or a standing item's
    own height and its host's, wholly over a host with the same under all of it; None where it isn't."""
    material = face.material
    if isinstance(material, Solid):
        return material.depth
    if (
        isinstance(material, Over)
        and isinstance(material.own, Solid)
        and isinstance(material.host, Solid)
        and any(face.outline.within(over) for over in material.over)
    ):
        return material.own.depth + material.host.depth
    return None


def material_at(material: Material, p: Point) -> float:
    """The material under one point of a face."""
    if isinstance(material, Solid):
        return material.depth
    if isinstance(material, (Taper, Dome, Turned)):
        return material.at(fs.dist(p, material.centre))
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
    #: A turned item's far face, and what stands on or is cut in one (place.md, "A turned item's far face"): its axes
    #: turned in its plane by this many degrees from the part's ``axes``, the first towards the second; its outline
    #: and positions on it are along them.
    turn: float = 0.0
    #: A turned item's other faces, and those of what is on them (place.md, "A turned item's faces"): everything above
    #: is the face with its item upright, and this motion moves it onto the part.
    local: Motion | None = None

    @property
    def half(self) -> Point:
        return self.outline.half

    @property
    def placed_frame(self) -> FaceFrame:
        """Its frame on the part: its own, moved by its item's motion where it has one."""
        return self.frame if self.local is None else self.local.frame(self.frame)

    @functools.cached_property
    def frame(self) -> FaceFrame:
        """Its centre, its first and second axes and its outward normal, turned in its plane by its ``turn``."""
        frame = FaceFrame.of_names(self.centre, self.axes[0], self.axes[1], self.normal)
        if self.turn == 0.0:
            return frame
        c, s = turn(self.turn)
        u, v = frame.u, frame.v
        return FaceFrame(frame.origin, _add(_scale(u, c), v, s), _add(_scale(u, -s), v, c), frame.n)

    def frame_at(self, at: Point) -> FaceFrame:
        """The face's frame at the point of its plane at ``at`` (item 3a's placeable face)."""
        frame = self.frame
        return FaceFrame(frame.point(*at), frame.u, frame.v, frame.n)


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

    @functools.cached_property
    def frame(self) -> FaceFrame:
        """The centre of its end at the smaller coordinate; the ways out at 0 and 90 degrees round it; its axis."""
        u, v = TURN_AXES[self.axis]
        return FaceFrame.of_names(self.start, u, v, self.axis)

    def frame_at(self, turn: Point, along: float) -> FaceFrame:
        """The side's frame at a point on it (item 3a): ``turn`` its angle's cosine and sine, ``along`` from its middle.

        Its origin is on the side; ``n`` the way out of the material (out of a
        rod, into a bore), ``v`` the axis and ``u`` round it.
        """
        frame = self.frame
        c, s = turn
        radial = _add(_add((0.0, 0.0, 0.0), frame.u, c), frame.v, s)
        middle = frame.level(self.start) + self.length / 2 + along
        point = _add(frame.at_level(self.start, middle), radial, self.radius)
        direction = (
            radial
            if self.outward
            else (-radial[0] + 0.0, -radial[1] + 0.0, -radial[2] + 0.0)
        )
        around = _add(_add((0.0, 0.0, 0.0), frame.u, -s), frame.v, c)
        if not self.outward:
            around = (-around[0] + 0.0, -around[1] + 0.0, -around[2] + 0.0)
        return FaceFrame(point, around, frame.n, direction)

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
    #: Turned in its face's plane (``place.turn``): the cosine and sine of the turn from the face's first axis.
    turn: Point | None = None
    #: Leaning from square to its flat face (``tilt``): its own direction, the face's normal turned towards the lean
    #: (``direction`` stays the face's); a cut's ``span`` is along it, from its point.
    lean: Vec | None = None
    #: On a turned item's face (place.md, "A turned item's faces"): the motion that takes it as placed upright
    #: (``local``) onto the part; its point, direction, box and lean are the part's.
    frame: Motion | None = None
    local: Copy | None = None


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
    return isinstance(end_of(item), ThroughAll)


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


def _entry(kind: str) -> PlaceKind:
    """The kind's entry in the ``place`` registry, asked when placing, never when this module is imported: the kinds' modules use this module's own faces, copies and materials."""
    from .items.place import PLACE

    return PLACE[kind]


def _box_edges(which: str, up: str, bottom: bool) -> tuple[tuple[str, str], ...]:
    """A box's edges ``which`` (a block's, a post's, a rib's, a tab's), by the two faces each lies between; ``bottom``: its bottom edges too, and all twelve (a block's)."""
    down = opposite(up)
    sides = [d for d in DIRECTIONS if d[1] != up[1]]
    vertical = tuple(
        (a, b) for n, a in enumerate(sides) for b in sides[n + 1 :] if a[1] != b[1]
    )
    sets: dict[str, tuple[tuple[str, str], ...]] = {
        "vertical": vertical,
        "top": tuple((up, s) for s in sides),
    }
    if bottom:
        sets["bottom"] = tuple((down, s) for s in sides)
        sets["all"] = sets["vertical"] + sets["top"] + sets["bottom"]
    return sets.get(which, ())


def _box_body(
    item: Item,
    point: Vec,
    up: str,
    sizes: Mapping[str, float],
    height: float,
    under: tuple[tuple[Outline, ...], Material] | None,
    faces: dict[str, Face],
    faced: bool = True,
) -> tuple[Vec, Vec]:
    """A box standing on a face: ``sizes`` along the face's axes, ``height`` up; ``faced``, its six faces too (a region has none)."""
    lo, hi = _box(point, up, sizes, height)
    if faced:
        across = {**sizes, up[1]: height}
        faces.update(_box_faces(lo, hi, across))
        top = faces[up]
        assert isinstance(top, FlatFace)
        faces[up] = FlatFace(
            up, top.centre, up, top.axes, top.outline, _far(Solid(height), under)
        )
    return lo, hi


def _rod_body(item: Item, layout: _Layout, key: tuple[str, int], point: Vec, up: str, axes: tuple[str, str],
              under: tuple[tuple[Outline, ...], Material] | None, faces: dict[str, Face], length: float, base: float,
              top_r: float, inner: float, *, foot_face: bool = True, tapered: bool = False,
              bored: bool = False) -> tuple[Vec, Vec]:  # fmt: skip
    """A round body or boss: ``base`` its radius at its foot, ``top_r`` at its far end, ``inner`` its bore's, ``length`` along its axis; ``foot_face``, its foot a face of its own (not a boss's); ``tapered``, its side closed (a cone's); ``bored``, a bore (a tube's)."""
    a1, a2 = axes
    u = unit(up)
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
            (Outline.disc(small, _in_plane(far_end, plane)),) if top_r > base else ()
        )
        faces["+end"] = FlatFace("+end", far_end, up, plane, end_outline(far_end, top_r),
                                 _far(own, under, within))  # fmt: skip
    else:
        layout.close(key, "+end", "it comes to a point: it has no +end")
    if foot_face:  # a boss's foot is joined to the face, and is no face of its own
        bottom: Material = Solid(length)
        if base > top_r:
            bottom = Taper(_in_plane(point, plane), small, large, length)
        faces["-end"] = FlatFace(
            "-end", point, opposite(up), plane, end_outline(point, base), bottom
        )
    start = point if up[0] == "+" else far_end
    if tapered:
        layout.close(
            key,
            "side",
            "a cone's side is tapered: nothing is placed on it, for now",
        )
    else:
        faces["side"] = RoundSide("side", up[1], start, length, base, True, inner)
    if bored:
        faces["bore"] = RoundSide("bore", up[1], start, length, inner, False, base)
    return lo, hi


def _sequence(spec: PartSpec) -> list[Item]:
    """Every item that isn't a change to another, in the order made: each time, the earliest
    in the spec whose dependencies are all made."""
    makes = [i for i in spec.items if _entry(i.kind).made]
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
    return _entry(kind).edges(which, up)


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
        _entry(item.kind).read(item, layout)
    sequence = _sequence(spec)
    first = True
    for item in sequence:
        on = _on(item)
        if _entry(item.kind).is_body and on is None:
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
    if not _entry(target.kind).hollowable:
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
    if _entry(item.kind).axial:
        up = "+" + (_choice(item, "axis") or "z")
    origin = (0.0, 0.0, 0.0)
    return _body(item, layout, 0, None, origin, up, FLAT_AXES[up[1]], None)


# ----------------------------------------------------------------------
# Positions on a face (place.md)
# ----------------------------------------------------------------------
def _footprint(
    item: Item, diameters: Mapping[str, float], axes: tuple[str, str]
) -> Outline:
    """The item's outline on a flat face with these axes, centred on the origin of the face's coordinates (turned by its
    ``place.turn``).

    For a hole, its widest circle (its counterbore's or countersink's).
    """
    found = _entry(item.kind).footprint(item, diameters, axes)
    lean = _lean(item, axes)
    if lean is not None:
        return _leaning_foot(item, found, lean)
    turned = _turn_of(item)
    return found if turned is None else _turned(item, found, turned)


#: How far, at most, an item leans (place.md, "Leaning on the face"), for now (degrees).
_MOST_LEAN = 75.0
#: The sides of the polygon round a leaning round foot's ellipse (forge_spec.lean says why it is drawn so).
_LEAN_SIDES = 128


@dataclass(frozen=True)
class _Lean:
    """How an item leans: the cosine and sine of its tilt, its way in its face's coordinates (turned with it), and
    whether that is along its own first axis."""

    c: float
    s: float
    way: Point
    first: bool


def _lean(item: Item, axes: tuple[str, str]) -> _Lean | None:
    """How an item leans on a flat face with these axes; None if it says no tilt. Refused (PlaceError): a kind that
    doesn't lean, no way or a way off the face's axes, a tilt out of range, a countersink."""
    tilt = item.get("tilt")
    if not isinstance(tilt, Value):
        return None
    if not _entry(item.kind).leans:
        raise PlaceError(item.id, "a hole, a boss or a post leans on its face, nothing else")
    towards = item.get("tilt_towards")
    if not isinstance(towards, Choice):
        raise PlaceError(item.id, "a tilt says which way it leans")
    axis, sign = in_axes(towards.value[1], axes), (1.0 if towards.value[0] == "+" else -1.0)
    if axis not in axes:
        raise PlaceError(item.id, f"it leans towards {towards.value}, which isn't one of the face's axes {axes}")
    degrees = _angle(tilt)
    if not 0.0 < degrees <= _MOST_LEAN + 1e-9:
        raise PlaceError(item.id, f"it leans {degrees:g} degrees: more than 0, at most {_MOST_LEAN:g}, for now")
    if isinstance(item.get("countersink"), Countersink):
        raise PlaceError(item.id, "a countersunk hole doesn't lean yet")
    first = axis == axes[0]
    way = (sign, 0.0) if first else (0.0, sign)
    place = _place(item)
    if place is not None and place.turn is not None:
        c, s = turn(_angle(place.turn))
        way = (c * way[0] - s * way[1], s * way[0] + c * way[1])
    c, s = turn(degrees)
    return _Lean(c, s, way, first)


def _leaning_foot(item: Item, found: Outline, lean: _Lean) -> Outline:
    """A leaning item's foot: its cross-section's section by its face, drawn out along its lean by 1 / cos(tilt); a
    round one's ellipse as the polygon of its tangents (evenly round it, and where it reaches farthest along each of
    the face's axes); a post's rectangle, turned with it."""
    if found.shape == "rect":
        h1, h2 = found.half
        h1, h2 = (h1 / lean.c, h2) if lean.first else (h1, h2 / lean.c)
        place = _place(item)
        by = turn(_angle(place.turn)) if place is not None and place.turn is not None else (1.0, 0.0)
        return _turned(item, Outline.rect(h1, h2), by)
    if found.shape != "disc":
        raise PlaceError(item.id, "only a round or a rectangular foot leans")
    r = found.half[0]
    a, b = r / lean.c, r
    w1, w2 = lean.way
    q1, q2 = -w2, w1
    full = 2.0 * math.pi
    params = [full * k / _LEAN_SIDES for k in range(_LEAN_SIDES)]
    for x, y in ((a * w1, b * q1), (a * w2, b * q2)):  # where each coordinate is at its most
        t = fs.atan2(y, x)
        params += [t % full, (t + math.pi) % full]
    params.sort()
    kept = [t for k, t in enumerate(params) if k == 0 or t - params[k - 1] > 1e-9]
    if full - kept[-1] + kept[0] <= 1e-9:
        kept.pop()
    corners: list[Point] = []
    for k, t in enumerate(kept):
        nxt = kept[k + 1] if k + 1 < len(kept) else kept[0] + full
        m, d = (t + nxt) / 2.0, (nxt - t) / 2.0
        x, y = a * fs.cos(m) / fs.cos(d), b * fs.sin(m) / fs.cos(d)
        corners.append((x * w1 + y * q1, x * w2 + y * q2))
    return Outline.profile([Segment(corners[k], corners[(k + 1) % len(corners)]) for k in range(len(corners))])


def _turn_of(item: Item) -> Point | None:
    """The cosine and sine of an item's ``place.turn`` in its face's plane; None if it has none."""
    place = _place(item)
    if place is None or place.turn is None:
        return None
    if isinstance(item.get("tilt"), Value) and _entry(item.kind).leans:
        return turn(_angle(place.turn))  # it turns the way it leans
    if not _entry(item.kind).turnable(item):
        raise PlaceError(
            item.id,
            "a turn turns a slot, a rectangular pocket, a rib, a tab, a block, a post or a line of letters in its face's plane",
        )
    return turn(_angle(place.turn))


def _turned(item: Item, outline: Outline, by: Point) -> Outline:
    """An outline turned about the origin of the face's coordinates: its sides and arcs, each turned."""
    if outline.shape != "rect":
        raise PlaceError(item.id, "only a rectangle, rounded or not, is turned")
    c, s = by
    angle = fs.atan2(s, c)

    def at(p: Point) -> Point:
        return (c * p[0] - s * p[1], s * p[0] + c * p[1])

    return Outline.profile([Segment(at(q.a), at(q.b)) if isinstance(q, Segment)
                            else Arc(at(q.centre), q.radius, q.start + angle, q.sweep) for q in outline.pieces()])  # fmt: skip


def _sized(
    item: Item, axes: tuple[str, str], along: str | None, long: float, short: float
) -> Outline:
    """A long box's footprint: ``long`` along ``along`` (one of the face's ``axes``), ``short`` across it."""
    a1, _ = axes
    along = None if along is None else in_axes(along, axes)
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
            first = fs.atan2(here[1] - c[1], here[0] - c[0])
            last = fs.atan2(segment.to[1] - c[1], segment.to[0] - c[0])
            sweep = ((first - last) if segment.clockwise else (last - first)) % (
                2 * math.pi
            )
            whole = (
                sweep <= 1e-12
            )  # an arc back to where it starts goes all the way round
            sweep = 2 * math.pi if whole else sweep
            start = last if segment.clockwise and not whole else first
            sides.append(Arc(c, fs.dist(here, c), start, sweep))
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
            abs(p[1] - height) <= TOL and min(fs.dist(p, e) for e in end.ends()) > 1e-6
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
    return _entry(item.kind).extent(item, foot)


def _covering(
    item: Item, diameters: Mapping[str, float], face: FlatFace
) -> Outline | None:
    """What an item covers on a flat face, centred on the origin of the face's coordinates: its footprint, or a line of letters' ink's box (None: spaces alone).

    A line of letters is placed by its box (text.md), but its ink reaches
    past it (a j's tail, an f's hook): its ink must lie on the face
    (docs/V2-stage4.md, 7.1). The letters run left to right along up (the
    face's second axis) cross outward.
    """
    if _lean(item, face.axes) is not None:  # leaning, it covers its foot: its section by the face
        return _footprint(item, diameters, face.axes)
    found = _entry(item.kind).covers(item, diameters, face)
    turned = _turn_of(item)
    if found is None or turned is None or found.shape == "profile":  # a kind's covering made of its footprint is turned
        return found
    return _turned(item, found, turned)


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


def _pattern_entry(mode: str) -> PatternPlace:
    """The pattern mode's entry in the ``place`` role's modes, asked when placing (as :func:`_entry`)."""
    from .items.place.pattern import PATTERN_PLACE

    return PATTERN_PLACE[mode]


def _flat_positions(item: Item, face: FlatFace, layout: _Layout) -> list[Point]:
    """Every copy's centre on a flat face, in the face's coordinates, in the order they are made."""
    place = _place(item)
    if place is not None:
        place = _named_by(place, face.axes)
    a1, a2 = face.axes
    axes_given = dict(place.axes) if place else {}
    pattern = place.pattern if place else None
    if place is not None and place.angle is not None:
        raise PlaceError(
            item.id, "an angle places an item round a round side, not on a flat face"
        )
    if place is not None and place.turn is not None and place.concentric:
        raise PlaceError(
            item.id, "a turned item is placed along the face's axes, not concentric"
        )
    for axis in axes_given:
        if axis not in face.axes:
            raise PlaceError(
                item.id, f"a position along {axis}, which face {face.name} doesn't have"
            )
    centre = face.frame.plane(face.centre)
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
    mode = _pattern_entry(pattern.kind)
    fixed = mode.fixed_axes(pattern, a1, a2)
    clash = sorted(set(axes_given) & fixed)
    if clash:
        raise PlaceError(
            item.id,
            f"its {pattern.kind} pattern sets where copies are along {clash[0]}",
        )
    kind = pattern.kind
    if mode.rect_only and face.outline.shape != "rect":
        raise PlaceError(
            item.id, f"a {kind} pattern needs a rectangular face; {face.name} isn't one"
        )
    if mode.at_the_corners:
        return [
            (centre[0] + d1, centre[1] + d2)
            for d1, d2 in mode.offsets(item, pattern, values, counts, half, a1, a2)
        ]
    if mode.along_its_axis and pattern.axis not in face.axes:
        raise PlaceError(
            item.id,
            f"its {kind} runs along {pattern.axis}, which face {face.name} doesn't have",
        )
    if mode.round:
        for axis, position in axes_given.items():
            if position.mode == "side" and position.to == "edge":
                raise PlaceError(
                    item.id,
                    f"a {kind} of copies is measured to its centre along {axis}, not to an edge",
                )
    offsets = mode.offsets(item, pattern, values, counts, half, a1, a2)
    anchor = [0.0, 0.0]
    for k, axis in enumerate(face.axes):
        given = axes_given.get(axis)
        if mode.pinned_along_axis and axis == pattern.axis:
            continue
        anchor[k] = _anchor(item, given, half[k], reach[k])
        if given is not None and given.mode == "side" and mode.nearest_from_edge:
            # From an edge, measured to the nearest copy along that axis (place.md, "Patterns").
            along = [o[k] for o in offsets]
            anchor[k] -= (
                min(along) if given.side and given.side[0] == "-" else max(along)
            )
    return [
        (centre[0] + anchor[0] + d1, centre[1] + anchor[1] + d2) for d1, d2 in offsets
    ]


def _named_by(place: Place, axes: tuple[str, str]) -> Place:
    """A place along a face's axes as the frame names them (:func:`in_axes`): its positions, their sides, and its
    pattern's values, counts and axis."""

    def name(n: str) -> str:
        before, _, last = n.rpartition("_")
        return n if last not in ("u", "v") else (before + "_" if before else "") + in_axes(last, axes)

    pattern = place.pattern
    if pattern is not None:
        pattern = replace(pattern, values={name(k): v for k, v in pattern.values.items()},
                          counts={name(k): c for k, c in pattern.counts.items()},
                          axis=None if pattern.axis is None else in_axes(pattern.axis, axes))  # fmt: skip
    positions = {in_axes(a, axes): replace(p, side=None if p.side is None else p.side[0] + in_axes(p.side[1:], axes))
                 for a, p in place.axes.items()}  # fmt: skip
    return replace(place, axes=positions, pattern=pattern)


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
    normal = face.frame.n
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
        found.append(face.frame.plane(other.point))
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
        _names_fit(item, face)
        motion = face.local if isinstance(face, FlatFace) else None
        if motion is None:
            made += _HOSTS[type(face)](item, face, host, len(hosts), layout, len(made))
            continue
        # A turned item's face (place.md, "A turned item's faces"): placed on as with that item upright, then moved.
        place = _place(item)
        if (place is not None and place.concentric) or item.id in layout.shells:
            raise PlaceError(item.id, "on a turned item's face, nothing is concentric with another or hollowed, yet")
        upright = replace(face, local=None)
        for copy in _HOSTS[FlatFace](item, upright, host, len(hosts), layout, len(made)):
            made.append(_moved_copy(copy, motion, layout))
    count = item.get("count")
    if isinstance(count, Count) and count.n != len(made):
        raise PlaceError(
            item.id, f"its count is {count.n}, but it is placed {len(made)} times"
        )
    return tuple(made)


def _moved_copy(copy: Copy, motion: Motion, layout: _Layout) -> Copy:
    """A copy placed upright on a turned item's face, moved by that item's motion: its point, direction, box and lean
    on the part, and its own faces moved with it (a round side, which turns with it, takes nothing yet)."""
    key = (copy.item, copy.index)
    for name, found in list(layout.faces.get(key, {}).items()):
        if isinstance(found, FlatFace):
            layout.faces[key][name] = replace(found, local=motion if found.local is None else motion.after(found.local))
        else:
            layout.close(key, name, "it is on a turned item's face: nothing is placed round its side, yet")
    lo, hi = motion.box(copy.lo, copy.hi) if copy.lo is not None and copy.hi is not None else (None, None)
    return replace(copy, point=motion.point(copy.point), direction=motion.vector(copy.direction), lo=lo, hi=hi,
                   lean=None if copy.lean is None else motion.vector(copy.lean), frame=motion, local=copy)  # fmt: skip


def _names_fit(item: Item, face: Face) -> None:
    """A turned face's axes are named only by its own, u and v; a round side's by neither (place.md, "Where on the
    face")."""
    named = {axis for _, axis in axis_names(item)}
    if isinstance(face, FlatFace) and (face.turn != 0.0 or face.local is not None) and named - {"u", "v"}:
        raise PlaceError(item.id, f"its face is turned with what it is on: it names its axes by the part's {sorted(named)}")
    if isinstance(face, RoundSide) and named & {"u", "v"}:
        raise PlaceError(item.id, "u and v are a flat face's own axes, not a round side's")


def _on_flat(item: Item, face: Face, host: tuple[str, int, str], host_copies: int, layout: _Layout,
             first: int) -> list[Copy]:  # fmt: skip
    assert isinstance(face, FlatFace)
    return _flat_copies(item, face, host, host_copies, layout, first)


def _on_round(item: Item, face: Face, host: tuple[str, int, str], host_copies: int, layout: _Layout,
              first: int) -> list[Copy]:  # fmt: skip
    assert isinstance(face, RoundSide)
    return _round_copies(item, face, host, layout, first)


#: Each kind of face an item can be put on (item 3a's placeable faces), by its class: how its copies are placed.
_HOSTS = {FlatFace: _on_flat, RoundSide: _on_round}


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
    if _entry(item.kind).is_body:
        if not overlap([foot, outline]):
            raise PlaceError(item.id, f"at {at}, it doesn't meet the face it stands on")
        return
    if foot.within(outline):
        return
    if outline.shape == "ring" and _entry(item.kind).taken:
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
    turned = _turn_of(item)
    if place is not None and place.concentric:
        if turned is not None:
            raise PlaceError(
                item.id, "a turned item is placed along the face's axes, not concentric"
            )
        positions = _concentric(item, face, host, host_copies, layout)
    else:
        positions = _flat_positions(item, face, layout)
    taken = _entry(item.kind).taken
    made: list[Copy] = []
    for n, (p1, p2) in enumerate(positions):
        point = face.frame_at((p1, p2)).origin
        assert face.frame.level(point) == face.frame.level(face.centre)
        _lies_on(item, face, (p1, p2), layout)
        index = first + n
        if taken:
            made.append(_flat_cut(item, face, host, index, point, layout))
        else:
            made.append(
                _standing(
                    item, face, host, index, point, face.normal, face.axes, layout
                )
            )
        lean = _lean(item, face.axes)
        degrees = _as_placed(item, face)
        if lean is not None:
            made[-1] = replace(_leaning_copy(item, made[-1], face, lean, layout),
                               turn=None if degrees is None else turn(degrees))  # fmt: skip
        elif degrees is not None:
            made[-1] = _turned_copy(item, made[-1], face, (p1, p2), degrees, layout)
    return made


def _as_placed(item: Item, face: FlatFace) -> float | None:
    """An item's turn as placed, in degrees from its face's axes as the part names them: its own (``place.turn``) and,
    on a turned face, the face's besides (place.md, "A turned item's far face"); None if neither turns it."""
    place = _place(item)
    own = _angle(place.turn) if place is not None and place.turn is not None else None
    if face.turn == 0.0:
        return own
    return face.turn + (own or 0.0)


def _leaning_copy(item: Item, copy: Copy, face: FlatFace, lean: _Lean, layout: _Layout) -> Copy:
    """A copy leaning on its face (place.md, "Leaning on the face"), on a face with the same material under all of
    it, ``T`` deep: its own direction; a cut's span along it, from its point (right through, until its whole circle is
    past the far side: ``(T + r sin) / cos``); a standing one's box round its foot and its far end, and what it
    reaches back into the face from its foot (its half size along its lean times tan) held to ``T``. Every face it
    has is closed, as a turned item's is."""
    thick = same_under(face)
    if thick is None:
        raise PlaceError(item.id, "it leans on a face without the same material under all of it: not yet")
    n = face.frame.n
    a1, a2 = face.frame.u, face.frame.v
    w = tuple(lean.way[0] * a1[k] + lean.way[1] * a2[k] for k in range(3))
    u = (lean.c * n[0] + lean.s * w[0], lean.c * n[1] + lean.s * w[1], lean.c * n[2] + lean.s * w[2])
    key = (item.id, copy.index)
    for name in list(layout.faces.get(key, {})) + [n_ for n_ in KINDS[item.kind].faces if n_ not in layout.faces.get(key, {})]:
        if name not in layout.closed.get(key, {}):
            layout.close(key, name, "it leans on its face: nothing is placed on a leaning item's faces, for now")
    if _entry(item.kind).taken:
        r = layout.diameters[item.id] / 2
        if _through(item):
            depth = (thick + r * lean.s) / lean.c
        else:
            depth = _mm(item, "depth")
            if depth * lean.c + r * lean.s > thick + TOL:
                raise PlaceError(item.id, "leaning, it is deeper than the material under it")
        return replace(copy, span=(0.0, depth), lean=u)
    height = _mm(item, "height")
    foot = _entry(item.kind).footprint(item, layout.diameters, face.axes)
    across = (-lean.way[1], lean.way[0])
    q = tuple(across[0] * a1[k] + across[1] * a2[k] for k in range(3))
    p = copy.point
    top = tuple(p[k] + height * u[k] for k in range(3))
    if foot.shape == "rect":
        along, other = (foot.half[0], foot.half[1]) if lean.first else (foot.half[1], foot.half[0])
        if along * lean.s / lean.c > thick - TOL:
            raise PlaceError(item.id, "leaning, its foot reaches back into the face past the material under it")
        tilted = tuple(lean.c * w[k] - lean.s * n[k] for k in range(3))
        points = [tuple(c_[k] + i * h * x[k] + j * other * q[k] for k in range(3))
                  for c_, h, x in ((p, along / lean.c, w), (top, along, tilted)) for i in (-1, 1) for j in (-1, 1)]  # fmt: skip
        lo = tuple(min(pt[k] for pt in points) for k in range(3))
        hi = tuple(max(pt[k] for pt in points) for k in range(3))
    else:
        r = foot.half[0]
        if r * lean.s / lean.c > thick - TOL:
            raise PlaceError(item.id, "leaning, its foot reaches back into the face past the material under it")
        reach = [fs.hypot(r / lean.c * w[k], r * q[k]) for k in range(3)]
        cap = [r * math.sqrt(max(1.0 - u[k] * u[k], 0.0)) for k in range(3)]
        lo = tuple(min(p[k] - reach[k], top[k] - cap[k]) for k in range(3))
        hi = tuple(max(p[k] + reach[k], top[k] + cap[k]) for k in range(3))
    return replace(copy, lean=u, lo=(lo[0], lo[1], lo[2]), hi=(hi[0], hi[1], hi[2]))


def _turned_copy(item: Item, copy: Copy, face: FlatFace, at: Point, degrees: float, layout: _Layout) -> Copy:
    """A copy turned in its face's plane by ``degrees`` as placed (its own turn and its face's): its turn kept, as on a
    plane along the part's axes; a standing one's box round its footprint turned so. A round one is the same turned:
    its faces turned with its face, its far face standing (place.md, "A turned item's far face"), its others closed. A
    box's far face is turned with it, its own height of material under it and, wholly over a host with the same
    material under all of it, the host's; anywhere else it is closed, as every other face of a turned item is."""
    key = (item.id, copy.index)
    by = turn(degrees)
    entry = _entry(item.kind)
    faces = layout.faces.setdefault(key, {})
    foot = entry.footprint(item, layout.diameters, face.axes)
    round_ = not entry.turnable(item)
    if round_ and foot.shape not in ("disc", "ring"):
        raise PlaceError(item.id, "it is on a turned face, and its outline, which isn't round, doesn't turn yet")
    up = direction_of(copy.direction)
    far = _entry(item.kind).far(up) if up is not None and copy.lo is not None else None
    kept: FlatFace | None = None
    if entry.taken:
        if round_:  # a round cut is the same turned: its floor is along its face's axes
            for name, found in list(faces.items()):
                if isinstance(found, FlatFace):
                    faces[name] = replace(found, turn=face.turn)
            return replace(copy, turn=by)
        kept = _turned_floor(item, faces, face, degrees, layout)
    elif far is not None and isinstance(faces.get(far), FlatFace) and item.id not in layout.shells:
        kept = _turned_far(item, faces[far], face, at, degrees, round_)  # type: ignore[arg-type]
    motion = None
    if not entry.taken and not round_ and item.id not in layout.shells and copy.lo is not None:
        # A turned box's other faces are its own, turned with it: kept as they are upright, moved by its turn.
        e1, e2 = unit("+" + face.axes[0]), unit("+" + face.axes[1])
        square = (e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0])
        motion = Motion.about(copy.point, square, by)
    for name in list(faces) + [n for n in KINDS[item.kind].faces if n not in faces]:
        if (kept is not None and name == kept.name) or name in layout.closed.get(key, {}):
            continue
        found = faces.get(name)
        if motion is not None and name != far and isinstance(found, FlatFace) and not name.startswith("inner "):
            faces[name] = replace(found, local=motion)
        else:
            layout.close(key, name, "it is turned in its face: only a turned box's faces, or a round item's far face, "
                         "take anything, for now")  # fmt: skip
    if kept is not None:
        faces[kept.name] = kept
    if copy.lo is None or copy.hi is None:
        return replace(copy, turn=by)
    if not round_:
        foot = _turned(item, foot, by)
    lo, hi = list(copy.lo), list(copy.hi)
    middle = _in_plane(copy.point, face.axes)
    for k, axis in enumerate(face.axes):
        i = _INDEX[axis]
        lo[i] = middle[k] + foot.centre[k] - foot.half[k]
        hi[i] = middle[k] + foot.centre[k] + foot.half[k]
    return replace(copy, turn=by, lo=(lo[0], lo[1], lo[2]), hi=(hi[0], hi[1], hi[2]))


def _turned_floor(item: Item, faces: dict[str, Face], face: FlatFace, degrees: float, layout: _Layout) -> FlatFace | None:
    """A turned pocket's floor (pocket.md, place.md "A turned item's far face"): turned with it, its outline along its
    own axes about its centre, the material under its face less its depth under it, where its face has the same
    material under all of it; else None (closed)."""
    floor = faces.get("bottom")
    host = same_under(face)
    if not isinstance(floor, FlatFace) or host is None or not isinstance(floor.material, Less):
        return None
    turned = replace(floor, turn=degrees)
    c1, c2 = turned.frame.plane(floor.centre)
    foot = _entry(item.kind).footprint(item, layout.diameters, face.axes).moved(c1, c2)
    return replace(turned, outline=foot, material=Solid(host - floor.material.depth))


def _turned_far(item: Item, far: FlatFace, face: FlatFace, at: Point, degrees: float, round_: bool) -> FlatFace | None:
    """A turned item's far face, turned by ``degrees`` as it is: its outline moved to where its centre is along its
    turned axes. A round item's keeps the material its host gives it (it is turned as its host's face is); a box's has
    its own height and, wholly over a host with the same material under all of it, the host's too; else None."""
    turned = replace(far, turn=degrees)
    c1, c2 = turned.frame.plane(far.centre)
    o1, o2 = far.outline.centre
    outline = far.outline.moved(c1 - o1, c2 - o2)
    if round_:
        return replace(turned, outline=outline)
    host = same_under(face)
    if host is None:
        return None
    own = _turn_of(item)
    foot = _entry(item.kind).footprint(item, {}, face.axes)
    if own is not None:
        foot = _turned(item, foot, own)
    if not foot.moved(*at).within(face.outline):
        return None
    height = far.material.own if isinstance(far.material, Over) else far.material
    assert isinstance(height, Solid)
    return replace(turned, outline=outline, material=Solid(height.depth + host))


# ----------------------------------------------------------------------
# Cuts
# ----------------------------------------------------------------------
def _mouth(item: Item, layout: _Layout, face: FlatFace, at: Point) -> Outline:
    """The outline a cut goes in through: a hole's own circle, a line of letters' ink's box, or the cut's outline."""
    return _entry(item.kind).mouth(item, layout, face, at)


def _flat_cut(item: Item, face: FlatFace, host: tuple[str, int, str], index: int, point: Vec,
              layout: _Layout) -> Copy:  # fmt: skip
    at = face.frame.plane(point)
    mouth = _mouth(item, layout, face, at)
    entry = _entry(item.kind)
    embossed = entry.embossed(item)
    if _through(item):
        entry.cut_through(item)
        depth = most(face.material, [mouth])
        if depth <= TOL:
            raise PlaceError(
                item.id, "there is no material under its mouth to cut through"
            )
    else:
        depth = _mm(item, "depth")
    copy = Copy(item.id, index, host, point, face.frame.n, face.axes,
                span=(-depth, 0.0) if embossed else (0.0, depth))  # fmt: skip
    entry.after_cut(item, face, index, point, mouth, depth, layout)
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
    centre = _add(point, face.frame.n, -depth)
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
    entry = _entry(item.kind)
    if not entry.goes_round_side:
        raise PlaceError(
            item.id,
            f"only holes, bosses, posts, tabs and ribs go on a round side, not a {item.kind}",
        )
    place = _place(item)
    if place is not None and place.turn is not None:
        raise PlaceError(
            item.id, "a turn turns an item in a flat face's plane, not round a side"
        )
    axis = side.axis
    if place is not None and place.concentric:
        raise PlaceError(item.id, "nothing is concentric on a round side, for now")
    pattern = place.pattern if place else None
    if pattern is not None and not _pattern_entry(pattern.kind).round:
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
        extra = sorted(
            set(values)
            - ({"step"} if _pattern_entry(pattern.kind).steps_round else set())
        )
        if extra:
            raise PlaceError(item.id, f"round a side, a {pattern.kind} takes only a count"
                             + (" and a step" if _pattern_entry(pattern.kind).steps_round else "") + f", not {extra}")  # fmt: skip
        _needs(
            item,
            pattern,
            {**values, **counts},
            "count",
            *(("step",) if _pattern_entry(pattern.kind).steps_round else ()),
        )
        step = _pattern_entry(pattern.kind).round_step(values, counts)
        angles = [start + k * step for k in range(counts["count"])]
    zero, quarter = side.frame.u, side.frame.v
    made = []
    for n, angle in enumerate(angles):
        c, s = turn(angle)
        radial = _add(_add((0.0, 0.0, 0.0), zero, c), quarter, s)
        direction = (
            radial
            if side.outward
            else (-radial[0] + 0.0, -radial[1] + 0.0, -radial[2] + 0.0)
        )
        up, axes, reach_along = entry.round_frame(item, direction, axis, layout)
        along = _anchor(
            item, positions.get(axis), side.length / 2, (-reach_along, reach_along)
        )
        if abs(along) + reach_along > side.length / 2 + TOL:
            raise PlaceError(
                item.id,
                f"{along:g} mm along the side from its middle, it runs past the side's end",
            )
        point = side.frame_at((c, s), along).origin
        index = first + n
        made.append(
            entry.round_copy(
                item, side, host, index, point, direction, up, axes, layout
            )
        )
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
    entry = _entry(item.kind)
    if entry.is_body:
        if isinstance(face, RoundSide):
            raise PlaceError(item.id, "a body stands on a flat face")
        axis = _choice(item, "axis")
        if entry.axial and axis not in (None, up[1]):
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
    at = _in_plane(point, axes)
    section = section_of(item)
    ends = _entry(item.kind).ends(
        item, layout, key, point, up, axes, under, faces, section, at
    )
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
    entry = _entry(kind)
    key = (item.id, index)
    on_side = isinstance(face, RoundSide)
    under = _host_material(face)
    faces: dict[str, Face] = {}
    u = unit(up)
    lo, hi = entry.body(item, layout, key, host, point, up, axes, under, faces)
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
        joined = "-end" if entry.joined_by_end else opposite(up)
        if joined in layout.faces[key]:
            layout.close(key, joined, f"it is joined to {host[0]} by this face")
    if on_side:
        far = entry.far(up)
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
    thin = None if thin is None else in_axes(thin, FLAT_AXES[up[1]])
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
    entry = _entry(kind)
    allowed = entry.openable(item)
    if not open_faces <= allowed:
        raise PlaceError(shell.id, f"a shell of a {kind} can leave open {sorted(allowed) or 'nothing'}, "
                         f"not {sorted(open_faces - allowed)}")  # fmt: skip
    for name in sorted(open_faces):
        layout.close(key, name, f"{shell.id} leaves it open")

    entry.hollow(
        item, layout, key, base, up, lo, hi, shell, thickness, floor, open_faces
    )


def _walls(
    names: Sequence[str],
    shell: Item,
    open_faces: frozenset[str],
    floor: float | None,
    thickness: float,
) -> dict[str, float]:
    """A block's or a cylinder's walls, by the faces ``names`` it may have closed: each the shell's thickness, or its floor's (the wall opposite an open face)."""

    def other_end(name: str) -> str:
        return {"+end": "-end", "-end": "+end"}.get(name) or opposite(name)

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
    return walls


# ----------------------------------------------------------------------
# The order the part is made in (frame.md)
# ----------------------------------------------------------------------
def _order(sequence: Sequence[Item], layout: _Layout) -> tuple[Step, ...]:
    """Each item in the order made: a hollowed body whole (itself, its own edges' roundings,
    its hollow, its rim's roundings), then every other rounding, chamfer and thread."""
    steps: list[Step] = []
    rounds = [i for i in layout.spec.items if _entry(i.kind).rounds_edges]
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
        if _entry(i.kind).made_last and i.id not in made
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
        if not _entry(placed.kinds[key[0]]).cavity_boxed:
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
    o1, o2 = face.frame.plane(centre)
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
            placed, theirs_frame = face.placed_frame, getattr(other, "frame", None)
            checks = (
                ("centre", placed.origin, getattr(other, "centre", None)),
                ("frame", (*placed.u, *placed.v, *placed.n),
                 None if theirs_frame is None else (*theirs_frame.u, *theirs_frame.v, *theirs_frame.n)),
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
                ("turn", face.turn, getattr(other, "turn", 0.0)),
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
