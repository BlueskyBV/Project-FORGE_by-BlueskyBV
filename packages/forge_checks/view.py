"""What every view of a built part answers, and the proxy the checks see it through.

A part is judged through a :class:`GeometryView`, never through how it was
made: a mesh read from a file, OpenCascade's B-rep, the implicit kernel's
field. Each view says which questions it can answer (its
:class:`Capability` set); whether it may lack one is the capability table's
to say, never the view's.

The checks never hold a view itself, only a :class:`ViewProxy`, which

- passes on exactly the questions of the protocol, and nothing else a view
  happens to have (how the part was built can't leak through an attribute);
- refuses a question the view didn't declare it answers
  (:class:`NotAnswerableError`);
- tidies what is asked (points as finite ``(n, 3)`` floats, directions made
  unit) and checks what comes back: an answer of the wrong shape, a side
  that isn't one, a negative distance, a coverage coarser than asked, is the
  view breaking its contract (:class:`ViewError`), and the part is held.

A view that can't tell which side a point is on says :attr:`Side.UNKNOWN`.
That is never taken for either side: a check that meets it can't pass.

>>> Side.IN, int(Side.OUT), Side(2).name
(<Side.IN: 1>, -1, 'UNKNOWN')
"""

from __future__ import annotations

import enum
import functools
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from forge_numeric import vector as fv
from forge_units import Interval
from numpy.typing import NDArray

from .predicates import LARGEST

__all__ = [
    "Box",
    "Capability",
    "Coverage",
    "Crossings",
    "EdgeFacts",
    "FaceFacts",
    "GeometryView",
    "NotAnswerableError",
    "Resolution",
    "Side",
    "Topology",
    "ViewError",
    "ViewProxy",
    "covered",
    "held",
]

Array = NDArray[np.float64]


class Side(enum.IntEnum):
    """What a view says of a point: outside the part, on its surface, inside, or can't tell."""

    OUT = -1
    ON = 0
    IN = 1
    UNKNOWN = 2


class Capability(enum.Enum):
    """A question a view may be able to answer."""

    CLASSIFY = "classify"
    CROSSINGS = "crossings"
    DISTANCE = "distance"
    VOLUME = "volume"
    COVERAGE = "coverage"
    TOPOLOGY = "topology"
    FACES = "faces"
    EDGES = "edges"


class NotAnswerableError(Exception):
    """The view doesn't answer this question (it isn't among its capabilities)."""


class ViewError(Exception):
    """The view answered, but not as the protocol says it must: the part is held."""


def _array(
    value: object,
    shape: tuple[int, ...],
    what: str,
    *,
    floating: bool = False,
    integer: bool = False,
    boolean: bool = False,
) -> None:
    """Is ``value`` a NumPy array of this shape and kind (floats finite)?"""
    if (
        type(value) is not np.ndarray or value.shape != shape
    ):  # no masked or other subclass
        raise ViewError(f"{what} must be a plain array of shape {shape}")
    kind = value.dtype.kind
    if floating and (kind != "f" or not np.isfinite(value).all()):
        raise ViewError(f"{what} must be finite floats")
    if integer and kind not in "iu":
        raise ViewError(f"{what} must be integers")
    if boolean and kind != "b":
        raise ViewError(f"{what} must be booleans")


def _frozen(array: NDArray[np.generic]) -> NDArray[np.generic]:
    array = np.array(array, copy=True)
    array.setflags(write=False)
    return array


@dataclass(frozen=True)
class Box:
    """An axis-aligned box: the least and greatest coordinate along each axis, in mm."""

    lo: tuple[float, float, float]
    hi: tuple[float, float, float]

    def __post_init__(self) -> None:
        if not all(math.isfinite(v) for v in (*self.lo, *self.hi)):
            raise ValueError(f"a box's corners must be finite: {self.lo}, {self.hi}")
        if any(a > b for a, b in zip(self.lo, self.hi, strict=True)):
            raise ValueError(
                f"a box's least corner must not exceed its greatest: {self.lo}, {self.hi}"
            )

    @property
    def size(self) -> tuple[float, float, float]:
        x, y, z = (b - a for a, b in zip(self.lo, self.hi, strict=True))
        return x, y, z

    def grown(self, by: float) -> Box:
        """The box grown by ``by`` every way."""
        (x0, y0, z0), (x1, y1, z1) = self.lo, self.hi
        return Box((x0 - by, y0 - by, z0 - by), (x1 + by, y1 + by, z1 + by))


@dataclass(frozen=True, eq=False)
class Coverage:
    """Points standing for the whole surface, none of it left out.

    Every point of the surface is within ``radius`` of one of ``points``.
    ``normals`` point outwards and are unit; ``patch`` is the face or the
    triangle each point is on; ``tolerance`` is how far the view's surface
    may be from the true one there, in mm.
    """

    points: Array
    normals: Array
    patch: NDArray[np.int64]
    tolerance: Array
    radius: float

    def __post_init__(self) -> None:
        n = len(self.points)
        _array(self.points, (n, 3), "a coverage's points", floating=True)
        _array(self.normals, (n, 3), "a coverage's normals", floating=True)
        _array(self.patch, (n,), "a coverage's patches", integer=True)
        _array(self.tolerance, (n,), "a coverage's tolerances", floating=True)
        if (self.tolerance < 0.0).any():
            raise ViewError("a coverage's tolerances can't be negative")
        length = np.sqrt(fv.dot(self.normals, self.normals))
        if not np.all(np.abs(length - 1.0) <= 1e-9):  # NaN fails too
            raise ViewError("a coverage's normals must be unit")
        if not (
            isinstance(self.radius, float)
            and math.isfinite(self.radius)
            and self.radius > 0
        ):
            raise ViewError("a coverage's radius must be a finite positive float")
        for name in ("points", "normals", "patch", "tolerance"):
            object.__setattr__(self, name, _frozen(getattr(self, name)))


@dataclass(frozen=True, eq=False)
class Crossings:
    """Where rays cross a surface, ahead of their origins.

    One entry per crossing, ordered by ray and then by distance: ``ray`` is
    which ray, ``t`` how far along it (directions are unit), ``entering``
    whether it passes into the material there. ``grazed`` has one entry per
    ray: it passed exactly through an edge or a corner, so a crossing there
    may be counted twice or not at all, and whoever cast it casts again.
    """

    ray: NDArray[np.int64]
    t: Array
    entering: NDArray[np.bool_]
    grazed: NDArray[np.bool_]

    def __post_init__(self) -> None:
        n = len(self.ray)
        _array(self.ray, (n,), "crossings' rays", integer=True)
        _array(self.t, (n,), "crossings' distances", floating=True)
        _array(self.entering, (n,), "crossings' directions", boolean=True)
        _array(self.grazed, (len(self.grazed),), "rays' grazes", boolean=True)
        if (self.t <= 0.0).any():
            raise ViewError("crossings must lie ahead of their rays' origins")
        if n and (self.ray.min() < 0 or self.ray.max() >= len(self.grazed)):
            raise ViewError("a crossing names a ray that wasn't cast")
        order = np.lexsort((self.t, self.ray))
        if not np.array_equal(order, np.arange(n)):
            raise ViewError("crossings must be ordered by ray, then by distance")
        for name in ("ray", "t", "entering", "grazed"):
            object.__setattr__(self, name, _frozen(getattr(self, name)))


@dataclass(frozen=True)
class Topology:
    """How the built surface hangs together.

    - ``shells``: connected pieces of surface;
    - ``solids``, ``voids``: shells that bound material from outside, and
      hollows sealed inside it; counted only on a surface that is otherwise
      sound (``None`` if not);
    - ``open_edges``: edges with one triangle; ``bad_edges``: with three or
      more, or with two running the same way; ``bad_vertices``: corners whose
      triangles don't make one fan; ``bad_triangles``: with a coordinate that
      isn't finite, a repeated corner, or no area;
    - ``self_intersections``: pairs of triangles meeting where they aren't
      joined;
    - ``misnested``: shells whose orientation contradicts where they lie (an
      inside-out part, a solid inside a solid);
    - ``genus``: each solid's through-holes, largest solid first.
    """

    shells: int
    solids: int | None
    voids: int | None
    open_edges: int
    bad_edges: int
    bad_vertices: int
    bad_triangles: int
    self_intersections: int
    misnested: int | None
    genus: tuple[int, ...]

    def __post_init__(self) -> None:
        counts = {name: getattr(self, name) for name in (
            "shells", "solids", "voids", "open_edges", "bad_edges", "bad_vertices",
            "bad_triangles", "self_intersections", "misnested",
        )}  # fmt: skip
        for name, value in counts.items():
            maybe = name in ("solids", "voids", "misnested") and value is None
            if not maybe and (type(value) is not int or value < 0):
                raise ViewError(f"a topology's {name} must be a count, not {value!r}")
        if not isinstance(self.genus, tuple) or any(
            type(g) is not int or g < 0 for g in self.genus
        ):
            raise ViewError(f"a topology's genus must be counts, not {self.genus!r}")

    @property
    def sound(self) -> bool:
        """A closed, consistently oriented, non-self-intersecting surface around at least one solid."""
        return (
            self.shells > 0
            and self.open_edges == 0
            and self.bad_edges == 0
            and self.bad_vertices == 0
            and self.bad_triangles == 0
            and self.self_intersections == 0
            and self.misnested == 0
            and bool(self.solids)
        )


@dataclass(frozen=True)
class FaceFacts:
    """One face, by its geometry only: nothing about how it was made.

    ``kind`` is "plane", "cylinder", "cone", "sphere", "torus" or "other";
    ``surface`` its surface's parameters, so faces on one surface can be merged.
    """

    kind: str
    surface: tuple[float, ...]
    area: float
    bounds: Box


@dataclass(frozen=True)
class EdgeFacts:
    """One edge, by its geometry only: ``kind`` is "line", "circle" or "other"."""

    kind: str
    curve: tuple[float, ...]
    length: float
    bounds: Box


class GeometryView(Protocol):
    """What a view of a built part answers. Points and lengths are in mm."""

    @property
    def source(self) -> str:
        """Where the view comes from: "mesh-file", "brep", "step-file", "implicit"."""
        ...

    @property
    def capabilities(self) -> frozenset[Capability]: ...

    def classify(self, points: Array) -> NDArray[np.int8]:
        """Each point's :class:`Side`."""
        ...

    def distance(self, points: Array) -> Array:
        """Each point's exact distance to the view's surface."""
        ...

    def crossings(self, origins: Array, directions: Array) -> Crossings:
        """Where each ray (unit direction) crosses the surface ahead of its origin."""
        ...

    def volume(self) -> Interval: ...

    def bounds(self) -> Box: ...

    def coverage(self, radius: float, within: Box | None = None) -> Coverage:
        """Points on every face or triangle, every point of the surface within ``radius`` of one; or only where the surface meets the box ``within`` (points of it near the box may come too)."""
        ...

    def topology(self) -> Topology: ...

    def faces(self) -> Sequence[FaceFacts]: ...

    def edges(self) -> Sequence[EdgeFacts]: ...


@dataclass(frozen=True)
class Resolution:
    """How finely a part's surface is covered: within ``radius`` of a point everywhere, and in each box of ``finer`` within its own radius (docs/V2-stage4.md, 13.10).

    The radius at a place is the least of ``radius`` and the radius of each
    finer box that holds it.

    >>> fine = Resolution(0.5, ((Box((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)), 0.1),))
    >>> fine.at(np.array([[0.5, 0.5, 0.5], [3.0, 0.0, 0.0]])).tolist(), fine.finest
    ([0.1, 0.5], 0.1)
    """

    radius: float
    finer: tuple[tuple[Box, float], ...] = ()

    def __post_init__(self) -> None:
        radii = (self.radius, *(r for _, r in self.finer))
        if not all(isinstance(r, float) and math.isfinite(r) and r > 0 for r in radii):
            raise ValueError(
                f"a resolution's radii are finite positive floats: {radii}"
            )
        if any(type(box) is not Box or r >= self.radius for box, r in self.finer):
            raise ValueError(
                "a resolution's finer boxes are Boxes, each finer than its radius everywhere"
            )

    @property
    def finest(self) -> float:
        """The least radius anywhere."""
        return min((self.radius, *(r for _, r in self.finer)))

    @functools.cached_property
    def _boxes(self) -> tuple[Array, Array, Array]:
        """The finer boxes' least and greatest corners, and their radii, as arrays."""
        lo = np.array([box.lo for box, _ in self.finer], dtype=np.float64).reshape(
            -1, 3
        )
        hi = np.array([box.hi for box, _ in self.finer], dtype=np.float64).reshape(
            -1, 3
        )
        return lo, hi, np.array([r for _, r in self.finer], dtype=np.float64)

    def at(self, points: Array, reach: float | Array = 0.0) -> Array:
        """The least radius anywhere within ``reach`` of each point: of ``radius`` and every finer box that comes that near."""
        points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        found = np.full(len(points), self.radius)
        if not self.finer or not len(points):
            return found
        near = np.broadcast_to(np.asarray(reach, dtype=np.float64), (len(points),))[
            :, None
        ]
        lo, hi, radii = self._boxes
        # Only the boxes that come near the points at all are asked about each point.
        finite = np.isfinite(points).all(axis=1)
        if not finite.any():
            return found
        most = float(near.max())
        least, greatest = (
            points[finite].min(axis=0) - most,
            points[finite].max(axis=0) + most,
        )
        for k in np.flatnonzero(
            np.all(lo <= greatest, axis=1) & np.all(hi >= least, axis=1)
        ):
            inside = np.all((points >= lo[k] - near) & (points <= hi[k] + near), axis=1)
            found[inside] = np.minimum(found[inside], radii[k])
        return found

    def within(self, box: Box) -> float:
        """The least radius anywhere in ``box``."""
        found = self.radius
        for finer, r in self.finer:
            if all(
                a <= d and c <= b
                for a, b, c, d in zip(box.lo, box.hi, finer.lo, finer.hi, strict=True)
            ):
                found = min(found, r)
        return found

    def scaled(self, factor: float) -> Resolution:
        """The same resolution ``factor`` times finer everywhere."""
        return Resolution(
            self.radius / factor, tuple((box, r / factor) for box, r in self.finer)
        )


def covered(view: ViewProxy, resolution: Resolution) -> Coverage:
    """The view's coverage at a resolution: every point of its surface within the radius there of a point (docs/V2-stage4.md, 13.10).

    Its coverage everywhere at ``resolution.radius``, and within each finer
    box at that box's radius; a point of one of them more than its own radius
    inside a finer box is left out (every point of the surface outside that
    box is farther than that from it, and every point inside is covered
    finer); and a point the boxes, where they overlap, give again (the same
    place on the same face or triangle), once. With no finer box, the view's
    coverage itself.
    """
    whole = view.coverage(resolution.radius)
    if not resolution.finer:
        return whole
    pieces = [whole, *(view.coverage(r, box) for box, r in resolution.finer)]
    lo, hi, radii = resolution._boxes
    kept: list[NDArray[np.bool_]] = []
    for piece in pieces:
        keep = np.ones(len(piece.points), dtype=bool)
        for k in np.flatnonzero(radii < piece.radius):
            deep = np.all(
                (piece.points > lo[k] + piece.radius)
                & (piece.points < hi[k] - piece.radius),
                axis=1,
            )
            keep &= ~deep
        kept.append(keep)
    points = np.concatenate([p.points[k] for p, k in zip(pieces, kept, strict=True)])
    patch = np.concatenate([p.patch[k] for p, k in zip(pieces, kept, strict=True)])
    _, first = np.unique(
        np.column_stack([points, patch.astype(np.float64)]), axis=0, return_index=True
    )
    once = np.sort(first)
    return Coverage(
        points[once],
        np.concatenate([p.normals[k] for p, k in zip(pieces, kept, strict=True)])[once],
        patch[once],
        np.concatenate([p.tolerance[k] for p, k in zip(pieces, kept, strict=True)])[
            once
        ],
        float(resolution.radius),
    )


def held(coverage: Coverage) -> Coverage:
    """A coverage made read-only, to be kept and handed to every caller alike (none can change it for the next)."""
    for array in (
        coverage.points,
        coverage.normals,
        coverage.patch,
        coverage.tolerance,
    ):
        array.setflags(write=False)
    return coverage


_SIDES = np.array([Side.OUT, Side.ON, Side.IN, Side.UNKNOWN], dtype=np.int8)

#: The protocol's questions, and the capability each needs (bounds: none).
_QUESTIONS: dict[str, Capability | None] = {
    "classify": Capability.CLASSIFY,
    "distance": Capability.DISTANCE,
    "near": Capability.DISTANCE,
    "crossings": Capability.CROSSINGS,
    "volume": Capability.VOLUME,
    "bounds": None,
    "coverage": Capability.COVERAGE,
    "topology": Capability.TOPOLOGY,
    "faces": Capability.FACES,
    "edges": Capability.EDGES,
}


def _points(points: Array, what: str) -> Array:
    array = np.ascontiguousarray(points, dtype=np.float64)
    if array.ndim != 2 or array.shape[1] != 3:
        raise ValueError(f"{what} must be an (n, 3) array, not {array.shape}")
    if not np.isfinite(array).all() or (np.abs(array) > LARGEST).any():
        raise ValueError(f"{what} must be finite and within {LARGEST:g} mm")
    return array


def _unit(directions: Array) -> Array:
    """Directions made unit, however large or small they were written."""
    biggest = np.abs(directions).max(axis=1)
    if (biggest == 0.0).any():
        raise ValueError("a ray needs a direction")
    scaled = directions / biggest[:, None]
    return np.asarray(scaled / np.sqrt(fv.dot(scaled, scaled))[:, None])


class ViewProxy:
    """A view, as the checks may see it: the protocol's questions, checked both ways.

    Whatever goes wrong inside the view (it raises, or answers out of
    contract) is a :class:`ViewError`; only a question the view doesn't
    answer is :class:`NotAnswerableError`.
    """

    __slots__ = ("_answer", "capabilities", "source")

    source: str
    capabilities: frozenset[Capability]
    _answer: Callable[..., object]

    def __init__(self, view: GeometryView) -> None:
        try:
            source, capabilities = view.source, frozenset(view.capabilities)
        except Exception as error:  # a view that can't even say what it is
            raise ViewError(f"the view can't say what it is: {error!r}") from error
        if (
            type(source) is not str or not source
        ):  # a plain string: nothing that can misbehave
            raise ViewError("a view must say where it comes from")
        if not all(isinstance(c, Capability) for c in capabilities):
            raise ViewError("a view's capabilities must be Capability values")

        def answer(question: str, *args: object) -> object:
            if question not in _QUESTIONS:
                raise AttributeError(f"{question!r} isn't a question views answer")
            if question == "near" and not hasattr(view, "near"):
                # The protocol's own answer, for a view with no faster one.
                points, tolerances = args
                return np.asarray(view.distance(points)) <= tolerances  # type: ignore[arg-type,operator]
            return getattr(view, question)(*args)

        object.__setattr__(self, "source", source)
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "_answer", answer)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("a view proxy can't be changed")

    def __repr__(self) -> str:
        names = ", ".join(sorted(c.value for c in self.capabilities))
        return f"ViewProxy({self.source}: {names})"

    def _ask(self, question: str, *args: object) -> object:
        need = _QUESTIONS[question]
        if need is not None and need not in self.capabilities:
            raise NotAnswerableError(f"a {self.source} view doesn't answer {question}")
        try:
            return self._answer(question, *args)
        except NotAnswerableError:
            raise
        except Exception as error:  # anything else the view does wrong holds the part
            raise ViewError(
                f"the view failed to answer {question}: {error!r}"
            ) from error

    def classify(self, points: Array) -> NDArray[np.int8]:
        asked = _points(points, "points")
        sides = self._ask("classify", asked)
        if (
            type(sides) is not np.ndarray
            or sides.shape != (len(asked),)
            or sides.dtype.kind not in "iu"
            or not np.isin(sides, _SIDES).all()
        ):
            raise ViewError("classify must give one Side per point, as integers")
        return np.asarray(sides, dtype=np.int8)

    def distance(self, points: Array) -> Array:
        asked = _points(points, "points")
        found = self._ask("distance", asked)
        _array(found, (len(asked),), "distances", floating=True)
        assert isinstance(found, np.ndarray)
        if (found < 0.0).any():
            raise ViewError("distances can't be negative")
        return np.asarray(found, dtype=np.float64)

    def near(self, points: Array, tolerances: Array) -> NDArray[np.bool_]:
        """Whether each point is within its tolerance of the surface: ``distance(points) <= tolerances``.

        A view may answer it faster than measuring every distance (the B-rep
        certifies most points with a foot on a face); a view with no faster
        answer is asked the distances.
        """
        asked = _points(points, "points")
        t = np.ascontiguousarray(
            np.broadcast_to(np.asarray(tolerances, dtype=np.float64), (len(asked),))
        )
        if not np.isfinite(t).all() or (t < 0.0).any():
            raise ValueError("a tolerance is finite and not negative")
        found = self._ask("near", asked, t)
        if (
            type(found) is not np.ndarray
            or found.shape != (len(asked),)
            or found.dtype != np.bool_
        ):
            raise ViewError("near must give one bool per point")
        return found

    def crossings(self, origins: Array, directions: Array) -> Crossings:
        start = _points(origins, "origins")
        way = np.ascontiguousarray(directions, dtype=np.float64)
        if way.shape != start.shape or not np.isfinite(way).all():
            raise ValueError("one finite direction per origin")
        found = self._ask("crossings", start, _unit(way))
        if type(found) is not Crossings or found.grazed.shape != (len(start),):
            raise ViewError("crossings must be Crossings, with one grazed flag per ray")
        return found

    def volume(self) -> Interval:
        found = self._ask("volume")
        if type(found) is not Interval:
            raise ViewError("volume must be an Interval")
        return found

    def bounds(self) -> Box:
        found = self._ask("bounds")
        if type(found) is not Box:
            raise ViewError("bounds must be a Box")
        return found

    def coverage(self, radius: float, within: Box | None = None) -> Coverage:
        if not (math.isfinite(radius) and radius > 0.0):
            raise ValueError("a coverage radius must be finite and positive")
        if within is not None and type(within) is not Box:
            raise ValueError("a coverage is within a Box")
        found = (
            self._ask("coverage", float(radius))
            if within is None
            else self._ask("coverage", float(radius), within)
        )
        if type(found) is not Coverage:
            raise ViewError("coverage must be a Coverage")
        if found.radius > radius:
            raise ViewError(
                f"coverage asked to {radius} mm came back at {found.radius} mm"
            )
        return found

    def topology(self) -> Topology:
        found = self._ask("topology")
        if type(found) is not Topology:
            raise ViewError("topology must be a Topology")
        return found

    def faces(self) -> Sequence[FaceFacts]:
        found = self._ask("faces")
        if not isinstance(found, Sequence) or not all(
            type(f) is FaceFacts for f in found
        ):
            raise ViewError("faces must be FaceFacts")
        return tuple(found)

    def edges(self) -> Sequence[EdgeFacts]:
        found = self._ask("edges")
        if not isinstance(found, Sequence) or not all(
            type(e) is EdgeFacts for e in found
        ):
            raise ViewError("edges must be EdgeFacts")
        return tuple(found)
