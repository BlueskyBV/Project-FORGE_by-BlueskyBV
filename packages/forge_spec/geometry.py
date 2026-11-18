"""The geometry the placement solver reasons with: faces, outlines, fits, material.

Everything here is exact and axis-aligned:

- a **flat face** is a rectangle (whose corners may be rounded, each by its
  own radius: a round-ended tab rounds two of them), a disc, a ring, or an
  outline of lines and arcs (an extrusion's end: :mod:`forge_spec.outline`);
- a **side face** is the round side of a cylinder, a tube or a bore;
- an **outline** is what an item covers on the face it is on, as rectangles
  and discs: a round-ended slot is a rectangle and two discs, a pocket with
  rounded corners two rectangles and four discs. Every outline is centrally
  symmetric about the item's position;
- the **material** under a face is how far a cut can go before it breaks
  through: a plate's thickness, a shelled box's wall, a cone's height falling
  off towards its rim, a dome's height over each point of its base, a turned
  part's height at each distance from its axis.

Whether an outline lies on a face is decided exactly (see
:func:`outline_on_face`), never by bounding boxes, so a round-ended slot that
fits a disc isn't questioned and a square pocket whose corners stick out of it
is.

>>> face = FlatFace("+end", (0, 0, 10), "+z", ("x", "y"), "disc", (10, 10))
>>> outline_on_face(face, slot_outline(19.5, 6, along_first=True), 0, 0)
True
>>> outline_on_face(face, (rect(9.75, 3),), 0, 0)
False
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from functools import cached_property
from itertools import pairwise

from forge_numeric import scalar as fs

from .frames import Frame, Rigid, cos_sin
from .outline import Arc, Line, Shape, boundary_within, meet, turned_depth

__all__ = [
    "EPS",
    "BallFace",
    "ConeFace",
    "DepthModel",
    "Dome",
    "Face",
    "FlatFace",
    "Footprint",
    "Less",
    "Over",
    "Part",
    "SideFace",
    "Slant",
    "Source",
    "Taper",
    "Turned",
    "Vec",
    "add_material",
    "bbox",
    "centred",
    "cone_sag",
    "copies_overlap",
    "disc",
    "face_footprint",
    "far_near",
    "first_close_pair",
    "fits_somewhere",
    "footprint_on_face",
    "inside_hole",
    "least_material_under",
    "material_at",
    "most_material_under",
    "outline_meets_face",
    "outline_on_face",
    "outline_within",
    "reach",
    "rect",
    "rounded_rect",
    "shape_meets_face",
    "shape_on_face",
    "shape_reach",
    "side_material",
    "side_most_material",
    "slot_outline",
    "touches_edge",
    "uniform",
]

Vec = tuple[float, float, float]
EPS = 1e-6

#: The quadrants of a face's two axes, in the order a face's corner radii are given.
QUADRANTS = ((1, 1), (-1, 1), (-1, -1), (1, -1))


Source = tuple[str, str]  # (item id, field name)


@dataclass(frozen=True)
class Taper:
    """The material under a cone's end, away from its centre.

    All of it out to radius ``flat`` (the smaller end's); from there the
    cone's own ``own`` falls in a straight line to nothing at ``edge`` (the
    larger end's). Only the cone's own material falls away: what it stands
    on is under it only within ``flat``.
    """

    flat: float
    edge: float
    own: float


@dataclass(frozen=True)
class Dome:
    """The material under a dome's flat face: its height above each point."""

    radius: float


@dataclass(frozen=True)
class Turned:
    """The material under a revolution's end: from the end along the line at each distance from the axis to where it leaves the half outline.

    ``shape`` is the half outline (distance from the axis, height); ``top``
    whether the face is its greatest height's end. ``extra`` is what is
    under it besides, where the line runs right through the revolution (the
    host's material, under the far end of one standing on a face).
    """

    shape: Shape
    top: bool
    extra: float = 0.0


@dataclass(frozen=True)
class Slant:
    """The material under a leaning item's far face (V2-stage4b-0c.md 3.3, 1b's step 5, with item 2b): its own, from
    each point back along its axis to the face it leans on. That is the face's ``depth_below`` at its centre, on the
    axis, and ``tan`` (its tilt's) less for each millimetre along ``way`` (a unit vector in the face's coordinates, the
    way it leans): the face it leans on is that much nearer there."""

    way: tuple[float, float]
    tan: float


DepthModel = Taper | Dome | Turned | Slant


@dataclass(frozen=True)
class Over:
    """What is under a standing item's far face besides its own material: its host's, where it is over its host's face.

    frame.md: at a point over the host's face, the material under the
    host's face there too; over an overhang, only the item's own. ``host``
    is the face it stands on, in the same axes, or with this face turned in
    its plane from them (a turned item's far face: the difference of their
    ``turn``); ``at`` this face's centre on it, along the host's axes from
    its centre. The host's material
    adds only where the item's own runs right down to its foot: a cone's
    within its smaller end (its :class:`Taper`'s ``flat``), a revolution's
    where the line runs right through it (its :class:`Turned`).
    """

    host: FlatFace
    at: tuple[float, float]


def _into_host(footprint: Footprint, p1: float, p2: float, turn: float) -> list[tuple[Footprint, float, float]]:
    """A footprint at (p1, p2) on a face turned ``turn`` degrees from its host's axes (a turned item's far face, over
    its host: V2-stage4b-0c.md 3.3, step 5), in the host's axes about the face's centre: its outline turned with it, or
    each of its parts on its own, a disc's at its centre turned so, a rectangle's an outline turned with it."""
    c, s = cos_sin(turn)
    if isinstance(footprint, Shape):
        return [(footprint.moved(p1, p2).turned(c, s), 0.0, 0.0)]
    found: list[tuple[Footprint, float, float]] = []
    for part in footprint:
        a1, a2 = p1 + part.centre[0], p2 + part.centre[1]
        q1, q2 = c * a1 - s * a2, s * a1 + c * a2
        if part.disc:
            found.append(((Part((0.0, 0.0), part.half, True),), q1, q2))
        else:
            found.append((Shape.rect((0.0, 0.0), part.half).turned(c, s), q1, q2))
    return found


@dataclass(frozen=True)
class Less:
    """A pocket's floor: the material under the face it was cut into, less its depth (frame.md).

    ``base`` is that face, in the same axes; ``at`` this face's centre on it,
    along those axes from its centre.
    """

    base: FlatFace
    at: tuple[float, float]
    depth: float


@dataclass(frozen=True)
class FlatFace:
    """A flat face: a rectangle (corners possibly rounded), a disc, a ring or an outline.

    ``depth_below`` is the item's own material under the face's centre,
    along -normal. ``depth_model`` says how it changes away from the centre:
    None (it doesn't), a :class:`Taper`, a :class:`Dome` or a :class:`Turned`;
    ``over``, what is under it besides, on its host (a standing item's far
    face); ``less``, for a pocket's floor, the material it is all there is of
    (``depth_below`` is then its least). Read the material under a footprint
    with :func:`least_material_under` and :func:`most_material_under`.
    ``room`` is how far something standing on it may rise before it meets a
    wall (a hollow's far side); outside a hollow there is no limit.

    So that a problem can be traced to the values it rests on, a face keeps
    the (item, field) pairs its size comes from along each of its axes
    (``axis_sources``), and those its material comes from (``depth_sources``).
    """

    name: str
    centre: Vec
    normal: str  # "+z"
    axes: tuple[str, str]
    shape: str  # "rect", "disc", "annulus", "profile"
    half: tuple[float, float]  # rect half sizes along axes; disc: (r, r)
    inner_radius: float = 0.0
    depth_below: float = 0.0
    #: A rectangle's corner radii, by quadrant: (+, +), (-, +), (-, -), (+, -).
    corners: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    depth_model: DepthModel | None = None
    axis_sources: tuple[tuple[Source, ...], tuple[Source, ...]] = ((), ())
    depth_sources: tuple[Source, ...] = ()
    room: float = math.inf
    room_sources: tuple[Source, ...] = ()
    #: A "profile" face's outline, in the face's axes about its centre (the middle of its box).
    profile: Shape | None = None
    over: Over | None = None
    less: Less | None = None
    #: A turned item's far face, and what stands on or is cut in one (schema 1.4; V2-stage4b-0c.md, 3.3, 1b's third
    #: move): its axes turned in its plane by this many degrees from the part's ``axes``, the first towards the second,
    #: and the (item, field) pairs the turn comes from.
    turn: float = 0.0
    turn_sources: tuple[Source, ...] = ()
    #: Named by its own axes, ``("u", "v")`` (an item that names them so): the part's names for them before its turn.
    named: tuple[str, str] | None = None
    #: A face of a turned or leaning item, or of what is on one (V2-stage4b-0c.md 3.3, 1b's third move, step 2): the
    #: motion that takes its item as it would stand upright onto the part. Its ``normal``, ``axes`` and ``turn`` are
    #: then its own there (its ``centre`` is the part's): it is placed on as that upright face is, and moved so.
    local: Rigid | None = None

    @property
    def sources(self) -> tuple[Source, ...]:
        """Every (item, field) pair the face's size comes from."""
        return self.axis_sources[0] + tuple(
            s for s in self.axis_sources[1] if s not in self.axis_sources[0]
        )

    @property
    def part_axes(self) -> tuple[str, str]:
        """The part's names for its axes before any turn: ``axes``, or what ``u`` and ``v`` name."""
        return self.named or self.axes

    @cached_property
    def frame(self) -> Frame:
        """Its centre, its first and second axes and its outward normal (:mod:`forge_spec.frames`): turned in its plane
        by its ``turn``; a face of a turned or leaning item's, moved with it."""
        if self.local is not None:
            return self.local.frame(self.upright().frame)
        a1, a2 = self.part_axes
        frame = Frame.of_names(self.centre, a1, a2, self.normal)
        return frame if self.turn == 0.0 else frame.turned(*cos_sin(self.turn))

    @property
    def axes_are_the_parts(self) -> bool:
        """Whether its axes run along the part's: not turned, nor a turned or leaning item's (``local``)."""
        return self.turn == 0.0 and self.local is None

    def upright(self) -> FlatFace:
        """A face of a turned or leaning item as it would be with its item upright (``local`` undone); any other face
        as it is."""
        if self.local is None:
            return self
        return replace(self, centre=self.local.inverse().point(self.centre), local=None)

    def spelled(self, names: tuple[str, str]) -> FlatFace:
        """The face with its axes named ``names`` (``("u", "v")``), its frame unchanged."""
        return self if names == self.axes else replace(self, axes=names, named=self.part_axes)

    def frame_at(self, position: tuple[float, float]) -> Frame:
        """The face's frame at a point on it, given in its own coordinates (``u``, ``v``) from its centre (item 3a)."""
        frame = self.frame
        return Frame(frame.at(*position), frame.u, frame.v, frame.n)

    @property
    def symmetric(self) -> bool:
        """Centrally symmetric and convex: a shape that fits anywhere fits at the centre."""
        if self.shape == "disc":
            return True
        c = self.corners
        return self.shape == "rect" and c[0] == c[2] and c[1] == c[3]

    # Item 3a's placeable face, second part (V2-stage4b-0c.md, 3.4): where on the face a footprint lies (its outline),
    # and the material under one, asked of the face itself. A footprint is an item's foot: its outline as parts, or of
    # lines and arcs, in the face's axes, at a point given in its own coordinates from its centre.
    def holds(self, footprint: Footprint, at: tuple[float, float], *, cut: bool = False) -> bool:
        """Whether a footprint at ``at`` lies wholly on the face's material; a cut's on a ring may cover its hole (a
        step round the bore)."""
        if isinstance(footprint, Shape):
            return shape_on_face(self, footprint, *at)
        return outline_on_face(self, footprint, *at, cut=cut)

    def meets(self, footprint: Footprint, at: tuple[float, float]) -> bool:
        """Whether a footprint at ``at`` shares some area with the face (a body may overhang the face it stands on)."""
        return _footprint_meets(self, footprint, *at)

    def fits_somewhere(self, parts: Sequence[Part], *, cut: bool = False) -> bool | None:
        """Whether an outline fits anywhere on the face; None when the face can't settle it on its own."""
        return fits_somewhere(self, parts, cut=cut)

    def in_its_hole(self, parts: Sequence[Part], at: tuple[float, float]) -> bool:
        """Whether an outline at ``at`` lies wholly in a ring's hole: a cut there cuts nothing."""
        return inside_hole(self, parts, *at)

    def touches_its_edge(self, parts: Sequence[Part], at: tuple[float, float]) -> bool:
        """Whether a cut's outline at ``at`` touches the face's edge from inside, pinching the wall between to nothing."""
        return touches_edge(self, parts, *at)

    def material_under(self, footprint: Footprint, at: tuple[float, float]) -> float:
        """The least material under a footprint at ``at``: what a blind cut of that outline must fit in."""
        return least_material_under(self, footprint, *at)

    def most_material_under(self, footprint: Footprint, at: tuple[float, float]) -> float:
        """The most material under a footprint at ``at``: how far a cut of that outline through goes."""
        return most_material_under(self, footprint, *at)

    @property
    def uniform(self) -> bool:
        """Whether the same material is under every point of it: its own, with no model, host or base to it."""
        return uniform(self)


@dataclass(frozen=True)
class SideFace:
    """The round side of a body (``outward``) or of a bore (not ``outward``).

    ``wall`` is the material a radial cut meets: a solid rod's whole
    diameter, a tube's wall. So that a problem is traced to the values it
    rests on, the side keeps where its radius comes from (``radius_sources``),
    its length (``length_sources``) and its wall (``depth_sources``).
    """

    name: str
    axis: str  # "z"
    start: Vec  # centre of the end the axis starts from
    length: float
    radius: float
    outward: bool = True
    wall: float = 0.0
    radius_sources: tuple[Source, ...] = ()
    length_sources: tuple[Source, ...] = ()
    depth_sources: tuple[Source, ...] = ()
    #: The side of an item standing on a turned item's face (1b's third move, step 5.2): kept as it is with that item
    #: upright, and the motion that takes it onto the part.
    local: Rigid | None = None
    #: A round-ended tab's end (item 3b's fourth step; tab.md): the half of the side facing this way, its far end's;
    #: None for a whole side.
    half: str | None = None
    #: Behind such a half, how far the tab runs on, as wide as the half, to its foot.
    behind: float = 0.0

    def upright(self) -> SideFace:
        """The side as it is with its item upright (``local`` undone): its axis and start are already so."""
        return self if self.local is None else replace(self, local=None)

    @property
    def sources(self) -> tuple[Source, ...]:
        """Every (item, field) pair the side's size comes from."""
        return self.radius_sources + tuple(
            s for s in self.length_sources if s not in self.radius_sources
        )

    @property
    def reference(self) -> tuple[str, str]:
        """The axes 0 and 90 degrees round it point along (frame.md: round z, x then y; round x, y then z; round y, z then x)."""
        return _REFERENCE[self.axis]

    @cached_property
    def frame(self) -> Frame:
        """The centre of the end its axis starts from; ``u`` and ``v`` the ways out at 0 and 90 degrees round it, ``n`` its axis
        (moved onto the part by ``local``, where its item stands on a turned item's face)."""
        u, v = self.reference
        found = Frame.of_names(self.start, u, v, self.axis)
        return found if self.local is None else self.local.frame(found)

    # Item 3a's placeable face, second part: the material a cut along a radius of the side meets, the same wherever on
    # it, asked of the side itself (its foot, the cut's mouth, counts only by how far it reaches).
    def material_under(self, footprint: Footprint, at: tuple[float, float] = (0.0, 0.0)) -> float:
        """The least material a radial cut of that mouth meets: what a blind one must fit in. Into a round-ended tab's
        end, at ``at``'s angle (degrees), in the tab: through its half-disc and on into its straight part, until it
        comes out of the tab's side or reaches its foot."""
        if self.half is not None:
            return min(self._half_exits(_reach_of(footprint), at[0]))
        return side_material(self, _reach_of(footprint))

    @property
    def middle(self) -> float:
        """A half's middle: the angle round its axis (degrees, from its first reference axis towards its second) of the
        way it faces."""
        assert self.half is not None
        u, v = self.reference
        quarter = {("+", u): 0.0, ("+", v): 90.0, ("-", u): 180.0, ("-", v): 270.0}
        return quarter[(self.half[0], self.half[1])]

    def _half_exits(self, r: float, angle: float) -> tuple[float, float]:
        """How far a radial cut ``r`` in radius at ``angle`` (degrees) into a round-ended tab's end stays in the tab, along
        the lines through its mouth's two sides round the axis, from the line square to it at its point: the tab's
        section across its thickness is convex, so along the rest it stays in further."""
        c, s = cos_sin(angle - self.middle)  # off the half's middle: along it (y), across it (x)
        found = []
        for side in (-r, r):
            x0, y0 = self.radius * s + side * c, self.radius * c - side * s
            found.append(_tab_exit(self.radius, self.behind, x0, y0, -s, -c))
        return found[0], found[1]

    def most_material_under(self, footprint: Footprint, at: tuple[float, float] = (0.0, 0.0)) -> float:
        """How far a radial cut of that mouth through the side's wall goes: until it is out all across its mouth."""
        return side_most_material(self, _reach_of(footprint))

    def frame_at(self, turn: tuple[float, float], along: float) -> Frame:
        """The side's frame at a point on it (item 3a): ``turn`` the cosine and sine of its angle round the axis, ``along``
        how far from the middle along it.

        Its origin is on the side; ``n`` the way out of the material (out of a
        rod, into a bore), ``v`` the axis and ``u`` round it, ``u x v = n``
        on the outside of a rod.
        """
        frame = self.frame
        r = frame.radial(*turn)
        centre = _plus(frame.origin, frame.n, self.length / 2 + along)
        origin = _plus(centre, r, self.radius)
        outward = r if self.outward else (-r[0], -r[1], -r[2])
        around = frame.radial(-turn[1], turn[0])
        return Frame(
            origin,
            around if self.outward else (-around[0], -around[1], -around[2]),
            frame.n,
            outward,
        )


@dataclass(frozen=True)
class BallFace:
    """A ball's or a dome's curved surface (item 3b's second step; sphere.md): its centre, the way its pole lies from it
    (``up``: the way the ball stands, its own +z as the first body) and its radius; whether it is a dome (the half of
    the ball on its pole's side), and whether it is ``standing`` on a face (a whole ball so is ``seated``, its lower
    half in what it stands on). A point on it is at a ``latitude`` from its equator towards its pole and an angle round its pole
    (its longitude) from its zero meridian, the way round its pole its frame's ``u`` gives (frame.md: about z, +x).

    ``wall`` is the material a cut along its radius meets at its pole: a ball's diameter, a dome's radius.
    """

    name: str
    centre: Vec
    up: str  # "+z"
    radius: float
    dome: bool = False
    #: Whether it stands on a face (a dome on its flat face; a ball centred on the face, its lower half in it).
    standing: bool = False
    radius_sources: tuple[Source, ...] = ()
    #: The face of what stands on a turned item's face (as a round side's): kept as with that item upright, and the
    #: motion onto the part.
    local: Rigid | None = None

    @property
    def wall(self) -> float:
        return self.radius if self.dome else 2 * self.radius

    @property
    def sources(self) -> tuple[Source, ...]:
        return self.radius_sources

    @property
    def depth_sources(self) -> tuple[Source, ...]:
        return self.radius_sources

    @property
    def seated(self) -> bool:
        """A whole ball standing on a face: its lower half in what it stands on."""
        return self.standing and not self.dome

    @property
    def lowest(self) -> float:
        """The least latitude (degrees) what is on it may reach down to: its rim's on a dome, its equator's on a seated
        ball (below it is what it stands on); a free ball's south pole."""
        return 0.0 if self.dome or self.seated else -90.0

    def upright(self) -> BallFace:
        return self if self.local is None else replace(self, local=None)

    @cached_property
    def frame(self) -> Frame:
        """Its centre; ``u`` its zero meridian's way out at its equator, ``v`` a quarter round its pole from it, ``n``
        its pole's way (right-handed)."""
        a, b = _REFERENCE[self.up[1]]
        found = Frame.of_names(self.centre, "+" + a, self.up[0] + b, self.up)
        return found if self.local is None else self.local.frame(found)

    def frame_at(self, longitude: tuple[float, float], latitude: tuple[float, float]) -> Frame:
        """Its frame at a point on it (item 3a's placeable face): ``longitude`` and ``latitude`` the cosines and sines of
        the angles round its pole and up from its equator. Its origin is on the surface; ``n`` the way out, ``u`` east
        (round its pole) and ``v`` north (towards its pole), ``u x v = n``."""
        frame = self.frame
        (cl, sl), (cp, sp) = longitude, latitude
        out = tuple(cp * (cl * frame.u[i] + sl * frame.v[i]) + sp * frame.n[i] + 0.0 for i in range(3))
        east = tuple(-sl * frame.u[i] + cl * frame.v[i] + 0.0 for i in range(3))
        north = tuple(-sp * (cl * frame.u[i] + sl * frame.v[i]) + cp * frame.n[i] + 0.0 for i in range(3))
        origin = _plus(frame.origin, out, self.radius)  # type: ignore[arg-type]
        return Frame(origin, east, north, out)  # type: ignore[arg-type]

    # Item 3a's placeable face: the material a cut along its radius meets, at a latitude (degrees) of it.
    def material_under(self, footprint: Footprint, at: tuple[float, float] = (0.0, 90.0)) -> float:
        """The least material a radial cut of that mouth meets, at ``at`` (its longitude and latitude): what a blind
        one must fit in. Into a ball, the far side comes first at its edge (as into a rod); into a dome, its flat face,
        at its edge nearest the rim."""
        r, reach_ = self.radius, _reach_of(footprint)
        through = r + math.sqrt(max(r * r - reach_ * reach_, 0.0))
        if not self.dome:
            return through
        c, s = cos_sin(at[1])
        return min(through, r - reach_ * c / s) if s > EPS else 0.0

    def most_material_under(self, footprint: Footprint, at: tuple[float, float] = (0.0, 90.0)) -> float:
        """How far a radial cut of that mouth through it goes: through a ball, to its far side; through a dome, until it
        is out of its flat face all across its mouth."""
        r, reach_ = self.radius, _reach_of(footprint)
        if not self.dome:
            return 2 * r
        c, s = cos_sin(at[1])
        return r + reach_ * c / s if s > EPS else math.inf


@dataclass(frozen=True)
class ConeFace:
    """A cone's tapered side (item 3b's third step; cone.md): its axis, the centre of its end at the smaller coordinate
    along it (``start``), its length, and its radius at that end (``start_radius``) and at the other (``end_radius``),
    either of which may be 0 (a point). A point on it is at an angle round its axis (as round a side, from its frame's
    ``u``) and a distance from its middle along it; its normal leans from the radius there towards the narrower end by
    the cone's half angle.

    ``joined`` is the end it stands on (``"start"`` or ``"end"``), None for the first body.
    """

    name: str
    axis: str  # "z"
    start: Vec
    length: float
    start_radius: float
    end_radius: float
    joined: str | None = None
    radius_sources: tuple[Source, ...] = ()
    length_sources: tuple[Source, ...] = ()
    depth_sources: tuple[Source, ...] = ()
    #: The side of what stands on a turned item's face (as a round side's): kept as with that item upright, and the
    #: motion onto the part.
    local: Rigid | None = None

    def upright(self) -> ConeFace:
        return self if self.local is None else replace(self, local=None)

    @property
    def sources(self) -> tuple[Source, ...]:
        return self.radius_sources + tuple(s for s in self.length_sources if s not in self.radius_sources)

    @property
    def reference(self) -> tuple[str, str]:
        """The axes 0 and 90 degrees round it point along (as a round side's)."""
        return _REFERENCE[self.axis]

    @cached_property
    def frame(self) -> Frame:
        """The centre of the end at ``start``; ``u`` and ``v`` the ways out at 0 and 90 degrees round it, ``n`` its axis
        (moved onto the part by ``local``)."""
        u, v = self.reference
        found = Frame.of_names(self.start, u, v, self.axis)
        return found if self.local is None else self.local.frame(found)

    @property
    def wall(self) -> float:
        """The most material a cut along a radius of it meets: its diameter at its wider end."""
        return 2 * max(self.start_radius, self.end_radius)

    @property
    def slope(self) -> float:
        """How fast its radius grows along its axis (negative where it narrows)."""
        return (self.end_radius - self.start_radius) / self.length

    @property
    def lean(self) -> tuple[float, float]:
        """The cosine and sine of the turn that takes a radius's way out to its normal, about its way round (``u`` at
        the point): its half angle, towards its narrower end."""
        q = math.sqrt(1.0 + self.slope * self.slope)
        return 1.0 / q, self.slope / q

    def radius_at(self, along: float) -> float:
        """Its radius ``along`` from its middle."""
        return self.start_radius + self.slope * (self.length / 2 + along)

    def frame_at(self, turn: tuple[float, float], along: float) -> Frame:
        """Its frame at a point on it (item 3a's placeable face): ``turn`` the cosine and sine of its angle round the
        axis, ``along`` how far from its middle along it. Its origin is on the side; ``n`` its normal, out of the
        material; ``u`` round it (as a round side's); ``v`` up its slope, towards its end (``u x v = n``)."""
        frame = self.frame
        r = frame.radial(*turn)
        a = frame.n
        c, s = self.lean
        centre = _plus(frame.origin, a, self.length / 2 + along)
        origin = _plus(centre, r, self.radius_at(along))
        normal = (c * r[0] - s * a[0] + 0.0, c * r[1] - s * a[1] + 0.0, c * r[2] - s * a[2] + 0.0)
        slant = (c * a[0] + s * r[0] + 0.0, c * a[1] + s * r[1] + 0.0, c * a[2] + s * r[2] + 0.0)
        return Frame(origin, frame.radial(-turn[1], turn[0]), slant, normal)

    def exit(self, point: Vec, way: Vec) -> float:
        """How far from ``point`` along the unit ``way`` the line through them is last in the cone (0 where it never
        is): the cone is convex, so the line is in it along one stretch."""
        frame = self.frame
        a = frame.n
        d0 = (point[0] - frame.origin[0], point[1] - frame.origin[1], point[2] - frame.origin[2])
        s0, ds = _dot3(d0, a), _dot3(way, a)
        w0 = _plus(d0, a, -s0)
        dw = _plus(way, a, -ds)
        k, r0, length = self.slope, self.start_radius, self.length

        def inside(t: float) -> bool:
            at = s0 + t * ds
            w = _plus(w0, dw, t)
            r = r0 + k * at
            return -EPS <= at <= length + EPS and r >= -EPS and _dot3(w, w) <= r * r + EPS

        found = [0.0]
        if abs(ds) > 1e-15:
            found += [(0.0 - s0) / ds, (length - s0) / ds]
        c0 = r0 + k * s0
        qa = _dot3(dw, dw) - k * k * ds * ds
        qb = 2.0 * (_dot3(w0, dw) - k * ds * c0)
        qc = _dot3(w0, w0) - c0 * c0
        if abs(qa) > 1e-15:
            disc_ = qb * qb - 4.0 * qa * qc
            if disc_ >= 0.0:
                root = math.sqrt(disc_)
                found += [(-qb - root) / (2.0 * qa), (-qb + root) / (2.0 * qa)]
        elif abs(qb) > 1e-15:
            found.append(-qc / qb)
        ts = sorted(t for t in found if t >= 0.0)
        last = 0.0
        for t0, t1 in pairwise(ts):
            if t1 - t0 > 1e-12 and inside((t0 + t1) / 2):
                last = t1
        return last

    def _rim_exits(self, footprint: Footprint, along: float) -> list[float]:
        """How far a cut of that mouth along the normal at ``along`` (from its middle; at 0 degrees round it, the same
        all round) stays in the cone, from each of points all round its rim, from the plane through its point square
        to its normal."""
        r = _reach_of(footprint)
        upright = self.upright()
        here = upright.frame_at((1.0, 0.0), along)
        inward = (-here.n[0], -here.n[1], -here.n[2])
        found = []
        for k in range(_RIM_POINTS):
            c, s = cos_sin(360.0 * k / _RIM_POINTS)
            on = _plus(_plus(here.origin, here.u, r * c), here.v, r * s)
            found.append(upright.exit(on, inward))
        return found

    # Item 3a's placeable face: the material a cut along its normal meets, at a place on it (its angle round the
    # axis, degrees, and how far from its middle along it), the same all round it.
    def material_under(self, footprint: Footprint, at: tuple[float, float] = (0.0, 0.0)) -> float:
        """The least material a cut of that mouth along its normal meets: what a blind one must fit in. The cone is
        convex, so the least is at its mouth's rim; the far side comes first there, or an end."""
        return min(self._rim_exits(footprint, at[1]))

    def most_material_under(self, footprint: Footprint, at: tuple[float, float] = (0.0, 0.0)) -> float:
        """How far a cut of that mouth along its normal stays in the cone across its mouth: the most of its rim's and
        its point's."""
        upright = self.upright()
        here = upright.frame_at((1.0, 0.0), at[1])
        middle = upright.exit(here.origin, (-here.n[0], -here.n[1], -here.n[2]))
        return max(middle, *self._rim_exits(footprint, at[1]))


def cone_sag(face: ConeFace, radius: float, across: float) -> float:
    """How far a foot reaching ``across`` either way round a cone's side, where its radius is ``radius``, falls from
    the plane square to its normal at its point to the side: the side's curve round it, square to its slope, has the
    radius ``radius`` over the cosine of its half angle."""
    r = radius / face.lean[0]
    return r - math.sqrt(max(r * r - across * across, 0.0))


#: At how many points all round a cut's rim a cone's material under it is asked.
_RIM_POINTS = 180


def _dot3(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


Face = FlatFace | SideFace | BallFace | ConeFace

#: Round each axis, the axes at 0 and 90 degrees.
_REFERENCE = {"z": ("x", "y"), "x": ("y", "z"), "y": ("z", "x")}


def _plus(a: Vec, b: Vec, scale: float) -> Vec:
    """``a + scale b``, coordinate by coordinate (the solver's ``_add``)."""
    return (a[0] + b[0] * scale, a[1] + b[1] * scale, a[2] + b[2] * scale)


@dataclass(frozen=True)
class Part:
    """One piece of an outline: a rectangle, or a disc of radius ``half[0]``."""

    centre: tuple[float, float]
    half: tuple[float, float]
    disc: bool = False


#: What an item covers on the face it is on: its outline as parts, or an outline of lines and arcs.
Footprint = Sequence[Part] | Shape


def rect(h1: float, h2: float, c1: float = 0.0, c2: float = 0.0) -> Part:
    return Part((c1, c2), (h1, h2))


def disc(r: float, c1: float = 0.0, c2: float = 0.0) -> Part:
    return Part((c1, c2), (r, r), disc=True)


def rounded_rect(h1: float, h2: float, radius: float) -> tuple[Part, ...]:
    """A rectangle with rounded corners. The radius must already fit (radius <= h1, h2)."""
    if radius <= EPS:
        return (rect(h1, h2),)
    e1, e2 = h1 - radius, h2 - radius
    return (rect(e1, h2), rect(h1, e2),
            *(disc(radius, s1 * e1, s2 * e2) for s1, s2 in QUADRANTS))  # fmt: skip


def slot_outline(length: float, width: float, *, along_first: bool) -> tuple[Part, ...]:
    """A round-ended slot, ``length`` overall, as a rectangle and two discs."""
    long, wide = length / 2, width / 2
    reach_ = max(long - wide, 0.0)
    if along_first:
        return (rect(reach_, wide), disc(wide, reach_, 0.0), disc(wide, -reach_, 0.0))
    return (rect(wide, reach_), disc(wide, 0.0, reach_), disc(wide, 0.0, -reach_))


def bbox(parts: Iterable[Part]) -> tuple[float, float]:
    """Half sizes of the box around an outline centred on its position."""
    b1 = b2 = 0.0
    for part in parts:
        b1 = max(b1, abs(part.centre[0]) + part.half[0])
        b2 = max(b2, abs(part.centre[1]) + part.half[1])
    return b1, b2


def centred(parts: Sequence[Part]) -> tuple[Part, ...]:
    """An outline moved so the box round it is centred on its position: what fits anywhere fits so at the middle of a
    face that is the same turned half round. Letters' ink lies off their point (generated part 2361: a cedilla and a
    stop, their ink all below the middle of their line's box, asked about as twice as tall as it is)."""
    if not parts:
        return tuple(parts)
    lo1, hi1 = min(p.centre[0] - p.half[0] for p in parts), max(p.centre[0] + p.half[0] for p in parts)
    lo2, hi2 = min(p.centre[1] - p.half[1] for p in parts), max(p.centre[1] + p.half[1] for p in parts)
    m1, m2 = (lo1 + hi1) / 2, (lo2 + hi2) / 2
    return tuple(replace(p, centre=(p.centre[0] - m1, p.centre[1] - m2)) for p in parts)


def reach(parts: Iterable[Part]) -> float:
    """How far an outline reaches from its centre."""
    far = 0.0
    for part in parts:
        c1, c2 = abs(part.centre[0]), abs(part.centre[1])
        if part.disc:
            far = max(far, fs.hypot(c1, c2) + part.half[0])
        else:
            far = max(far, fs.hypot(c1 + part.half[0], c2 + part.half[1]))
    return far


def _reach_of(footprint: Footprint) -> float:
    """How far a footprint reaches from its own origin: an outline's parts', or one of lines and arcs."""
    return shape_reach(footprint) if isinstance(footprint, Shape) else reach(footprint)


def _disc_in_rect_face(face: FlatFace, u1: float, u2: float, r: float) -> bool:
    """Whether a disc (a point when ``r`` is 0) lies on a rectangular face.

    Exact for any corner radii: the disc's centre must lie in the face shrunk
    by ``r``, whose corners are rounded by ``radius - r`` where that is
    positive, and sharp where it isn't.
    """
    h1, h2 = face.half
    if abs(u1) + r > h1 + EPS or abs(u2) + r > h2 + EPS:
        return False
    # Every corner is asked, not only the quadrant's: a round-ended tab's two
    # corners are each as big as half its width, and reach past its middle.
    for radius, (s1, s2) in zip(face.corners, QUADRANTS, strict=True):
        if r >= radius:
            continue
        a1, a2 = s1 * u1 - (h1 - radius), s2 * u2 - (h2 - radius)
        if a1 > 0 and a2 > 0 and fs.hypot(a1, a2) > radius - r + EPS:
            return False
    return True


def _corners_of(part: Part, p1: float, p2: float) -> list[tuple[float, float]]:
    c1, c2 = part.centre[0] + p1, part.centre[1] + p2
    h1, h2 = part.half
    return [(c1 + s1 * h1, c2 + s2 * h2) for s1, s2 in QUADRANTS]


def _far_near(part: Part, p1: float, p2: float) -> tuple[float, float]:
    """The farthest and nearest distances of a part from the face's centre."""
    c1, c2 = part.centre[0] + p1, part.centre[1] + p2
    h1, h2 = part.half
    if part.disc:
        d = fs.hypot(c1, c2)
        return d + h1, max(d - h1, 0.0)
    far = fs.hypot(abs(c1) + h1, abs(c2) + h2)
    near = fs.hypot(max(abs(c1) - h1, 0.0), max(abs(c2) - h2, 0.0))
    return far, near


def _covers_hole(part: Part, p1: float, p2: float, radius: float) -> bool:
    """Whether a part covers a ring's whole central hole (a step around a bore)."""
    c1, c2 = part.centre[0] + p1, part.centre[1] + p2
    if part.disc:
        return fs.hypot(c1, c2) + radius <= part.half[0] + EPS
    return (
        abs(c1) + radius <= part.half[0] + EPS
        and abs(c2) + radius <= part.half[1] + EPS
    )


def part_on_face(face: FlatFace, part: Part, p1: float, p2: float) -> bool:
    """Whether one part lies on the face's material (a ring's hole is not material)."""
    if face.shape == "profile":
        assert face.profile is not None
        centre = (part.centre[0] + p1, part.centre[1] + p2)
        if part.disc:
            return face.profile.holds_disc(centre, part.half[0], EPS)
        return face.profile.holds_rect(centre, part.half, EPS)
    if face.shape == "rect":
        c1, c2 = part.centre[0] + p1, part.centre[1] + p2
        if part.disc:
            return _disc_in_rect_face(face, c1, c2, part.half[0])
        return all(
            _disc_in_rect_face(face, u1, u2, 0.0)
            for u1, u2 in _corners_of(part, p1, p2)
        )
    far, near = _far_near(part, p1, p2)
    return far <= face.half[0] + EPS and (
        face.shape != "annulus" or near >= face.inner_radius - EPS
    )


def outline_on_face(face: FlatFace, parts: Sequence[Part], p1: float, p2: float,
                    *, cut: bool = False) -> bool:  # fmt: skip
    """Whether an outline placed at (p1, p2) lies on the face.

    For a cut on a ring, covering the whole central hole is fine: that is a
    step around the bore, the same as a counterbore.
    """
    if face.shape == "annulus" and cut:
        outer = all(_far_near(part, p1, p2)[0] <= face.half[0] + EPS for part in parts)
        if not outer:
            return False
        if any(_covers_hole(part, p1, p2, face.inner_radius) for part in parts):
            return True
    return all(part_on_face(face, part, p1, p2) for part in parts)


def touches_edge(face: FlatFace, parts: Sequence[Part], p1: float, p2: float) -> bool:
    """Whether a cut's outline at (p1, p2), on the face, touches the face's edge at a point from inside.

    There the material between the cut and the face's side is pinched to
    nothing: a hole touching a plate's side, or a disc's rim, leaves an edge
    on which the part meets itself, which no kernel builds soundly. A part of
    the outline meets the edge where it lies on the face but, grown by a
    hair, would not; a straight side lying along the edge only opens the cut
    there (a rebate), and so does a round end where another part of the same
    outline meets the edge too (a round-ended slot along the edge). A cut
    round the face's centre that covers it, or a ring's bore, all round
    touches nothing at a point.

    >>> face = FlatFace("+z", (0.0, 0.0, 6.0), "+z", ("x", "y"), "rect", (30.0, 10.0))
    >>> touches_edge(face, (disc(2.5),), 0, 7.5), touches_edge(face, (disc(2.5),), 0, 7)
    (True, False)
    >>> touches_edge(face, slot_outline(12, 4, along_first=True), 0, 8)
    False
    """
    if face.shape == "profile" and len(parts) > 1:
        return False  # where on an outline each part's touch lies isn't worked out: one disc alone is asked
    covering = face.shape == "annulus" and any(
        _covers_hole(part, p1, p2, face.inner_radius) for part in parts
    )
    for k, part in enumerate(parts):
        if not part.disc and face.shape in ("rect", "profile"):
            continue
        c1, c2 = part.centre[0] + p1, part.centre[1] + p2
        if face.shape in ("disc", "annulus") and fs.hypot(c1, c2) < EPS:
            continue
        grown = Part(
            part.centre, (part.half[0] + 2 * EPS, part.half[1] + 2 * EPS), part.disc
        )
        if covering:
            if _far_near(grown, p1, p2)[0] <= face.half[0] + EPS:
                continue
        elif part_on_face(face, grown, p1, p2):
            continue
        at = _touching(face, part, c1, c2)
        others = [other for j, other in enumerate(parts) if j != k]
        if at is not None and _point_in_parts(others, (p1, p2), *at):
            continue
        return True
    return False


def _touching(
    face: FlatFace, part: Part, c1: float, c2: float
) -> tuple[float, float] | None:
    """Where a disc meets a rectangular face's straight edge from inside (None: elsewhere)."""
    if face.shape != "rect" or not part.disc:
        return None
    (h1, h2), r = face.half, part.half[0]
    if abs(abs(c1) + r - h1) <= 3 * EPS:
        return math.copysign(h1, c1), c2
    if abs(abs(c2) + r - h2) <= 3 * EPS:
        return c1, math.copysign(h2, c2)
    return None


def outline_meets_face(
    face: FlatFace, parts: Sequence[Part], p1: float, p2: float
) -> bool:
    """Whether an outline at (p1, p2) shares some area with the face (overhang allowed).

    Exact for rectangular faces, discs and rings; a rectangle's rounded
    corners are ignored, which can only say "meets" where it barely doesn't.
    """
    for part in parts:
        c1, c2 = part.centre[0] + p1, part.centre[1] + p2
        h1, h2 = part.half
        if face.shape == "profile":
            piece = (
                Shape.disc((c1, c2), h1)
                if part.disc
                else Shape.rect((c1, c2), part.half)
            )
            if shape_meets_face(face, piece, 0.0, 0.0):
                return True
            continue
        if face.shape == "rect":
            g1 = max(abs(c1) - face.half[0], 0.0)
            g2 = max(abs(c2) - face.half[1], 0.0)
            if part.disc:
                if fs.hypot(g1, g2) < h1 - EPS:
                    return True
            elif (
                abs(c1) - h1 < face.half[0] - EPS and abs(c2) - h2 < face.half[1] - EPS
            ):
                return True
            continue
        far, near = _far_near(part, p1, p2)
        if near < face.half[0] - EPS and (
            face.shape != "annulus" or far > face.inner_radius + EPS
        ):
            return True
    return False


def fits_somewhere(
    face: FlatFace, parts: Sequence[Part], *, cut: bool = False
) -> bool | None:
    """Whether the outline fits anywhere on the face; None when it can't be settled.

    For a centrally symmetric convex face (a rectangle with matching
    opposite corners, a disc), a symmetric outline that fits anywhere also
    fits at the centre, so the centre decides. A plain rectangle is decided by
    the outline's box. Other faces are left to the placement's own check. The
    outline is taken with its box centred (:func:`centred`): where it fits
    is where its box does, not how far it reaches from its own point.
    """
    parts = centred(parts)
    if face.shape == "rect" and face.corners == (0.0, 0.0, 0.0, 0.0):
        b1, b2 = bbox(parts)
        return b1 <= face.half[0] + EPS and b2 <= face.half[1] + EPS
    if face.symmetric:
        return outline_on_face(face, parts, 0.0, 0.0, cut=cut)
    if face.shape == "annulus":
        if reach(parts) > face.half[0] + EPS:
            return False
        if cut and any(
            _covers_hole(part, 0.0, 0.0, face.inner_radius) for part in parts
        ):
            return True  # it fits at the centre, around the hole: a step round the bore
        lone = len(parts) == 1 and parts[0].disc
        if lone and 2 * parts[0].half[0] > face.half[0] - face.inner_radius + EPS:
            return (
                None if cut else False
            )  # a cut may still be meant to break into the hole
    return None


def _point_in_parts(
    parts: Sequence[Part], position: tuple[float, float], u1: float, u2: float
) -> bool:
    for part in parts:
        c1, c2 = part.centre[0] + position[0], part.centre[1] + position[1]
        if part.disc:
            if fs.hypot(u1 - c1, u2 - c2) <= part.half[0] + EPS:
                return True
        elif abs(u1 - c1) <= part.half[0] + EPS and abs(u2 - c2) <= part.half[1] + EPS:
            return True
    return False


def _part_in_part(
    a: Part, pa: tuple[float, float], b: Part, pb: tuple[float, float]
) -> bool:
    """Whether part ``a`` at ``pa`` lies wholly within part ``b`` at ``pb``: exact."""
    a1, a2 = a.centre[0] + pa[0], a.centre[1] + pa[1]
    b1, b2 = b.centre[0] + pb[0], b.centre[1] + pb[1]
    if b.disc:
        if a.disc:
            return fs.hypot(a1 - b1, a2 - b2) + a.half[0] <= b.half[0] + EPS
        return all(fs.hypot(a1 + s1 * a.half[0] - b1, a2 + s2 * a.half[1] - b2) <= b.half[0] + EPS
                   for s1, s2 in QUADRANTS)  # fmt: skip
    return (
        abs(a1 - b1) + a.half[0] <= b.half[0] + EPS
        and abs(a2 - b2) + a.half[1] <= b.half[1] + EPS
    )


def outline_within(inner: Sequence[Part], at: tuple[float, float], outer: Sequence[Part],
                   outer_at: tuple[float, float]) -> bool:  # fmt: skip
    """Whether one outline lies wholly within another: an item standing wholly over a cut's mouth.

    Exact where each piece of the one lies in a single piece of the other;
    otherwise each piece's outline is followed closely (a disc at 256 points,
    a rectangle at 64 along each side), so it is never said of an outline
    that pokes out by more than a hair.
    """
    for part in inner:
        if any(_part_in_part(part, at, other, outer_at) for other in outer):
            continue
        c1, c2 = part.centre[0] + at[0], part.centre[1] + at[1]
        if part.disc:
            r = part.half[0]
            points = [(c1 + r * fs.cos(t), c2 + r * fs.sin(t))
                      for t in (2 * math.pi * k / 256 for k in range(256))]  # fmt: skip
        else:
            h1, h2 = part.half
            edge = [k / 64 for k in range(65)]
            points = ([(c1 - h1 + 2 * h1 * f, c2 - h2) for f in edge] + [(c1 - h1 + 2 * h1 * f, c2 + h2) for f in edge]
                      + [(c1 - h1, c2 - h2 + 2 * h2 * f) for f in edge] + [(c1 + h1, c2 - h2 + 2 * h2 * f) for f in edge])  # fmt: skip
        if not all(_point_in_parts(outer, outer_at, u1, u2) for u1, u2 in points):
            return False
    return True


def inside_hole(face: FlatFace, parts: Sequence[Part], p1: float, p2: float) -> bool:
    """Whether an outline lies wholly in a ring's central hole: a cut there cuts nothing."""
    return face.shape == "annulus" and all(
        _far_near(part, p1, p2)[0] <= face.inner_radius + EPS for part in parts
    )


def _parts_overlap(
    a: Part, pa: tuple[float, float], b: Part, pb: tuple[float, float]
) -> bool:
    """Whether two parts, at their positions, share some area (touching doesn't count)."""
    a1, a2 = a.centre[0] + pa[0], a.centre[1] + pa[1]
    b1, b2 = b.centre[0] + pb[0], b.centre[1] + pb[1]
    if a.disc and b.disc:
        return fs.hypot(a1 - b1, a2 - b2) < a.half[0] + b.half[0] - EPS
    if not a.disc and not b.disc:
        return (
            abs(a1 - b1) < a.half[0] + b.half[0] - EPS
            and abs(a2 - b2) < a.half[1] + b.half[1] - EPS
        )
    disc_, d1, d2, box, r1, r2 = (
        (a, a1, a2, b, b1, b2) if a.disc else (b, b1, b2, a, a1, a2)
    )
    g1 = max(abs(d1 - r1) - box.half[0], 0.0)
    g2 = max(abs(d2 - r2) - box.half[1], 0.0)
    return fs.hypot(g1, g2) < disc_.half[0] - EPS


def _off_corners(shape: Shape, p: tuple[float, float]) -> tuple[float, float]:
    """``p``, or a point 1e-8 mm above it where it is at the height of one of the outline's corners or its arcs' tops.

    There, the crossing rule (:meth:`~forge_spec.outline.Shape.inside`) can
    count a corner twice, as it can where the corners of copies of one
    outline line up; a point that far off is on the same side of an outline
    it is more than :data:`EPS` from.
    """
    heights = [e[1] for q in shape.pieces for e in q.ends()]
    heights += [
        q.centre[1] + k * q.radius
        for q in shape.pieces
        if isinstance(q, Arc)
        for k in (-1.0, 1.0)
    ]
    y = p[1]
    while any(abs(y - h) < 1e-9 for h in heights):
        y += 1e-8
    return (p[0], y)


def shape_holds(shape: Shape, p: tuple[float, float], tol: float = EPS) -> bool:
    """Whether a point is in an outline, or within ``tol`` of it."""
    return shape.distance(p) <= tol or shape.inside(_off_corners(shape, p))


def shapes_overlap(a: Shape, b: Shape) -> bool:
    """Whether two outlines' insides share some area (touching, along a side or at a point, keeps them apart).

    So they do when a point of either's outline is inside the other by more
    than :data:`EPS` (each piece split where it meets the other's, its ends
    and the middle of each stretch asked), or the middle of either's box is
    (one wholly within the other, or the two the same).
    """

    def deep_in(shape: Shape, p: tuple[float, float]) -> bool:
        return shape.distance(p) > EPS and shape.inside(_off_corners(shape, p))

    for x, y in ((a, b), (b, a)):
        for q in x.pieces:
            cuts = sorted(
                {0.0, 1.0, *(q.param(m) for w in y.pieces for m in meet(q, w))}
            )
            asked = [
                *cuts,
                *((t0 + t1) / 2 for t0, t1 in pairwise(cuts) if t1 - t0 > 1e-12),
            ]
            if any(deep_in(y, q.at(t)) for t in asked):
                return True
        (l1, l2), (h1, h2) = x.box()
        if deep_in(y, ((l1 + h1) / 2, (l2 + h2) / 2)):
            return True
    return False


def first_close_pair(points: Sequence[tuple[float, float]], owners: Sequence[int], cells: tuple[float, float],
                     close: Callable[[int, int], bool], *, wrap: float | None = None) -> tuple[int, int] | None:  # fmt: skip
    """The first two owners with points close to each other, or None: (j, i), j < i, i as small as can be.

    ``points`` belong to ``owners`` (a copy may have more than one point) and
    are given in owner order. Two points can be close only if they are less
    than a cell apart along each coordinate, so each point is compared with
    those in its own and the neighbouring cells of a grid: about linear in
    the number of points, however they are laid out. With ``wrap``, the first
    coordinate is an angle that comes round again at that value.
    """
    c1, c2 = max(cells[0], EPS), max(cells[1], EPS)
    bins = max(1, math.floor(wrap / c1)) if wrap is not None else 0
    grid: dict[tuple[int, int], list[int]] = {}

    def key(p: tuple[float, float]) -> tuple[int, int]:
        if wrap is not None:
            return math.floor((p[0] % wrap) / (wrap / bins)) % bins, math.floor(
                p[1] / c2
            )
        return math.floor(p[0] / c1), math.floor(p[1] / c2)

    def around(k: tuple[int, int]) -> set[tuple[int, int]]:
        firsts = (
            {(k[0] + d) % bins for d in (-1, 0, 1)}
            if wrap is not None
            else {k[0] - 1, k[0], k[0] + 1}
        )
        return {(a, b) for a in firsts for b in (k[1] - 1, k[1], k[1] + 1)}

    n = 0
    while n < len(points):
        owner = owners[n]
        best: int | None = None
        group = []
        while n < len(points) and owners[n] == owner:
            group.append(n)
            n += 1
        for i in group:
            for cell in around(key(points[i])):
                for j in grid.get(cell, ()):
                    if (
                        owners[j] < owner
                        and (best is None or owners[j] < best)
                        and close(j, i)
                    ):
                        best = owners[j]
        if best is not None:
            return best, owner
        for i in group:
            grid.setdefault(key(points[i]), []).append(i)
    return None


def copies_overlap(
    parts: Sequence[Part], positions: Sequence[tuple[float, float]]
) -> tuple[int, int] | None:
    """The first two copies of an outline, at these positions, that overlap, or None.

    Exact for outlines made of rectangles and discs, and about linear in the
    number of copies (:func:`first_close_pair`), so no pattern is too big
    to check.
    """
    if not parts or len(positions) < 2:
        return None
    b1, b2 = bbox(parts)

    def close(j: int, i: int) -> bool:
        return any(
            _parts_overlap(a, positions[j], b, positions[i])
            for a in parts
            for b in parts
        )

    return first_close_pair(positions, range(len(positions)), (2 * b1, 2 * b2), close)


def _depth_at(face: FlatFace, rho: float) -> float:
    """The material under the face at distance ``rho`` from its centre."""
    model = face.depth_model
    if model is None:
        return face.depth_below
    if isinstance(model, Turned):
        return turned_depth(model.shape, model.top, rho, rho, model.extra)[0]
    if isinstance(model, Dome):
        return math.sqrt(max(model.radius * model.radius - rho * rho, 0.0))
    assert not isinstance(model, Slant), "a slant's material isn't by distance from the centre"
    if rho <= model.flat:
        return face.depth_below
    if rho >= model.edge:
        return 0.0
    return model.own * (model.edge - rho) / (model.edge - model.flat)


def _depth_range(face: FlatFace, near: float, far: float) -> tuple[float, float]:
    """The least and the most material under the face between distances ``near`` and ``far`` from its centre.

    Every model but a turned part's falls away from the centre, so the least
    is at the farthest distance and the most at the nearest; a turned part's
    is worked out over the run (:func:`~forge_spec.outline.turned_depth`).
    """
    model = face.depth_model
    if isinstance(model, Turned):
        return turned_depth(model.shape, model.top, near, far, model.extra)
    if isinstance(model, Slant):  # bounds over the ring, whichever way it leans (the walks above read it exactly)
        return max(face.depth_below - model.tan * far, 0.0), face.depth_below + model.tan * far
    return _depth_at(face, far), _depth_at(face, near)


def material_at(face: FlatFace, p1: float, p2: float, r: float) -> float:
    """The least material under a disc of radius ``r`` at (p1, p2) on the face (a point, ``r`` 0): what a blind cut must fit in."""
    return least_material_under(face, (disc(r),), p1, p2)


def _tab_exit(radius: float, behind: float, x0: float, y0: float, dx: float, dy: float) -> float:
    """How far from (x0, y0) along the unit (dx, dy) a line stays in a round-ended tab's section across its thickness:
    the half-disc of ``radius`` about the origin on the side of +y, and the strip as wide behind it, ``behind`` long
    (0 where it never is in it). The section is convex, so the line is in it along one stretch."""

    def inside(t: float) -> bool:
        x, y = x0 + t * dx, y0 + t * dy
        if abs(x) > radius + EPS or y < -behind - EPS:
            return False
        return y <= EPS or x * x + y * y <= radius * radius + EPS

    found = [0.0]
    if abs(dx) > 1e-15:
        found += [(radius - x0) / dx, (-radius - x0) / dx]
    if abs(dy) > 1e-15:
        found += [(0.0 - y0) / dy, (-behind - y0) / dy]
    b = x0 * dx + y0 * dy
    disc_ = b * b - (x0 * x0 + y0 * y0 - radius * radius)
    if disc_ >= 0.0:
        root = math.sqrt(disc_)
        found += [-b - root, -b + root]
    last = 0.0
    for t0, t1 in pairwise(sorted(t for t in found if t >= 0.0)):
        if t1 - t0 > 1e-12 and inside((t0 + t1) / 2):
            last = t1
    return last


def side_material(face: SideFace, r: float) -> float:
    """The least material a cut of radius ``r`` along a radius of a round side meets: what a blind one must fit in.

    Measured from the side's surface on the cut's axis, in along it
    (docs/definitions/hole.md). Into a solid rod, the far side comes first at
    the cut's edge; into a tube's wall from outside, the bore comes first at
    its middle; out through a wall from inside a bore or hollow, the outside
    comes first at its edge.
    """
    radius, wall = face.radius, face.wall
    if face.outward:
        if wall >= 2 * radius - EPS:
            return radius + math.sqrt(max(radius * radius - r * r, 0.0))
        return wall
    outer = radius + wall
    return math.sqrt(max(outer * outer - r * r, 0.0)) - radius


def side_most_material(face: SideFace, r: float) -> float:
    """How far a cut of radius ``r`` through a round side's wall goes: until it is out all across its mouth.

    Through a solid rod, to the far side; through a tube's wall from outside,
    until it is in the bore everywhere across its mouth; out through a wall
    from inside, to the outside on its axis.
    """
    radius, wall = face.radius, face.wall
    if face.outward:
        if wall >= 2 * radius - EPS:
            return 2 * radius
        inner = radius - wall
        return radius - math.sqrt(max(inner * inner - r * r, 0.0))
    return wall


def far_near(footprint: Footprint, p1: float, p2: float) -> tuple[float, float]:
    """The farthest and the nearest distances of a footprint at (p1, p2) from the face's centre.

    A footprint is an item's outline as parts, or an outline of lines and
    arcs (an extrusion's or a revolution's, standing on the face). Where it
    covers the centre, its nearest distance is 0.

    >>> far_near((rect(3, 4),), 0, 0)
    (5.0, 0.0)
    >>> far_near(Shape.disc((0.0, 0.0), 2.0), 5, 0)
    (7.0, 3.0)
    """
    if isinstance(footprint, Shape):
        moved, centre = footprint.moved(p1, p2), (0.0, 0.0)
        near = 0.0 if moved.inside(centre) else moved.distance(centre)
        return shape_reach(moved), near
    ranges = [_far_near(part, p1, p2) for part in footprint]
    return max(far for far, _ in ranges), min(near for _, near in ranges)


@dataclass(frozen=True)
class _Step:
    """One face on the way down from a face to what is under it: its own material, and how to take what is under it.

    ``less``: a pocket's floor, its depth less than what it was cut into;
    else ``face``, a standing item's far face, its own with its host's added
    (or, for the most, the greater of that and its own, ``own``).
    """

    less: float = 0.0
    face: FlatFace | None = None
    near: float = 0.0
    far: float = 0.0
    own: float = 0.0


def least_material_under(
    face: FlatFace, footprint: Footprint, p1: float, p2: float
) -> float:
    """The least material under a footprint at (p1, p2): what a blind cut of that outline must fit in.

    The item's own material under a face depends only on the distance from
    its centre (docs/definitions/frame.md, "The material under a face"), so
    its least is the least over the footprint's run of distances, from its
    nearest point to its farthest: where it falls away from the centre, under
    its farthest point. A standing item's far face has its host's material
    under it too where it is over the host's face: when the whole footprint
    is, the least of the host's under it adds to its own (where its own runs
    right down to its foot); else, over the overhang, its own is all there
    is. A pocket's floor has what was under it, less its depth. Worked down
    the stack of faces one at a time, however tall.

    >>> face = FlatFace("+end", (0, 0, 10), "+z", ("x", "y"), "disc", (10, 10), depth_below=10,
    ...                 depth_model=Dome(10))
    >>> round(least_material_under(face, (rect(3, 4),), 0, 0), 6)  # its corner is 5 from the centre
    8.660254
    >>> plate = FlatFace("+z", (0, 0, 5), "+z", ("x", "y"), "rect", (20, 10), depth_below=5.0)
    >>> shelf = FlatFace("+z", (15, 0, 8), "+z", ("x", "y"), "rect", (10, 5), depth_below=3.0,
    ...                  over=Over(plate, (15, 0)))  # over the plate to 5 along x from its centre, then over air
    >>> least_material_under(shelf, (disc(1),), -5, 0), least_material_under(shelf, (disc(1),), 5, 0)
    (8.0, 3.0)
    """
    steps: list[_Step] = []
    while True:
        if face.less is not None:
            steps.append(_Step(less=face.less.depth))
            p1, p2, face = p1 + face.less.at[0], p2 + face.less.at[1], face.less.base
            continue
        if isinstance(face.depth_model, Slant):  # a leaning item's far face: its own material, over nothing else
            found = _slanted(face, face.depth_model, footprint, p1, p2, 1.0)
            break
        far, near = far_near(footprint, p1, p2)
        over = face.over
        if over is not None and face.turn != over.host.turn:
            # A turned item's far face over its host: the footprint in the host's axes, each piece of it.
            pieces = [(f, q1 + over.at[0], q2 + over.at[1])
                      for f, q1, q2 in _into_host(footprint, p1, p2, face.turn - over.host.turn)]  # fmt: skip
            if all(footprint_on_face(over.host, *piece) for piece in pieces):
                host = min(least_material_under(over.host, *piece) for piece in pieces)
                found = _depth_range(add_material(face, host), near, far)[0]
            else:
                found = _depth_range(face, near, far)[0]
            break
        if over is None or not footprint_on_face(
            over.host, footprint, p1 + over.at[0], p2 + over.at[1]
        ):
            found = _depth_range(face, near, far)[0]
            break
        steps.append(_Step(face=face, near=near, far=far))
        p1, p2, face = p1 + over.at[0], p2 + over.at[1], over.host
    for step in reversed(steps):
        if step.face is None:
            found -= step.less
        else:
            found = _depth_range(add_material(step.face, found), step.near, step.far)[0]
    return found


def most_material_under(
    face: FlatFace, footprint: Footprint, p1: float, p2: float
) -> float:
    """The most material under a footprint at (p1, p2): how far a cut of that outline through goes.

    It comes out of the far side all across its mouth, so it goes as deep as
    the material is deepest under it: the item's own, where it falls away
    from the centre, under its nearest point (the centre itself, where it
    covers it); and where the footprint is over its host's face, its own and
    the most of the host's under it. A pocket's floor: what was under it, less
    its depth.

    >>> face = FlatFace("+end", (0, 0, 10), "+z", ("x", "y"), "disc", (10, 10), depth_below=10,
    ...                 depth_model=Dome(10))
    >>> most_material_under(face, (rect(3, 4, 6, 0),), 0, 0)  # its nearest point is 3 from the centre
    9.539392014169456
    >>> plate = FlatFace("+z", (0, 0, 5), "+z", ("x", "y"), "rect", (20, 10), depth_below=5.0)
    >>> shelf = FlatFace("+z", (15, 0, 8), "+z", ("x", "y"), "rect", (10, 5), depth_below=3.0,
    ...                  over=Over(plate, (15, 0)))  # over the plate to 5 along x from its centre, then over air
    >>> most_material_under(shelf, (disc(1),), 5, 0), most_material_under(shelf, (disc(1),), 7, 0)
    (8.0, 3.0)
    """
    steps: list[_Step] = []
    while True:
        if face.less is not None:
            steps.append(_Step(less=face.less.depth))
            p1, p2, face = p1 + face.less.at[0], p2 + face.less.at[1], face.less.base
            continue
        if isinstance(face.depth_model, Slant):  # a leaning item's far face: its own material, over nothing else
            found = _slanted(face, face.depth_model, footprint, p1, p2, -1.0)
            break
        far, near = far_near(footprint, p1, p2)
        found = _depth_range(face, near, far)[1]
        over = face.over
        if over is not None and face.turn != over.host.turn:
            # A turned item's far face over its host: the footprint in the host's axes, each piece of it.
            pieces = [(f, q1 + over.at[0], q2 + over.at[1])
                      for f, q1, q2 in _into_host(footprint, p1, p2, face.turn - over.host.turn)]  # fmt: skip
            meeting = [piece for piece in pieces if _footprint_meets(over.host, *piece)]
            if meeting:
                host = max(most_material_under(over.host, *piece) for piece in meeting)
                found = max(found, _depth_range(add_material(face, host), near, far)[1])
            break
        if over is None or not _footprint_meets(
            over.host, footprint, p1 + over.at[0], p2 + over.at[1]
        ):
            break
        steps.append(_Step(face=face, near=near, far=far, own=found))
        p1, p2, face = p1 + over.at[0], p2 + over.at[1], over.host
    for step in reversed(steps):
        if step.face is None:
            found -= step.less
        else:
            found = max(
                step.own,
                _depth_range(add_material(step.face, found), step.near, step.far)[1],
            )
    return found


def _slanted(face: FlatFace, slant: Slant, footprint: Footprint, p1: float, p2: float, sign: float) -> float:
    """The least (``sign`` 1) or the most (-1) material under a footprint at (p1, p2) on a leaning item's far face
    (:class:`Slant`): its own at the centre, less ``tan`` for each millimetre the footprint reaches farthest (or least
    far) along the way it leans; none below nothing."""
    w1, w2 = slant.way
    reach = _support(footprint, (sign * w1, sign * w2), p1, p2)
    return max(face.depth_below - sign * slant.tan * reach, 0.0)


def _support(footprint: Footprint, way: tuple[float, float], p1: float, p2: float) -> float:
    """How far along ``way`` (a unit vector) a footprint at (p1, p2) reaches, at most."""
    w1, w2 = way
    if isinstance(footprint, Shape):
        found = -math.inf
        for piece in footprint.pieces:
            ends: tuple[tuple[float, float], ...]
            if isinstance(piece, Arc):
                ends = (piece.at(0.0), piece.at(1.0))
                angle = fs.atan2(w2, w1)
                if _within_sweep(angle, piece.start, piece.sweep):
                    ends += ((piece.centre[0] + piece.radius * w1, piece.centre[1] + piece.radius * w2),)
            else:
                ends = (piece.a, piece.b)
            found = max(found, *(w1 * (p1 + e[0]) + w2 * (p2 + e[1]) for e in ends))
        return found
    found = -math.inf
    for part in footprint:
        c1, c2 = p1 + part.centre[0], p2 + part.centre[1]
        if part.disc:
            found = max(found, w1 * c1 + w2 * c2 + part.half[0])
        else:
            found = max(found, w1 * c1 + w2 * c2 + abs(w1) * part.half[0] + abs(w2) * part.half[1])
    return found


def _within_sweep(angle: float, start: float, sweep: float) -> bool:
    """Whether ``angle`` (radians) lies on an arc from ``start`` turning ``sweep`` (anticlockwise positive)."""
    turn = 2 * math.pi
    if abs(sweep) >= turn - 1e-12:
        return True
    lo, span = (start, sweep) if sweep >= 0 else (start + sweep, -sweep)
    return (angle - lo) % turn <= span + 1e-12


def add_material(face: FlatFace, host: float) -> FlatFace:
    """The face with ``host`` more material under it wherever its own runs right down to its foot, and nothing else under it.

    Its own constant material, or a cone's within its smaller end
    (:class:`Taper` ``flat``); a revolution's where the line runs right
    through it (:class:`Turned` ``extra``).
    """
    model = face.depth_model
    if isinstance(model, Turned):
        model = replace(model, extra=model.extra + host)
    return replace(
        face, depth_below=face.depth_below + host, depth_model=model, over=None
    )


def uniform(face: FlatFace) -> bool:
    """Whether the same material is under every point of the face: its own, with no model, host or base to it."""
    return face.depth_model is None and face.over is None and face.less is None


def face_footprint(face: FlatFace) -> Footprint:
    """A footprint holding all of a face: its outline, or (for a rectangle with rounded corners, a ring) its box or disc."""
    if face.shape == "profile":
        assert face.profile is not None
        return face.profile
    if face.shape in ("disc", "annulus"):
        return (disc(face.half[0]),)
    return (rect(*face.half),)


def footprint_on_face(
    face: FlatFace, footprint: Footprint, p1: float, p2: float
) -> bool:
    """Whether a footprint at (p1, p2) lies wholly on the face's material."""
    if isinstance(footprint, Shape):
        return shape_on_face(face, footprint, p1, p2)
    return outline_on_face(face, footprint, p1, p2)


def _footprint_meets(
    face: FlatFace, footprint: Footprint, p1: float, p2: float
) -> bool:
    if isinstance(footprint, Shape):
        return shape_meets_face(face, footprint, p1, p2)
    return outline_meets_face(face, footprint, p1, p2)


# ----------------------------------------------------------------------
# Outlines of lines and arcs on faces (an extrusion standing on one; anything on an extrusion's end)
# ----------------------------------------------------------------------
def _walls(face: FlatFace) -> tuple[Line | Arc, ...]:
    """The face's boundary, as pieces, in its axes about its centre."""
    if face.shape == "profile":
        assert face.profile is not None
        return face.profile.pieces
    if face.shape in ("disc", "annulus"):
        found = Shape.disc((0.0, 0.0), face.half[0]).pieces
        if face.shape == "annulus":
            found += Shape.disc((0.0, 0.0), face.inner_radius).pieces
        return found
    return Shape.rect((0.0, 0.0), face.half, face.corners).pieces


def _on_face(face: FlatFace, p: tuple[float, float]) -> bool:
    """Whether a point is on the face's material (its boundary included)."""
    if face.shape == "profile":
        assert face.profile is not None
        return face.profile.contains(p, EPS)
    if face.shape == "rect":
        return _disc_in_rect_face(face, p[0], p[1], 0.0)
    far = fs.hypot(p[0], p[1])
    return far <= face.half[0] + EPS and (
        face.shape != "annulus" or far >= face.inner_radius - EPS
    )


def _in_face(face: FlatFace, p: tuple[float, float]) -> bool:
    """Whether a point is in the face's material and off its boundary."""
    return _on_face(face, p) and min(w.distance(p) for w in _walls(face)) > EPS


def shape_on_face(face: FlatFace, shape: Shape, p1: float, p2: float) -> bool:
    """Whether an outline of lines and arcs at (p1, p2) lies wholly on the face's material.

    Its boundary must (each piece split where it meets the face's, each
    stretch's ends and middle on the face); and on a ring, the hole in the
    middle must not lie inside it.
    """
    moved = shape.moved(p1, p2)
    if not boundary_within(moved.pieces, lambda p: _on_face(face, p), _walls(face)):
        return False
    return face.shape != "annulus" or not moved.inside((0.0, 0.0))


def shape_meets_face(face: FlatFace, shape: Shape, p1: float, p2: float) -> bool:
    """Whether an outline at (p1, p2) shares some area with the face (overhang allowed).

    A stretch of either's boundary inside the other, off its boundary, says
    so; where the boundaries lie on each other, a point just inside the
    outline does.
    """
    moved = shape.moved(p1, p2)
    walls = _walls(face)

    def in_shape(p: tuple[float, float]) -> bool:
        return moved.inside(p) and moved.distance(p) > EPS

    for pieces, others, inside in (
        (moved.pieces, walls, lambda p: _in_face(face, p)),
        (walls, moved.pieces, in_shape),
    ):
        for q in pieces:
            cuts = sorted({0.0, 1.0, *(q.param(x) for w in others for x in meet(q, w))})
            if any(
                inside(q.at((a + b) / 2)) for a, b in pairwise(cuts) if b - a > 1e-12
            ):
                return True
    q = moved.pieces[0]
    m, ahead = q.at(0.5), q.at(0.5 + 1e-6)
    tx, ty = ahead[0] - m[0], ahead[1] - m[1]
    norm = fs.hypot(tx, ty) or 1.0
    for side in (1.0, -1.0):
        p = (m[0] - side * ty / norm * 1e-4, m[1] + side * tx / norm * 1e-4)
        if moved.inside(p):
            return _on_face(face, p)
    return False


def shape_reach(shape: Shape) -> float:
    """How far an outline reaches from its own origin."""
    found = 0.0
    for q in shape.pieces:
        points = list(q.ends())
        if isinstance(q, Arc):
            cx, cy = q.centre
            angle = fs.atan2(cy, cx) if fs.hypot(cx, cy) > 0 else q.start
            fraction = q.fraction(angle)
            if fraction is not None:
                points.append(q.at(fraction))
        found = max(found, *(fs.hypot(x, y) for x, y in points))
    return found
