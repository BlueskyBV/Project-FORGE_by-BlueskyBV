"""The spec's own shape: every item made in order, from the definitions alone.

The oracle works out, from a confirmed spec and the judge's own placement
(:mod:`forge_checks.place`), the solid the spec describes: each item's exact
solids (:mod:`forge_checks.shapes`), added or taken away in the order the
part is made (docs/definitions/frame.md). It never sees how the part was
built, nor the solver's coordinates.

**Steps.** The part is a sequence of steps, each adding a solid to what is
made so far or taking one away: a body or a standing feature adds; a cut
takes away; a hollowed body adds itself less its hollow (the shell hollows
that body alone, never what stands on it). A feature standing round a side
is the solid its definition gives: its cross-section, out to its height,
on the open side of the side's round surface, so its foot follows the curve.

**Where the shape isn't known exactly** (docs/V2-stage2.md, section 5.2), a
step has two forms, an *inner* and an *outer*: what the made part must at
least hold there, and what it may hold at most. A point between them is
neither surely in nor surely out (:data:`~forge_checks.view.Side.UNKNOWN`):

- letters: inside the box round their line, cut in or standing out to their
  depth (their outlines come from the font, in stage 4);
- a region: its envelope (it is designed later, within it);
- a rounding's or a chamfer's zones: balls round where its edges meet at an
  angle, where it stops at something over its edge, where two of its runs
  end together, and along an edge on a round side (:mod:`forge_checks.rounds`);
- a thread: between its minor and major cylinders, over its length (where
  its helix starts round the axis is not the spec's to say; its profile is
  held by the thread's own check, at the turn the built thread has).

Roundings and chamfers are exact everywhere else.

Each is listed in :attr:`Oracle.unchecked`, with the reason.

**Classifying** a point replays the steps in order. Each solid says, from
its exact signed distance, whether the point is inside, outside, or within
:data:`~forge_checks.shapes.ON` of its surface. A point on no surface is
settled at once. A point on one or more surfaces (a post's foot on the plate
it stands on, a through hole's floor in the plate's far face, a hollow's
open face) is settled exactly from the first-order shape of every solid
there: the half-spaces of the facets it is on. Each cell of the sphere of
directions those facets' planes divide is tried once, from beside a corner
where the planes meet, and the steps replayed for it: a point every cell
puts inside is inside; every cell outside, outside; otherwise it is on the
part's surface. A cone's apex has no such model: a point there is UNKNOWN.

>>> from forge_spec.draft import read_draft
>>> plate = {"id": "plate", "kind": "block", "words": [0], "length": {"value": 80, "unit": "mm",
...          "from": {"assumed": "x"}}, "width": {"value": 50, "unit": "mm", "from": {"assumed": "x"}},
...          "height": {"value": 5, "unit": "mm", "from": {"assumed": "x"}}}
>>> hole = {"id": "h", "kind": "hole", "words": [0], "on": {"item": "plate", "face": "+z"},
...         "diameter": {"value": 6, "unit": "mm", "from": {"assumed": "x"}},
...         "depth": {"through": True, "from": {"assumed": "x"}}}
>>> spec, _ = read_draft({"spec_format": 1, "name": "p", "items": [plate, hole]})
>>> from forge_checks.place import place
>>> part = oracle(spec, place(spec))
>>> import numpy as np
>>> part.classify(np.array([[10, 0, 2.5], [0, 0, 2.5], [0, 0, 0], [3, 0, 2.5], [40, 0, 5]])).tolist()
[1, -1, -1, 0, 0]
"""

from __future__ import annotations

import functools
import itertools
import math
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace

import numpy as np
from forge_numeric import scalar as fs
from forge_numeric import vector as fv
from forge_spec.draft import (
    EdgeSet,
    Item,
    PartSpec,
    Text,
)
from forge_units import Interval
from numpy.typing import NDArray

from . import rounds
from .convex import Side as OutlineSide
from .convex import sides_in_turn
from .csg import Inter, Minus, Node, Union, bound, box, leaves, toward, toward_all
from .csg import box as csg_box
from .items.oracle import ORACLE
from .items.oracle._shapes import (
    Array,
    OracleError,
    Vec,
    Vec3,
    _axis,
    _frame,
    _mm,
    _outline_boundary,
    _outline_chain,
    _unit2,
    _vec,
)
from .letters import Letters2D
from .moved import moved_chain, moved_node, upright
from .outlines import Arc as OutlineArc
from .outlines import Segment as OutlineSegment
from .place import (
    Copy,
    FlatFace,
    Placed,
    RoundSide,
    body_edges,
    direction_of,
    section_of,
)
from .shapes import (
    INSIDE,
    ON,
    SINGULAR,
    SURFACE,
    Ball,
    Complement,
    ConePatch,
    Disc,
    FlatPatch,
    Flipped,
    Frame,
    Frustum,
    Halfspace,
    Local,
    Locals,
    Patch,
    Polygon,
    Prism,
    Revolved,
    Round,
    RoundPatch,
    RoundRect,
    Shape2D,
    Solid,
    SpherePatch,
    Torus,
    TorusPatch,
    patches,
)
from .tree import Tree
from .view import Box, Resolution, Side

__all__ = [
    "BOTH",
    "COARSE_PITCH",
    "INNER",
    "OFF",
    "OUTER",
    "Along",
    "CannotMakeError",
    "ExpectedTopology",
    "Inter",
    "Minus",
    "Node",
    "Oracle",
    "OracleCoverage",
    "OracleError",
    "Rounded",
    "Step",
    "Surface",
    "Unchecked",
    "Union",
    "bound",
    "box",
    "oracle",
    "probes",
    "thread_pitch",
]


_INF = math.inf

#: Which form of the part a step belongs to.
BOTH, INNER, OUTER = "both", "inner", "outer"


# ----------------------------------------------------------------------
# The sphere of directions round a point on several surfaces
# ----------------------------------------------------------------------
_THROUGH = 1e-12


def _cross3(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _dot3(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _unit3(a: Vec3) -> Vec3:
    n = math.sqrt(_dot3(a, a))
    return (a[0] / n, a[1] / n, a[2] / n)


def probes(normals: Sequence[NDArray[np.float64]]) -> Array:
    """One direction inside every cell the planes through a point with these normals make.

    Each cell of the sphere is a spherical polygon whose corners are where
    two of the planes' great circles cross. Round each such corner the
    circles through it divide the directions into sectors; one direction a
    little way into each sector, less far than the nearest other circle, is
    in the cell that sector opens. With one circle, its two sides. (Worked
    in plain floats: a point is settled this way thousands of times a part,
    and a few planes' vectors cost numpy more to hold than to work.)
    """
    circles: list[Vec3] = []
    for n in normals:
        u = _unit3((float(n[0]), float(n[1]), float(n[2])))
        if not any(abs(_dot3(c, u)) > 1 - _THROUGH for c in circles):
            circles.append(u)
    if not circles:
        return np.eye(3)
    if len(circles) == 1:
        c = circles[0]
        return np.array([c, (-c[0], -c[1], -c[2])])
    found: list[Vec3] = []
    for i in range(len(circles)):
        for j in range(i + 1, len(circles)):
            w = _unit3(_cross3(circles[i], circles[j]))
            for corner in (w, (-w[0], -w[1], -w[2])):
                dots = [_dot3(c, corner) for c in circles]
                through = [
                    c for c, d in zip(circles, dots, strict=True) if abs(d) <= _THROUGH
                ]
                apart = [fs.asin(min(abs(d), 1.0)) for d in dots if abs(d) > _THROUGH]
                step = 0.5 * min([*apart, 2e-3])
                tangents: list[Vec3] = []
                for c in through:
                    t = _unit3(_cross3(corner, c))
                    tangents += [t, (-t[0], -t[1], -t[2])]
                e1 = tangents[0]
                e2 = _cross3(corner, e1)
                angles = sorted(
                    (fs.atan2(_dot3(t, e2), _dot3(t, e1)) % (2 * math.pi), k)
                    for k, t in enumerate(tangents)
                )
                near, out = fs.cos(step), fs.sin(step)
                for k in range(len(angles)):
                    a0 = angles[k][0]
                    a1 = angles[(k + 1) % len(angles)][0] + (
                        2 * math.pi if k + 1 == len(angles) else 0.0
                    )
                    middle = (a0 + a1) / 2
                    cm, sm = fs.cos(middle), fs.sin(middle)
                    b = (
                        cm * e1[0] + sm * e2[0],
                        cm * e1[1] + sm * e2[1],
                        cm * e1[2] + sm * e2[2],
                    )
                    found.append((near * corner[0] + out * b[0], near * corner[1] + out * b[1],
                                  near * corner[2] + out * b[2]))  # fmt: skip
    return np.array(found)


# ----------------------------------------------------------------------
# Steps and the oracle
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class Step:
    """Add a solid to what is made so far, or take one away; in both forms of the part, or one."""

    item: str
    copy: int
    adds: bool
    node: Node
    form: str = BOTH
    #: A rounding's or a chamfer's: made at the part's surface, never a passage or a hollow.
    finish: bool = False
    lo: Vec = field(init=False)
    hi: Vec = field(init=False)

    def __post_init__(self) -> None:
        lo, hi = box(self.node)
        if not all(math.isfinite(v) for v in (*lo, *hi)):
            raise ValueError(f"{self.item}: a step's solid is bounded")
        object.__setattr__(self, "lo", lo)
        object.__setattr__(self, "hi", hi)


@dataclass(frozen=True)
class Rounded:
    """One stretch of an edge a rounding or a chamfer rounds exactly: its edge, from ``a`` to ``b`` along it.

    ``fill``: it fills an inside corner (else it takes an outside one away).
    The checks measure the rounding's surface along it.
    """

    item: str
    copy: int
    edge: rounds.Edge
    a: float
    b: float
    size: float
    fillet: bool
    fill: bool


@dataclass(frozen=True)
class Unchecked:
    """What the oracle doesn't know exactly, and why: shown before building, and in the report."""

    item: str
    why: str


@dataclass(frozen=True)
class Oracle:
    """The spec's own shape."""

    steps: tuple[Step, ...]
    unchecked: tuple[Unchecked, ...]
    lo: Vec
    hi: Vec
    _tree: Tree = field(repr=False, compare=False)
    #: Every stretch of an edge a rounding rounds exactly, as the checks measure it.
    rounded: tuple[Rounded, ...] = ()

    # ------------------------------------------------------------------
    def classify(self, points: Array) -> NDArray[np.int8]:
        """Each point: IN, OUT, ON (within :data:`~forge_checks.shapes.ON` of the surface) or UNKNOWN.

        UNKNOWN where the shape isn't known exactly there (between its inner
        and outer forms), and at a cone's apex.
        """
        inner, outer = self._replay(np.asarray(points, dtype=np.float64))
        found = np.full(len(points), Side.UNKNOWN, dtype=np.int8)
        same = inner == outer
        found[same] = inner[same]
        found[(inner == Side.IN) & (outer != Side.UNKNOWN)] = Side.IN
        found[(outer == Side.OUT) & (inner != Side.UNKNOWN)] = Side.OUT
        return found

    def limits(self, points: Array) -> tuple[NDArray[np.int8], NDArray[np.int8]]:
        """Each point's side of the part's inner form (what it must hold) and its outer form (all it may hold)."""
        return self._replay(np.asarray(points, dtype=np.float64))

    def surfaces(self) -> tuple[Surface, ...]:
        """Every smooth piece of every solid of every step: where the part's surface can be."""
        return _surfaces(self)

    @functools.cached_property
    def apexes(self) -> Array:
        """Every point where a cone of a step's solids comes to a point, (n, 3)."""
        found = {
            p
            for step in self.steps
            for leaf in leaves(step.node)
            for p in leaf.apexes()
        }
        return np.array(sorted(found), dtype=np.float64).reshape(-1, 3)

    def witness(self, points: Array, radius: float | Array) -> NDArray[np.bool_]:
        """Whether a place the part's surface may be comes within ``radius`` of each point, shown by a point of it found there (see :func:`_witness`)."""
        return _witness(self, np.asarray(points, dtype=np.float64), radius)

    def coverage(
        self, radius: float | Resolution, finest: float | None = None
    ) -> OracleCoverage:
        """Points on the part's surface, every point of it within ``radius`` of one, or within the radius a :class:`~.view.Resolution` has there (see :class:`OracleCoverage`).

        ``finest``: a sixteenth of the radius everywhere unless given; in a
        finer box, as much finer again. Made once for each radius and kept,
        read-only: every view of the part is accounted for against the same
        points.
        """
        resolution = (
            radius if isinstance(radius, Resolution) else Resolution(float(radius))
        )
        key = (resolution, float(resolution.radius / 16 if finest is None else finest))
        found = self._covered.get(key)
        if found is None:
            found = _coverage(self, *key)
            for array in (found.points, found.normals, found.surface):
                array.setflags(write=False)
            self._covered[key] = found
        return found

    @functools.cached_property
    def _covered(self) -> dict[tuple[Resolution, float], OracleCoverage]:
        return {}

    def volume(self, rel: float = 1e-3, budget: int = 4_000_000) -> Interval:
        """The part's volume: an interval that holds it, from both its forms (see :func:`_volume`)."""
        return _volume(self, rel, budget)

    def expected_topology(self, resolution: float | None = None) -> ExpectedTopology:
        """How many solids and sealed voids the part has (see :func:`_topology`)."""
        return _topology(self, resolution)

    def held(
        self, point: Array, ways: Array, finished: bool = True
    ) -> tuple[NDArray[np.bool_], NDArray[np.bool_]] | None:
        """Whether the part holds the points just off ``point`` along each of ``ways``: in its inner form, and its outer.

        From the first-order shape of every step's solids at the point (as a
        point on surfaces is settled); None where that has no first-order
        shape (a cone's apex). ``finished``: with its roundings and chamfers
        (else as if they weren't made).
        """
        point = np.asarray(point, dtype=np.float64)
        ways = np.asarray(ways, dtype=np.float64)
        inner, outer, known = self.held_all(point[None, :], ways[None, :, :], finished)
        if not known[0]:
            return None
        return inner[0], outer[0]

    def held_all(
        self, points: Array, ways: Array, finished: bool = True
    ) -> tuple[NDArray[np.bool_], NDArray[np.bool_], NDArray[np.bool_]]:
        """:meth:`held` for many points at once, each with its own ``ways`` (points, ways, 3): the inner and outer forms' answers (points, ways), and where they are known (not at a singular point).

        Each step's solids are asked about all the points near them
        together, their answers for each point's ways read off the models
        (:func:`toward_all`), and the steps folded in order: each point's own
        steps, as :meth:`held` folds them one point at a time.

        A way that runs along a facet of a solid at the point (square to its
        normal) is on that solid's surface to first order, so the models
        can't say what is just off along it: two solids sharing that facet
        (an outline's convex pieces, an item standing flush on another) hold
        it between them, one alone doesn't. Such a way is held where every
        way a hair to either side of each facet it runs along is
        (:data:`_GRAZE`, :data:`_NUDGE`).
        """
        points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        ways = np.asarray(ways, dtype=np.float64).reshape(len(points), -1, 3)
        inner, outer, known, grazed = self._held_once(points, ways, finished)
        rows, cols = np.nonzero(np.any(np.any(grazed != 0.0, axis=3), axis=2))
        if not len(rows):
            return inner, outer, known
        at: list[Array] = []
        nudged: list[Array] = []
        owner: list[int] = []
        for n, (p, w) in enumerate(zip(rows, cols, strict=True)):
            facets = [m for m in grazed[p, w] if np.any(m != 0.0)]
            for signs in itertools.product((1.0, -1.0), repeat=len(facets)):
                way = ways[p, w] + _NUDGE * sum(
                    (s * m for s, m in zip(signs, facets, strict=True)), np.zeros(3)
                )
                at.append(points[p])
                nudged.append(way / fv.norm(way))
                owner.append(n)
        more_inner, more_outer, more_known, _ = self._held_once(
            np.asarray(at), np.asarray(nudged)[:, None, :], finished
        )
        mine = np.asarray(owner)
        for n, (p, w) in enumerate(zip(rows, cols, strict=True)):
            these = mine == n
            inner[p, w] = bool(np.all(more_inner[these, 0]))
            outer[p, w] = bool(np.all(more_outer[these, 0]))
            known[p] &= bool(np.all(more_known[these]))
        return inner, outer, known

    def _held_once(self, points: Array, ways: Array, finished: bool) -> tuple[
            NDArray[np.bool_], NDArray[np.bool_], NDArray[np.bool_], Array]:  # fmt: skip
        """:meth:`held_all` from the models alone, and for each point's way the normals (up to two) of the facets it runs along (else 0)."""
        n, k = ways.shape[0], ways.shape[1]
        held = {
            INNER: np.zeros((n, k), dtype=bool),
            OUTER: np.zeros((n, k), dtype=bool),
        }
        known = np.ones(n, dtype=bool)
        grazed = np.zeros((n, k, 2, 3))
        if not n:
            return held[INNER], held[OUTER], known, grazed
        pairs_point: list[NDArray[np.int64]] = []
        pairs_step: list[NDArray[np.int64]] = []
        for p, s in self._tree.within(points, np.full(n, 2 * ON)):
            pairs_point.append(p)
            pairs_step.append(s)
        if not pairs_point:
            return held[INNER], held[OUTER], known, grazed
        point_of, step_of = np.concatenate(pairs_point), np.concatenate(pairs_step)
        order = np.lexsort((point_of, step_of))
        point_of, step_of = point_of[order], step_of[order]
        for index, first, last in _groups(step_of):
            rows = np.unique(point_of[first:last])
            step = self.steps[index]
            answers: list[NDArray[np.bool_]] = []
            for leaf in leaves(step.node):
                found = leaf.locals(points[rows])
                known[rows[found.where == SINGULAR]] = False
                normals = np.nan_to_num(found.normals.reshape(len(rows), -1, 3))
                unused = np.isnan(
                    found.normals.reshape(len(rows), -1, 3)[:, None, :, 0]
                )
                dots = fv.matmul(ways[rows], np.swapaxes(normals, 1, 2))
                on = found.held(dots, unused)
                on = ~on if found.inverted else on
                answers.append(
                    np.where(
                        (found.where == SURFACE)[:, None],
                        on,
                        (found.where == INSIDE)[:, None],
                    )
                )
                along = (
                    (found.where == SURFACE)[:, None, None]
                    & ~unused
                    & (np.abs(dots) <= _GRAZE)
                )
                for r, w, slot in zip(*np.nonzero(along), strict=True):
                    m = normals[r, slot]
                    seen = grazed[rows[r], w]
                    if any(
                        abs(float(fv.matmul(m, g))) > 1.0 - 1e-9
                        for g in seen
                        if np.any(g != 0.0)
                    ):
                        continue  # the same facet's plane, from another solid sharing it
                    free = [i for i in range(2) if not np.any(seen[i] != 0.0)]
                    if free:
                        grazed[rows[r], w, free[0]] = m
            here = toward_all(step.node, iter(answers))
            for form in (INNER, OUTER):
                if step.form not in (BOTH, form) or (step.finish and not finished):
                    continue
                held[form][rows] = (
                    held[form][rows] | here if step.adds else held[form][rows] & ~here
                )
        return held[INNER], held[OUTER], known, grazed

    def along(self, origins: Array, directions: Array, lengths: Array) -> Along:
        """The part along each segment ``origins[i] + t directions[i]``, ``0 <= t <= lengths[i]`` (see :func:`_along`)."""
        return _along(self, origins, directions, lengths)

    def around(self, centre: Array, u: Array, v: Array, radius: float) -> Array:
        """The places round the circle ``centre + radius (cos a u + sin a v)`` where the part can change: angles in [0, 2 pi) (see :func:`_around`)."""
        return _around(self, centre, u, v, radius)

    def bound(self, points: Array, form: str = OUTER, reach: float = 0.0) -> Array:
        """A function negative inside the part's form and positive outside, its steps' bounds folded in order: its sign exact, and its size, up to ``reach``, at most each point's distance from the form's surface.

        Only the steps whose boxes come within ``reach`` of a point are
        folded for it, so a size beyond ``reach`` says only that the surface
        is farther than ``reach``: ``abs(bound) >= reach`` is how a point is
        known to be at least ``reach`` from it.
        """
        return _fold(self, np.asarray(points, dtype=np.float64), form, reach)

    # ------------------------------------------------------------------
    def _replay(self, points: Array) -> tuple[NDArray[np.int8], NDArray[np.int8]]:
        """Each point's side of the inner form and the outer, :data:`AT_ONCE` points at a time (the models found alike shared between them)."""
        if points.ndim != 2 or points.shape[1] != 3 or not np.all(np.isfinite(points)):
            raise ValueError("points are finite, (n, 3)")
        known: dict[tuple[object, ...], int] = {}
        if len(points) <= AT_ONCE:
            return self._replay_some(points, known)
        parts = [
            self._replay_some(points[start : start + AT_ONCE], known)
            for start in range(0, len(points), AT_ONCE)
        ]
        return (
            np.concatenate([inner for inner, _ in parts]),
            np.concatenate([outer for _, outer in parts]),
        )

    def _replay_some(
        self, points: Array, known: dict[tuple[object, ...], int]
    ) -> tuple[NDArray[np.int8], NDArray[np.int8]]:
        n = len(points)
        pairs_point: list[NDArray[np.int64]] = []
        pairs_step: list[NDArray[np.int64]] = []
        for p, s in self._tree.within(points, np.full(n, 2 * ON)):
            pairs_point.append(p)
            pairs_step.append(s)
        point_of = (
            np.concatenate(pairs_point) if pairs_point else np.zeros(0, dtype=np.int64)
        )
        step_of = (
            np.concatenate(pairs_step) if pairs_step else np.zeros(0, dtype=np.int64)
        )
        order = np.lexsort((point_of, step_of))
        point_of, step_of = point_of[order], step_of[order]
        held = {INNER: np.zeros(n, dtype=bool), OUTER: np.zeros(n, dtype=bool)}
        unsure = {INNER: np.zeros(n, dtype=bool), OUTER: np.zeros(n, dtype=bool)}
        cuts = np.flatnonzero(np.diff(step_of)) + 1
        for chunk in np.split(np.arange(len(step_of)), cuts):
            if not len(chunk):
                continue
            step = self.steps[int(step_of[chunk[0]])]
            rows = point_of[chunk]
            d = bound(step.node, points[rows], ON)
            inside, near = d < -ON, np.abs(d) <= ON
            for form in (INNER, OUTER):
                if step.form not in (BOTH, form):
                    continue
                if step.adds:
                    held[form][rows] |= inside
                else:
                    held[form][rows] &= ~inside
                unsure[form][rows] |= near
        # The few points on a surface: each one's steps, grouped by point once,
        # and each step's solids asked about all its points at once.
        either = unsure[INNER] | unsure[OUTER]
        chosen = either[point_of]
        rows_of_step = {
            int(step_of[chosen][start]): point_of[chosen][start:stop]
            for _, start, stop in _groups(step_of[chosen])
        }
        settle = _Settle(self, points, rows_of_step, known)
        result = []
        for form in (INNER, OUTER):
            side = np.where(held[form], Side.IN, Side.OUT).astype(np.int8)
            asked = np.flatnonzero(unsure[form])
            # On a solid's surface but off the form's (a ball's surface in the
            # air): the steps' bounds folded say which side, by more than ON.
            folded = _fold(self, points[asked], form, 2 * ON, ON)
            clear = np.abs(folded) > ON
            side[asked[clear]] = np.where(
                folded[clear] < 0, int(Side.IN), int(Side.OUT)
            )
            rows = asked[~clear]
            if len(rows):
                allowed = np.array([st.form in (BOTH, form) for st in self.steps])
                group, kept = _step_sets(point_of, step_of, rows, allowed, n)
                side[rows] = settle.many(rows, group, kept)
            result.append(side)
        return result[0], result[1]


_MIX = np.uint64(0xBF58476D1CE4E5B9)  # splitmix64's first multiplier
_SHIFT = np.uint64(31)


def _alike(table: Array) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
    """The table's distinct rows: one row of each, and which one each row is.

    Rows are told apart by a hash of their bits (one pass over the columns,
    no sort of rows), then checked whole against the row they were taken
    for; should two different rows share a hash, the rows are sorted after
    all. Rows alike to the bit are alike here, so the answer is exact.
    """
    bits = np.ascontiguousarray(table).view(np.uint64)
    mixed = np.full(len(bits), 0xCBF29CE484222325, dtype=np.uint64)
    for column in bits.T:
        mixed = (mixed ^ column) * _MIX
        mixed ^= mixed >> _SHIFT  # high bits (signs) down, so they never cancel
    _, first, which = np.unique(mixed, return_index=True, return_inverse=True)
    which = which.reshape(-1)
    if not np.array_equal(bits, bits[first[which]]):
        _, first, which = np.unique(
            bits, axis=0, return_index=True, return_inverse=True
        )
        which = which.reshape(-1)
    return first.astype(np.int64), which.astype(np.int64)


#: Points a view's classification settles at a time: while it is settled, a point on a surface holds every
#: facet's normal of the solids round it, so a million of them at once would hold gigabytes.
AT_ONCE = 100_000


class _Settle:
    """Points on surfaces, settled exactly, many at a time.

    Each step's solids are asked about all the points near them at once
    (:meth:`~forge_checks.shapes.Solid.locals`). Points whose first-order
    models are the same (a hole's floor all across the plate's far face) are
    settled once: the directions round a point and the replay depend on
    nothing else. The models are compared as rows of one table, so finding
    the points alike costs no work point by point.
    """

    def __init__(
        self,
        part: Oracle,
        points: Array,
        rows_of_step: dict[int, NDArray[np.int64]],
        known: dict[tuple[object, ...], int],
    ) -> None:
        self.part = part
        self.models: dict[int, tuple[NDArray[np.int64], list[Locals]]] = {}
        for k, rows in rows_of_step.items():
            found = [leaf.locals(points[rows]) for leaf in leaves(part.steps[k].node)]
            position = np.full(len(points), -1, dtype=np.int64)
            position[rows] = np.arange(len(rows))
            self.models[k] = (position, found)
        #: Each set of models already replayed, and its answer: the same for points settled together or apart.
        self.known = known

    def many(
        self,
        rows: NDArray[np.int64],
        group: NDArray[np.int64],
        steps: list[tuple[int, ...]],
    ) -> NDArray[np.int8]:
        """Each point's side of a form: every cell of directions round it, its steps (``steps[group[i]]``, the form's only) replayed for each."""
        found = np.empty(len(rows), dtype=np.int8)
        order = np.argsort(group, kind="stable")
        for g, start, stop in _groups(group[order]):
            kept = steps[g]
            at = order[start:stop]
            r = rows[at]
            columns = []
            for k in kept:
                position, solids = self.models[k]
                p = position[r]
                for local in solids:
                    columns.append(local.where[p].astype(np.float64)[:, None])
                    columns.append(local.normals[p].reshape(len(p), -1))
            if not columns:
                found[at] = self._replay([])
                continue
            table = np.concatenate(columns, axis=1) + 0.0  # -0 as 0
            table = np.where(np.isnan(table), 9.0, table)  # no normal's part is 9
            first, which = _alike(table)
            sides = np.empty(len(first), dtype=np.int8)
            plain = self._plain(kept, r[first], sides)
            for u in np.flatnonzero(~plain).tolist():
                key = (kept, table[first[u]].tobytes())
                if key not in self.known:
                    row = int(r[first[u]])
                    models = []
                    for k in kept:
                        position, solids = self.models[k]
                        models.append(
                            (k, [local[int(position[row])] for local in solids])
                        )
                    self.known[key] = self._replay(models)
                sides[u] = self.known[key]
            found[at] = sides[which]
        return found

    def _plain(
        self, kept: tuple[int, ...], rows: NDArray[np.int64], sides: NDArray[np.int8]
    ) -> NDArray[np.bool_]:
        """Settle at once, into ``sides``, the points whose facets' normals lie along one line or two (on one smooth surface, or on an edge where two meet); which they were.

        Round such a point the planes through it with those normals cut the
        directions into two cells (``±n``) or four, one for each pair of
        signs ``(d·n1, d·n2)``: ``d = ±n1 ± n2`` is in each (``|n1·n2| < 1``),
        as :func:`probes`'s directions are. Each leaf's answer in every cell
        is read off its model for all the points together, and the steps are
        replayed on those answers as :meth:`_replay` replays them one by one.
        A point on three lines or more (a corner) is left to it.
        """
        wheres: list[NDArray[np.int8]] = []
        normals: list[Array] = []
        inverted: list[bool] = []
        grouped: list[NDArray[np.int64] | None] = []
        for k in kept:
            position, solids = self.models[k]
            p = position[rows]
            for local in solids:
                wheres.append(local.where[p])
                normals.append(local.normals[p].reshape(len(p), -1, 3))
                inverted.append(local.inverted)
                grouped.append(None if local.groups is None else local.groups[p])
        if not wheres:
            return np.zeros(len(rows), dtype=bool)
        singular = np.any(np.stack(wheres, axis=1) == SINGULAR, axis=1)
        facets = np.concatenate(
            [
                np.where((w == SURFACE)[:, None, None], n, np.nan)
                for w, n in zip(wheres, normals, strict=True)
            ],
            axis=1,
        )  # (points, facets, 3), NaN where unused
        used = ~np.isnan(facets[:, :, 0])
        lengths = np.where(used, fv.norm(np.nan_to_num(facets), axis=2), 1.0)
        normed = np.nan_to_num(facets) / lengths[:, :, None]
        everyone = np.arange(len(rows))
        # Each point's first normal's line (any when it has none), then its first normal off that line.
        first = normed[everyone, np.argmax(used, axis=1)]
        on_first = np.abs(fv.dot(normed, first[:, None, :])) > 1 - _THROUGH
        off = used & ~on_first
        two = off.any(axis=1)
        second = normed[everyone, np.argmax(off, axis=1)]
        on_second = np.abs(fv.dot(normed, second[:, None, :])) > 1 - _THROUGH
        plain: NDArray[np.bool_] = ~singular & np.all(
            ~used | on_first | (two[:, None] & on_second), axis=1
        )
        if not plain.any():
            return plain
        n1, n2, pair = first[plain], second[plain], two[plain][:, None]
        ways = np.stack(
            [
                np.where(pair, n1 + n2, n1),
                np.where(pair, n1 - n2, -n1),
                np.where(pair, -n1 + n2, n1),
                np.where(pair, -n1 - n2, -n1),
            ],
            axis=1,
        )  # (points, 4, 3): one direction in each cell
        answers: list[NDArray[np.bool_]] = []
        for w, n, flip, groups in zip(wheres, normals, inverted, grouped, strict=True):
            w, n = w[plain], n[plain]
            dots = fv.matmul(ways, np.swapaxes(np.nan_to_num(n), 1, 2))
            unused = np.isnan(n[:, None, :, 0])
            these = Locals(w, n, flip, None if groups is None else groups[plain])
            on = these.held(dots, unused)
            on = ~on if flip else on
            surface = (w == SURFACE)[:, None]
            answers.append(np.where(surface, on, (w == INSIDE)[:, None]))
        leaf = iter(answers)
        held: NDArray[np.bool_] = np.zeros((int(plain.sum()), 4), dtype=bool)
        for k in kept:
            step = self.part.steps[k]
            here = toward_all(step.node, leaf)
            held = held | here if step.adds else held & ~here
        sides[plain] = np.where(
            held.all(axis=1),
            int(Side.IN),
            np.where(held.any(axis=1), int(Side.ON), int(Side.OUT)),
        )
        return plain

    def _replay(self, models: list[tuple[int, list[Local]]]) -> int:
        normals: list[NDArray[np.float64]] = []
        for _, mine in models:
            for local in mine:
                if local.where == SINGULAR:
                    return int(Side.UNKNOWN)
                normals.extend(local.normals)
        directions = probes(normals)
        held: NDArray[np.bool_] = np.zeros(len(directions), dtype=bool)
        for k, mine in models:
            step = self.part.steps[k]
            here = toward(step.node, iter(mine), directions)
            held = held | here if step.adds else held & ~here
        if held.all():
            return int(Side.IN)
        return int(Side.OUT) if not held.any() else int(Side.ON)


def oracle(spec: PartSpec, placed: Placed) -> Oracle:
    """The spec's own shape, from the definitions' placement."""
    items = {item.id: item for item in spec.items}
    steps: list[Step] = []
    unchecked: list[Unchecked] = []
    making = _Making(items, placed, steps)
    for planned in placed.order:
        item = items[planned.item]
        entry = ORACLE[item.kind]
        steps += entry.steps(item, planned, making)
        why = entry.left_unchecked(item)
        if why is not None and placed.copies[item.id]:
            unchecked.append(Unchecked(item.id, why))
    if not steps:
        raise OracleError("the spec makes nothing")
    return _assemble(steps, unchecked, making.rounded)


def _assemble(
    steps: Sequence[Step],
    unchecked: Sequence[Unchecked] = (),
    rounded: Sequence[Rounded] = (),
) -> Oracle:
    lo = np.array([s.lo for s in steps if s.adds]).min(axis=0)
    hi = np.array([s.hi for s in steps if s.adds]).max(axis=0)
    tree = Tree.build(np.array([s.lo for s in steps]), np.array([s.hi for s in steps]))
    return Oracle(
        tuple(steps), tuple(unchecked), _vec(lo), _vec(hi), tree, tuple(rounded)
    )


# ----------------------------------------------------------------------
# Roundings and chamfers (forge_checks.rounds), and the hollows that follow them
# ----------------------------------------------------------------------
class CannotMakeError(OracleError):
    """The spec's shape can't be made: a rounding none of whose edges are left, or that doesn't fit them (a CAN'T)."""


@dataclass
class _Making:
    """What is made so far, as roundings need it: each body copy's own solid, and a hollowed body's own roundings."""

    items: Mapping[str, Item]
    placed: Placed
    steps: list[Step]
    made: dict[tuple[str, int], Node] = field(default_factory=dict)
    own: dict[tuple[str, int], list[rounds.Made]] = field(default_factory=dict)
    hollowed: set[tuple[str, int]] = field(default_factory=set)
    #: A box-like body's edges a rounding made all along: by their two faces, ("fillet" or "chamfer", size).
    corners: dict[tuple[str, int], dict[frozenset[str], tuple[str, float]]] = field(
        default_factory=dict
    )
    #: Every stretch of an edge rounded exactly, for the checks.
    rounded: list[Rounded] = field(default_factory=list)

    def step(
        self, item: Item, copy: Copy, adds: bool, node: Node, envelope: bool = False
    ) -> Step:
        """A step making one copy of ``item``: ``node`` added (else taken away), in both forms of the part; ``envelope``, in the outer form alone (a region's)."""
        return Step(item.id, copy.index, adds, node, OUTER if envelope else BOTH)

    def hollows(self, shell: Item) -> list[Step]:
        """A shell's steps: its hollow in each copy of its body (:func:`_hollows`)."""
        return _hollows(shell, self)

    def rounding(
        self,
        item: Item,
        named: Mapping[int, tuple[tuple[str, str], ...]] | None,
        fillet: bool,
    ) -> list[Step]:
        """A rounding's or a chamfer's steps (:func:`_rounding`)."""
        return _rounding(item, named, self, fillet)

    def thread(self, item: Item) -> list[Step]:
        """A thread's steps (:func:`_thread`)."""
        return _thread(item, self)


def _rounding(
    item: Item,
    named: Mapping[int, tuple[tuple[str, str], ...]] | None,
    making: _Making,
    fillet: bool,
) -> list[Step]:
    """A rounding (``fillet``) or a chamfer, made on the shape made so far: on each copy of what it rounds."""
    edges = item.get("edges")
    if not isinstance(edges, EdgeSet):
        raise OracleError(f"{item.id}: a rounding names its edges")
    size = _mm(item.get("radius" if fillet else "size"))
    target = making.items[edges.of]
    part = _assemble(making.steps)

    def places(origin: Array, direction: Array, length: float) -> Array:
        return _places(part, origin[None, :], direction[None, :], np.array([length]))[1]

    found: list[Step] = []
    singles: dict[int, list[tuple[rounds.Chain, frozenset[str]]]] = {}
    #: A joint's jobs, by their place in ``jobs``: the box of the copy that stands there.
    near: dict[int, tuple[Vec, Vec]] = {}
    jobs: list[
        tuple[
            int,
            list[rounds.Chain],
            bool,
            list[Node],
            Node | None,
            tuple[str, int] | None,
        ]
    ] = []
    if edges.which == "joint":
        meets = making.items.get(edges.where_meets or "")
        if meets is None:
            raise OracleError(
                f"{item.id}: a joint is where {target.id} meets another item"
            )
        for index, chains, zones, box in _joint_chains(target, meets, making, size):
            if box is not None:
                near[len(jobs)] = box
            jobs.append((index, chains, True, zones, None, None))
    elif ORACLE[target.kind].outline_rounded:
        for copy in making.placed.copies[target.id]:
            whole = making.made[(target.id, copy.index)]
            for chains, fill in _extrusion_chains(target, copy, edges.which):
                jobs.append((copy.index, chains, fill, [], whole, None))
    else:
        for copy in making.placed.copies[target.id]:
            if named is not None and copy.index not in named:
                continue
            pairs = None if named is None else named[copy.index]
            chains, fill, zones, within, single = _edge_chains(
                target, copy, edges.which, pairs, making, size
            )
            singles[copy.index] = single
            key = (target.id, copy.index)
            own = key if named is not None and key not in making.hollowed else None
            jobs.append((copy.index, chains, fill, zones, within, own))
    try:
        results = [
            rounds.make(chains, size, fillet, fill, part.held_all, places, part.around)
            if chains
            else rounds.Made((), (), fill, size, fillet, False)
            for _, chains, fill, _, _, _ in jobs
        ]
        for k, box in near.items():
            results[k] = _by_the_copy(results[k], box, size)
        # The edge set must name an edge somewhere: on one copy at least, or where it may be.
        if not any(
            r.edged or zones
            for r, (*_, zones, _w, _o) in zip(results, jobs, strict=True)
        ):
            raise rounds.CannotMakeError(
                "none of the edges it names is left on the shape the spec makes"
            )
    except rounds.CannotMakeError as why:
        raise CannotMakeError(f"{item.id}: {why}") from None
    for result, (index, _, _, zones, within, own) in zip(results, jobs, strict=True):
        if own is not None:
            making.own.setdefault(own, []).append(result)
        making.rounded += [
            Rounded(item.id, index, edge, a, b, size, fillet, result.fill)
            for _, edge, a, b in result.pieces
        ]
        # A box-like body's edges rounded all along: the corners its faces now have.
        for chain, pair in singles.get(index, []):
            edge = chain.edges[0]
            spans = sorted((a, b) for _, e, a, b in result.pieces if e is edge)
            reach = 0.0
            for a, b in spans:
                if a > reach + 1e-9:
                    break
                reach = max(reach, b)
            if spans and reach >= edge.span - 1e-9:
                making.corners.setdefault((target.id, index), {})[pair] = (
                    item.kind,
                    size,
                )
        found += _rounding_steps(item.id, index, result, zones, within)
    return found


def _rounding_steps(
    item: str, copy: int, result: rounds.Made, more: Sequence[Node], within: Node | None
) -> list[Step]:
    """A rounding's steps: its exact solids outside its zones, in both forms; its zones in one form.

    Taking away, the inner form loses all of what it rounds in a zone (all
    the part must hold there is the rest) and the outer form keeps it all;
    filling, the outer form gains the whole zone.
    """
    zones = [*result.zones, *more]
    pieces = [node for node, *_ in result.pieces]
    found: list[Step] = []
    if pieces:
        node: Node = pieces[0] if len(pieces) == 1 else Union(tuple(pieces))
        if within is not None and not result.fill:
            node = Inter((node, within))
        if zones:
            node = Minus(node, zones[0] if len(zones) == 1 else Union(tuple(zones)))
        found.append(Step(item, copy, result.fill, node, BOTH, True))
    if zones:
        zone: Node = zones[0] if len(zones) == 1 else Union(tuple(zones))
        if result.fill:
            found.append(Step(item, copy, True, zone, OUTER, True))
        else:
            taken = Inter((zone, within)) if within is not None else zone
            found.append(Step(item, copy, False, taken, INNER, True))
    return found


def _hollows(shell: Item, making: _Making) -> list[Step]:
    """A shell's hollow in each copy of its body, following the body's own roundings (shell.md).

    The hollow is every point of the body at least its wall's thickness from
    each closed face: the body less every wall's reach. A face's reach is
    the band its wall's thickness in from it; where one of the body's own
    roundings meets the face, the face ends there, so its band stops at the
    line square to it there, with the reach round that line; and a
    rounding's own face reaches the shell's thickness in from it
    (:func:`~forge_checks.rounds.face_end`,
    :func:`~forge_checks.rounds.rounding_reach`). Where a rounding is only
    bounded (its zones, grown by the walls' thickness), so is the hollow:
    there the inner form loses all of the body, and the outer form keeps it.
    """
    body = making.items[str(shell.get("of"))]
    thickness = _mm(shell.get("thickness"))
    found: list[Step] = []
    for copy in making.placed.copies[body.id]:
        key = (body.id, copy.index)
        hollow = making.placed.hollows[key]
        bands = ORACLE[body.kind].wall_bands(body, copy, making.placed)
        off: dict[str, list[Node]] = {face: [] for face in bands}
        reaches: list[Node] = []
        zones: list[Node] = []
        assert copy.lo is not None and copy.hi is not None
        extent = 4 * float(max(np.array(copy.hi) - np.array(copy.lo))) + 10
        deepest = max(hollow.walls.values())
        for result in making.own.get(key, []):
            zones += [_grown(zone, deepest) for zone in result.zones]
            for _, edge, a, b in result.pieces:
                faces = (_face_of(body, copy, edge, 1), _face_of(body, copy, edge, 2))
                for side, face in ((1, faces[0]), (2, faces[1])):
                    if face not in bands:
                        raise OracleError(
                            f"{shell.id}: a rounding of {body.id} meets its face {face}, which has no wall"
                        )
                    off[face].append(
                        rounds.face_end(
                            edge, a, b, result.size, result.fillet, side, extent
                        )
                    )
                thick = (hollow.walls[faces[0]], hollow.walls[faces[1]])
                near = rounds.rounding_reach(
                    edge, a, b, result.size, result.fillet, thickness, thick
                )
                if near is not None:
                    reaches.append(near)
        walls: list[Node] = [
            Minus(band, _union(off[face])) if off[face] else band
            for face, band in bands.items()
        ]
        reach = _union([*walls, *reaches])
        whole = making.made[key]
        cut: Node = Minus(whole, reach)
        if zones:
            zone = _union(zones)
            found.append(Step(shell.id, copy.index, False, Minus(cut, zone)))
            found.append(
                Step(shell.id, copy.index, False, Inter((whole, zone)), INNER, True)
            )
        else:
            found.append(Step(shell.id, copy.index, False, cut))
        making.made[key] = Inter((whole, reach))
        making.hollowed.add(key)
    return found


def _union(nodes: Sequence[Node]) -> Node:
    return nodes[0] if len(nodes) == 1 else Union(tuple(nodes))


def _grown(zone: Node, by: float) -> Node:
    """A zone grown by ``by``: a ball's radius, or anything else's box."""
    if isinstance(zone, Ball):
        return Ball(zone.centre, zone.r + by)
    lo, hi = box(zone)
    return Prism.box(tuple(x - by for x in lo), tuple(x + by for x in hi))


def _face_of(body: Item, copy: Copy, edge: rounds.Edge, side: int) -> str:
    """Which face of the body is the one on ``side`` of one of its own edges."""
    boundary = edge.b1 if side == 1 else edge.b2
    if isinstance(boundary, rounds.Circle2):
        return "surface"
    n = boundary.normal
    if isinstance(edge, rounds.StraightEdge):
        world = n[0] * np.asarray(edge.u) + n[1] * np.asarray(edge.v)
        k = int(np.argmax(np.abs(world)))
        return ("+" if world[k] > 0 else "-") + "xyz"[k]
    if abs(n[0]) > abs(n[1]):
        return "side"
    up = float(
        fv.matmul(np.asarray(edge.axis), np.asarray(copy.direction, dtype=float))
    )
    return "+end" if n[1] * up > 0 else "-end"


def _edge_chains(
    target: Item,
    copy: Copy,
    which: str,
    pairs: tuple[tuple[str, str], ...] | None,
    making: _Making,
    size: float,
) -> tuple[
    list[rounds.Chain],
    bool,
    list[Node],
    Node | None,
    list[tuple[rounds.Chain, frozenset[str]]],
]:
    """The edges a rounding names on one copy of an item.

    Chains of them; whether it fills them; zones; what it rounds; and a
    box-like body's single edges, each with its two faces.
    """
    kind = target.kind
    entry = ORACLE[kind]
    if entry.taken:
        return (*entry.cut_chains(target, copy, which, making.placed, size), [])
    key = (target.id, copy.index)
    whole = making.made[key]
    # A turned one's, or one's on a turned item's face: found as it stands upright and unturned, then moved (edges.md,
    # "A turned item's edges").
    base, motion = upright(copy)
    up = direction_of(base.direction)
    assert up is not None
    if pairs is None:
        pairs = body_edges(kind, which, up)
    hollow = making.placed.hollows.get(key) if key in making.hollowed else None
    if motion is None:
        chains, single = entry.rim_chains(target, copy, which, pairs, making, whole, hollow)
        return chains, False, [], whole, single
    found, single = entry.rim_chains(target, base, which, pairs, making, moved_node(whole, motion.inverse()), hollow)
    moved = {id(chain): moved_chain(chain, motion) for chain in found}
    return [moved[id(c)] for c in found], False, [], whole, [(moved[id(c)], faces) for c, faces in single]


def _extrusion_chains(
    target: Item, copy: Copy, which: str
) -> list[tuple[list[rounds.Chain], bool]]:
    """An extrusion's edges an edge set names (extrusion.md), as chains made together: the edges round each end and those along its axis at the outline's corners that turn outward; and, filled, those at the corners that turn inward.

    Round an end, an edge for each side of the outline in turn, each arc a
    circle's piece about its own axis; along the axis, a straight edge at
    each corner where two sides meet at an angle. Where both are rounded
    ("all"), the corners turning inward meet the ends' roundings in zones.
    """
    assert copy.axes is not None
    outline = section_of(target)
    sides = sides_in_turn(outline)
    length = _mm(target.get("length"))
    first, second = _axis(copy.axes[0]), _axis(copy.axes[1])
    up = np.asarray(copy.direction, dtype=float)
    frame = _frame(copy.point, first, second)
    sign = float(
        fv.matmul(np.asarray(frame.w), up)
    )  # +1 or -1: the frame's third axis is the way it runs, or back
    outward: list[rounds.Chain] = []
    inward: list[rounds.Chain] = []
    if which in ("top", "all"):
        outward.append(_profile_chain(frame, sides, sign * length, sign))
    if which in ("bottom", "all"):
        outward.append(_profile_chain(frame, sides, 0.0, -sign))
    if which in ("vertical", "all"):
        su, sv = (first, second) if sign > 0 else (second, first)
        axes = (
            np.array([float(fv.matmul(su, first)), float(fv.matmul(su, second))]),
            np.array([float(fv.matmul(sv, first)), float(fv.matmul(sv, second))]),
        )
        for k, side in enumerate(sides):
            after = sides[(k + 1) % len(sides)]
            t_in, t_out = _side_tangent(side, True), _side_tangent(after, False)
            turn = t_in[0] * t_out[1] - t_in[1] * t_out[0]
            if t_in[0] * t_out[0] + t_in[1] * t_out[1] > 1.0 - 1e-9:
                continue  # they run on smoothly: no edge there
            convex = turn > 0  # it turns left, round the material
            corner = side.b
            b1 = _outline_boundary(
                outline, _side_piece(side), corner, corner, material=convex, axes=axes
            )
            b2 = _outline_boundary(
                outline, _side_piece(after), corner, corner, material=convex, axes=axes
            )
            origin = np.asarray(copy.point) + corner[0] * first + corner[1] * second
            edge = rounds.StraightEdge(
                _vec(origin), _vec(up), length, _vec(su), _vec(sv), b1, b2
            )
            clean = convex or which != "all"
            (outward if convex else inward).append(
                rounds.Chain((edge,), clean=(clean, clean))
            )
    return [
        (chains, fill) for chains, fill in ((outward, False), (inward, True)) if chains
    ]


def _side_piece(side: OutlineSide) -> OutlineSegment | OutlineArc:
    return side.arc if side.arc is not None else OutlineSegment(side.a, side.b)


def _side_tangent(side: OutlineSide, at_end: bool) -> tuple[float, float]:
    """The way a side of an outline runs (from ``a`` to ``b``), at its end or its start."""
    if side.arc is None:
        return _unit2(side.b[0] - side.a[0], side.b[1] - side.a[1])
    point = side.b if at_end else side.a
    out = _unit2(point[0] - side.arc.centre[0], point[1] - side.arc.centre[1])
    forward = fs.dist(side.a, side.arc.at(side.arc.start)) <= fs.dist(
        side.a, side.arc.at(side.arc.start + side.arc.sweep)
    )
    return (-out[1], out[0]) if forward else (out[1], -out[0])


def _profile_chain(
    frame: Frame, sides: Sequence[OutlineSide], z: float, face_sign: float
) -> rounds.Chain:
    """The edge all round an extrusion's end: its outline's sides in turn (anticlockwise) at height ``z`` along the frame's third axis, the end facing ``face_sign`` times it, the material inside the outline and behind the end.

    A straight side's edge is a straight edge; an arc's, a piece of a circle
    about the arc's own axis, turning the way the outline runs (an arc the
    outline runs clockwise round turns about the axis the other way, its
    material outside its circle).
    """
    u, v, w = (np.asarray(x, dtype=float) for x in (frame.u, frame.v, frame.w))
    n_face = face_sign * w
    edges: list[rounds.Edge] = []
    for side in sides:
        (x0, y0), (x1, y1) = side.a, side.b
        if side.arc is None:
            length = fs.hypot(x1 - x0, y1 - y0)
            along = ((x1 - x0) * u + (y1 - y0) * v) / length
            out = ((y1 - y0) * u - (x1 - x0) * v) / length
            sv = np.asarray(np.cross(along, n_face), dtype=np.float64)
            origin = frame.world(np.array([x0]), np.array([y0]), np.array([z]))[0]
            edges.append(rounds.StraightEdge(_vec(origin), _vec(along), length, _vec(n_face), _vec(sv),
                                             rounds.Line2((1.0, 0.0)), rounds.Line2((float(fv.matmul(out, n_face)), float(fv.matmul(out, sv))))))  # fmt: skip
            continue
        arc = side.arc
        centre = frame.world(
            np.array([arc.centre[0]]), np.array([arc.centre[1]]), np.array([z])
        )[0]
        forward = fs.dist(side.a, arc.at(arc.start)) <= fs.dist(
            side.a, arc.at(arc.start + arc.sweep)
        )
        if forward:  # anticlockwise: its material inside its circle
            edges.append(rounds.RoundEdge(_vec(centre), frame.w, frame.u, frame.v, arc.radius, 0.0,
                                          rounds.Line2((0.0, face_sign)), rounds.Line2((1.0, 0.0)), arc.start, arc.sweep))  # fmt: skip
        else:  # clockwise: about the axis the other way (v and the axis turned back), its material outside
            begin = arc.start + arc.sweep
            edges.append(rounds.RoundEdge(_vec(centre), _vec(-w), frame.u, _vec(-v), arc.radius, 0.0,
                                          rounds.Line2((0.0, -face_sign)), rounds.Line2((-1.0, 0.0)), -begin, arc.sweep))  # fmt: skip
    n = len(sides)
    smooth = tuple(
        float(
            fv.dot(
                _side_tangent(sides[i], True), _side_tangent(sides[(i + 1) % n], False)
            )
        )
        > 1.0 - 1e-9
        for i in range(n)
    )
    return rounds.Chain(tuple(edges), closed=True, smooth=smooth)


# --- Joints ----------------------------------------------------------------
def _joint_chains(
    target: Item, meets: Item, making: _Making, size: float
) -> Iterator[tuple[int, list[rounds.Chain], list[Node], tuple[Vec, Vec] | None]]:
    """Where one item stands on another: round each standing copy's foot, and under where it hangs over the face's edge; with the copy's box, beyond which none of it is (:func:`_by_the_copy`)."""
    placed = making.placed
    standing = None
    for s, h in ((target, meets), (meets, target)):
        if any(
            c.host is not None and c.host[0] == h.id
            for c in placed.copies.get(s.id, ())
        ):
            standing, host = s, h
            break
    if standing is None:
        raise OracleError(
            f"{target.id} and {meets.id} don't meet: a joint is where one stands on the other"
        )
    for copy in placed.copies[standing.id]:
        if copy.host is None or copy.host[0] != host.id:
            continue
        face = placed.face(copy.host)
        if isinstance(face, RoundSide):
            yield copy.index, [], [_joint_band(standing, copy, face, size)], None
            continue
        box = None if copy.lo is None or copy.hi is None else (copy.lo, copy.hi)
        corners = making.corners.get((standing.id, copy.index), {})
        base, motion = upright(copy)
        if motion is None:
            foot = ORACLE[standing.kind].footprint_chain(standing, copy, corners)
        else:  # turned, or on a turned item's face: found as it stands upright and unturned, then moved (edges.md)
            lo, hi = csg_box(moved_node(making.made[(standing.id, copy.index)], motion.inverse()))
            foot = moved_chain(ORACLE[standing.kind].footprint_chain(standing, replace(base, lo=lo, hi=hi), corners),
                               motion)  # fmt: skip
        yield copy.index, [foot, *_face_chains(face, copy)], [], box


def _by_the_copy(result: rounds.Made, box: tuple[Vec, Vec], size: float) -> rounds.Made:
    """A joint's rounding only by the copy that stands there: the face's edge is a corner under whatever hangs over it, and only this copy's overhang is its (generated part 874: a boss's joint bevelled where a block hung over the face's far edge).

    A stretch is kept where its ends or its middle lie within the copy's box,
    grown by twice the rounding's size.
    """
    reach = 2 * size + 1e-6
    lo, hi = np.asarray(box[0]) - reach, np.asarray(box[1]) + reach

    def by(piece: tuple[Node, rounds.Edge, float, float]) -> bool:
        _, edge, a, b = piece
        points = [edge.at(s)[0] for s in (a, (a + b) / 2, b)]
        return any(bool(np.all((p >= lo) & (p <= hi))) for p in points)

    return replace(result, pieces=tuple(p for p in result.pieces if by(p)))


def _face_chains(face: FlatFace, copy: Copy) -> list[rounds.Chain]:
    """Round the edge of the face an item stands on: under where it hangs over, the corner below its underside."""
    g = np.asarray(copy.direction, dtype=float)
    a1, a2 = _axis(face.axes[0]), _axis(face.axes[1])
    outline = face.outline
    middle = np.asarray(face.centre, dtype=float)
    middle = (
        middle
        + (outline.centre[0] - float(fv.matmul(middle, a1))) * a1
        + (outline.centre[1] - float(fv.matmul(middle, a2))) * a2
    )
    at = _frame(middle, a1, a2)
    sign = float(fv.matmul(np.asarray(at.w), g))
    # The air is below the face (behind it) and outside the face's edge; inside a ring's hole, inside it.
    if outline.shape == "rect":
        shape: Shape2D = RoundRect(outline.half[0], outline.half[1], outline.corners)
        return [_outline_chain(at, shape.pieces(), 0.0, sign, False, False)]
    found = [_outline_chain(at, Disc(outline.radius).pieces(), 0.0, sign, False, False)]
    if outline.shape == "ring":
        found.append(
            _outline_chain(at, Disc(outline.inner).pieces(), 0.0, sign, True, False)
        )
    return found


def _joint_band(item: Item, copy: Copy, face: RoundSide, size: float) -> Node:
    """Where an item stands round a side: its foot follows no circle; the zone where the rounding must be."""
    reach = 4 * size
    assert copy.lo is not None and copy.hi is not None
    lo = np.asarray(copy.lo) - reach
    hi = np.asarray(copy.hi) + reach
    axis = Frame.along(face.start, face.frame.n)
    near = Prism.box(_vec(lo), _vec(hi))
    band = Inter(
        (
            Round(axis, face.radius + reach),
            Complement(Round(axis, max(face.radius - reach, 1e-9))),
        )
    )
    return Inter((near, band))


# ----------------------------------------------------------------------
# Threads
# ----------------------------------------------------------------------
#: ISO 261's coarse pitches (mm), the judge's own copy: a plain metric size's pitch (thread.md).
COARSE_PITCH: Mapping[str, float] = {
    "M2": 0.4, "M2.5": 0.45, "M3": 0.5, "M4": 0.7, "M5": 0.8, "M6": 1.0, "M8": 1.25,
    "M10": 1.5, "M12": 1.75, "M16": 2.0, "M20": 2.5, "M24": 3.0,
}  # fmt: skip


def thread_pitch(designation: str) -> float:
    """A metric thread's pitch: the one it names (M8x1), or its size's coarse pitch (M8: 1.25 mm).

    >>> thread_pitch("M8"), thread_pitch("M8x1"), thread_pitch("M2.5")
    (1.25, 1.0, 0.45)
    """
    size, _, named = designation.strip().partition("x")
    if named:
        return float(named)
    if size not in COARSE_PITCH:
        raise CannotMakeError(
            f"no coarse pitch is known for an {size}: name its pitch ({size}x...)"
        )
    return COARSE_PITCH[size]


def _thread(item: Item, making: _Making) -> list[Step]:
    """A thread on each copy of what it threads: its zone, between its minor and major cylinders over its length (thread.md).

    The thread's major diameter is the rod's, and its depth the basic
    profile's, 5/8 of the sharp triangle's height. Where its helix starts
    round the axis is not the spec's to say, so the oracle bounds it: the
    part holds the core within the minor diameter there, and at most the rod
    (a step taking the rod's material between them away from the inner form
    alone).
    """
    designation = item.get("designation")
    if not isinstance(designation, Text):
        raise OracleError(f"{item.id}: a thread is named by its designation")
    target = making.items[str(item.get("of"))]
    if not ORACLE[target.kind].threadable:
        raise OracleError(f"{item.id}: a thread goes on a cylinder or a boss")
    pitch = thread_pitch(designation.text)
    radius = _mm(target.get("diameter")) / 2
    depth = 5 / 8 * math.sqrt(3) / 2 * pitch
    if depth >= radius:
        raise CannotMakeError(
            f"{item.id}: an {designation.text} thread is deeper than {target.id}'s radius"
        )
    whole = _mm(target.get(ORACLE[target.kind].rod_length))
    length = _mm(item.get("length")) if item.get("length") is not None else whole
    if length > whole + 1e-9:
        raise CannotMakeError(f"{item.id}: the thread is longer than {target.id}")
    found = []
    for copy in making.placed.copies[target.id]:
        frame = Frame.along(copy.point, np.asarray(copy.direction, dtype=float))
        start = whole - length
        ring = Minus(
            Prism(frame, Disc(radius + depth), start, whole + depth),
            Prism(frame, Disc(radius - depth), start - depth, whole + 2 * depth),
        )
        node = Inter((ring, making.made[(target.id, copy.index)]))
        found.append(Step(item.id, copy.index, False, node, INNER, True))
    return found


# ----------------------------------------------------------------------
# The part's surfaces: witnesses and coverage
# ----------------------------------------------------------------------
#: How far either side of a surface a point is looked at to tell whether the surface is the part's (mm).
OFF = 1e-6


@dataclass(frozen=True)
class Surface:
    """One smooth piece of one solid, and every step the solid is in (one solid can be in several: a body a rounding is kept within)."""

    steps: tuple[int, ...]
    leaf: Solid
    patch: Patch


@dataclass(frozen=True)
class OracleCoverage:
    """Points on the part's surface, standing for all of it.

    Every point of the part's surface is within ``radius`` of one of
    ``points``, except within ``finest`` of a curve where two of its solids'
    surfaces meet: there the pieces are split down to ``finest`` and every
    piece found on the part's surface is kept. In each of ``finer``'s boxes,
    the same at the box's radius, and its finest as much finer
    (docs/V2-stage4.md, 13.10). ``normals`` face out of the part;
    ``surface`` says which of :meth:`Oracle.surfaces` each is on.

    Each point is on its solid's surface, and the part's surface is within
    :data:`OFF` of it along its normal: the part is inside :data:`OFF`
    behind it and outside :data:`OFF` in front. Where two surfaces run
    within that of each other (a face beside the rounding that meets it
    tangentially, which takes away a sliver thinner than that), a point on
    one may be off the part's surface by up to :data:`OFF`.
    """

    points: Array
    normals: Array
    surface: NDArray[np.int64]
    radius: float
    finest: float
    finer: tuple[tuple[Box, float], ...] = ()


@dataclass(frozen=True)
class ExpectedTopology:
    """What the part should be made of: its solids, its sealed voids (None: not counted, with the reason)."""

    solids: int
    voids: int | None
    genus: tuple[int, ...] | None
    unchecked: tuple[str, ...]


def _surfaces(part: Oracle) -> tuple[Surface, ...]:
    """Each solid's smooth pieces once, whatever number of steps it is in.

    A bounded solid's pieces are its own; an endless one's are cut to the
    box of its step, so it is the same surface again only in a step with the
    same box.
    """
    held: dict[tuple[object, ...], tuple[Solid, Vec, Vec, list[int]]] = {}
    for k, step in enumerate(part.steps):
        for leaf in leaves(step.node):
            bounded = all(math.isfinite(x) for x in (*leaf.lo, *leaf.hi))
            key: tuple[object, ...] = (
                (id(leaf),) if bounded else (id(leaf), step.lo, step.hi)
            )
            if key not in held:
                held[key] = (leaf, step.lo, step.hi, [])
            if k not in held[key][3]:
                held[key][3].append(k)
    return tuple(
        Surface(tuple(steps), leaf, patch)
        for leaf, lo, hi, steps in held.values()
        for patch in patches(leaf, lo, hi)
        if patch.size[0] > 0 and patch.size[1] > 0
    )


def _sides(
    part: Oracle, points: Array, normals: Array
) -> tuple[NDArray[np.bool_], Array]:
    """Whether the part's surface is at each point, facing along or against the normal, and its outward normal."""
    plus = part.classify(points + OFF * normals)
    minus = part.classify(points - OFF * normals)
    out_along = (plus == Side.OUT) & (minus == Side.IN)
    out_back = (plus == Side.IN) & (minus == Side.OUT)
    return out_along | out_back, np.where(out_back[:, None], -normals, normals)


#: A way this near square to a facet's normal runs along the facet (cosine).
_GRAZE = 1e-12
#: How far a way along a facet is turned to either side of it to see what is there (radians, about).
_NUDGE = 1e-6

#: The solids whose signed distance is convex (convex solids): a complement's is concave.
_CONVEX = (Prism, Frustum, Ball, Round, Halfspace)


def _apart(
    leaf: Solid,
    centres: Array,
    corners: Array,
    normals: Array,
    reach: Array,
    bend: Array,
) -> NDArray[np.bool_]:
    """Whether a solid's surface surely misses each cell (its signed distance keeps one sign over it).

    A convex solid's signed distance is convex. Outside it, over a flat cell
    it is at least its value at the cell's middle less its slope along the
    cell times the cell's reach (a surface the cell runs alongside, as a
    face beside a rounding that meets it tangentially, is missed this way,
    where its distance alone is too small to say). Inside it, its greatest
    over the cell is at one of the cell's corners. A curved cell's points are
    within ``bend[:, 0]`` of the flat cell through its middle and
    ``bend[:, 1]`` of the flat pieces between its corners, and a signed
    distance changes no faster than distance: each bound gives its bend
    away. For a complement, the same of the solid it is the complement of.
    """
    solid = leaf.of if isinstance(leaf, Complement) else leaf
    if isinstance(solid, Revolved):
        return _apart_revolved(solid, centres, normals, reach, bend[:, 0])
    if not isinstance(solid, _CONVEX):
        return np.zeros(len(centres), dtype=bool)
    g = solid.signed_distance(centres)
    _, slope = solid.nearest(centres)
    along = slope - fv.dot(slope, normals)[:, None] * normals
    flat, chord = bend[:, 0], bend[:, 1]
    outside = (g > ON) & (g - fv.norm(along, axis=1) * reach - flat > ON)
    deepest = solid.signed_distance(corners.reshape(-1, 3)).reshape(-1, 4).max(axis=1)
    inside = (deepest + chord < -ON) & (g + chord < -ON)
    return np.asarray(outside | inside)


def _apart_revolved(
    solid: Revolved, centres: Array, normals: Array, reach: Array, bend: Array
) -> NDArray[np.bool_]:
    """Whether a solid of revolution's surface surely misses each cell, from its signed distance's convexity in its own half-plane.

    Its signed distance is its outline's, f(r, z), at a point's distance r
    from its axis and height z along it, and f is convex: so over a cell,
    f(r, z) is at least its value at the middle's (r0, z0) plus its
    gradient (g_r, g_z) there times the step (r - r0, z - z0). A step δ
    from the middle changes z by w·δ and r by at least e·δ (e the way out
    from the axis at the middle; r is convex in the point) and at most e·δ
    plus |δ|²/2(r0 - |δ|): to first order the solid's own 3D gradient
    g_r e + g_z w, and where g_r < 0 that much more times -g_r. Outside it,
    then: the middle's value, less the gradient along the cell times its
    reach, less its bend from the flat cell through its middle (as a
    convex solid's), less -g_r times
    reach²/2(r0 - reach). Inside it: f is at its most over the rectangle
    of (r, z) the cell's points may have at one of its corners, r within
    the reach of r0 (and no less than 0), z within the reach times how far
    the axis runs along the cell, and that bend, of z0.
    """
    rho, z, ca, cb = solid._polar(centres)
    g = solid.meridian.sd(rho, z)
    _, _, _, g_r, g_z = solid.meridian.nearest2d(rho, z)
    out = solid.frame.turn(ca, cb, np.zeros(len(ca)))
    w = np.asarray(solid.frame.w, dtype=np.float64)
    gradient = g_r[:, None] * out + g_z[:, None] * w
    along = gradient - fv.dot(gradient, normals)[:, None] * normals
    curl = np.zeros(len(rho))
    turning = g_r < 0
    far = rho > reach
    curl[turning & far] = (reach * reach / (2 * (rho - reach)))[turning & far]
    curl[turning & ~far] = np.inf
    # g_r times curl: nothing where g_r >= 0, minus -g_r times it where it is less.
    outside = (g > ON) & (g - fv.norm(along, axis=1) * reach - bend + g_r * curl > ON)
    up = w[None, :] - (fv.matmul(normals, w))[:, None] * normals
    rise = fv.norm(up, axis=1) * reach + bend
    r_lo, r_hi = np.maximum(rho - reach, 0.0), rho + reach
    deepest = np.max(
        [solid.meridian.sd(r, z + dz) for r in (r_lo, r_hi) for dz in (-rise, rise)],
        axis=0,
    )
    inside = (deepest < -ON) & (g < -ON)
    return np.asarray(outside | inside)


def _near_other(part: Oracle, centres: Array, corners: Array, normals: Array, reach: Array,
                owners: NDArray[np.int64], bend: Array) -> NDArray[np.bool_]:  # fmt: skip
    """Whether another solid's surface comes within ``reach`` of each centre, other than lying on it all over the cell.

    ``corners`` are each cell's four corners (n, 4, 3); ``owners`` the
    ``id`` of the solid each cell is on. A surface on which the centre and
    all four corners lie, facing the same way or the other, lies on the whole
    cell: it doesn't divide it. A cell whose ``bend`` (how far it strays from
    flat, two ways: :func:`_bend`; NaN if not known) is known is also clear
    of a surface the solid's convexity shows it misses (:func:`_apart`).
    """
    near = np.zeros(len(centres), dtype=bool)
    rows_all, steps_all = [], []
    for rows, steps in part._tree.within(centres, reach):
        rows_all.append(rows)
        steps_all.append(steps)
    if not rows_all:
        return near
    rows_of, step_of = np.concatenate(rows_all), np.concatenate(steps_all)
    by_leaf: dict[int, tuple[Solid, NDArray[np.bool_]]] = {}
    for k in np.unique(step_of):
        by_step = np.zeros(len(centres), dtype=bool)
        by_step[rows_of[step_of == k]] = True
        for leaf in leaves(part.steps[int(k)].node):
            if id(leaf) in by_leaf:
                by_leaf[id(leaf)][1][:] |= by_step
            else:
                by_leaf[id(leaf)] = (leaf, by_step.copy())
    for key, (leaf, rows_near) in by_leaf.items():
        r = np.flatnonzero(rows_near & (owners != key))
        if not len(r):
            continue
        d = leaf.signed_distance(centres[r])
        close = np.abs(d) <= reach[r]
        if not close.any():
            continue
        r, d = r[close], d[close]
        known = np.isfinite(bend[r]).all(axis=1)
        if known.any():
            clear = np.zeros(len(r), dtype=bool)
            q = r[known]
            clear[known] = _apart(
                leaf, centres[q], corners[q], normals[q], reach[q], bend[q]
            )
            r, d = r[~clear], d[~clear]
            if not len(r):
                continue
        on_it = np.abs(d) <= ON
        if on_it.any():
            c = corners[r].reshape(-1, 3)
            flat = np.all(np.abs(leaf.signed_distance(c).reshape(-1, 4)) <= ON, axis=1)
            _, n = leaf.nearest(centres[r])
            parallel = np.abs(fv.dot(n, normals[r])) >= 1 - 1e-9
            on_it &= flat & parallel
        near[r[~on_it]] = True
    return near


def _bend(patch: Patch, size_u: Array, size_v: Array) -> Array:
    """How far each cell of a patch strays from flat, (n, 2): from the flat cell through its middle, and from the flat pieces between its corners (NaN where that isn't bounded here).

    A cylinder's cell is an arc of length ``size_u`` swept along its axis.
    The arc's points are within r(1 - cos(a/2)) <= size_u²/8r of the chord
    between its ends, and of the tangent at its middle (a its angle), and
    project onto that tangent within half the arc's length of the middle:
    so the cell is within that of the rectangle of its corners, and of the
    flat cell through its middle. A cone's band's cell is straight along
    its slant (``size_u``) and an arc round its axis (``size_v``, measured
    at its largest radius R): at a radius r its arc turns through size_v/R
    and strays r(1 - cos(a/2)) <= size_v²/8R from its chord and its
    tangent; the band is ruled by its straight lines, which lie in the
    tangent plane along them and, two by two, in a plane (they meet at the
    apex, or run side by side): so the cell is within that of the flat cell
    through its middle and of the flat piece between its corners. A flat
    ring's cell lies in the flat cell through its middle, and its arcs
    reach that far past its corners' piece, in its plane. A torus's cell,
    ``size_u`` round its axis (measured at its outer equator, R + r) and
    ``size_v`` round its tube (r): in those lengths the surface's second
    derivatives are at most 1/(R + r) round the axis, 1/(R + r) across and
    1/r round the tube, so from its middle's tangent plane (Taylor's
    remainder) and from the two flat pieces between its corners (the
    bilinear piece's error, and its twist from them) it strays no more than
    size_u²/8(R + r) + size_u·size_v/4(R + r) + size_v²/8r; a ball's
    cell (its polar arc and its arc round the axis at the equator, each
    second derivative at most 1/r), (size_u + size_v)²/8r. Other curved
    pieces aren't bounded here.
    """
    piece = patch.of if isinstance(patch, Flipped) else patch
    if isinstance(piece, FlatPatch):
        return np.zeros((len(size_u), 2))
    if isinstance(piece, RoundPatch):
        sag = np.asarray(size_u * size_u / (8 * piece.r))
        return np.stack([sag, sag], axis=1)
    if isinstance(piece, ConePatch):
        sag = np.asarray(size_v * size_v / (8 * max(piece.r0, piece.r1)))
        flat = np.zeros(len(sag)) if piece.t0 == piece.t1 else sag
        return np.stack([flat, sag], axis=1)
    if isinstance(piece, TorusPatch) and piece.big >= 0:
        outer = piece.big + piece.r
        bow = np.asarray(
            size_u * size_u / (8 * outer)
            + size_u * size_v / (4 * outer)
            + size_v * size_v / (8 * piece.r)
        )
        return np.stack([bow, bow], axis=1)
    if isinstance(piece, SpherePatch):
        bow = np.asarray(fv.sq(size_u + size_v) / (8 * piece.r))
        return np.stack([bow, bow], axis=1)
    return np.full((len(size_u), 2), np.nan)


def _coverage(part: Oracle, resolution: Resolution, finest: float) -> OracleCoverage:
    """Every piece of every surface, split into cells until each is shown on the part's surface, off it, or as small as ``finest``.

    A cell is split until it is no wider than the radius anywhere it may
    reach, and its finest is as much finer as that radius is
    (docs/V2-stage4.md, 13.10). Each round settles the cells of every
    surface together.
    """
    radius = resolution.radius
    if not (radius > 0 and 0 < finest <= radius):
        raise ValueError("coverage needs 0 < finest <= radius")
    if finest * resolution.finest / radius < 8 * OFF:
        raise ValueError(f"coverage can't split cells finer than {8 * OFF} mm")
    surfaces = part.surfaces()
    if not surfaces:
        return OracleCoverage(
            np.zeros((0, 3)),
            np.zeros((0, 3)),
            np.zeros(0, dtype=np.int64),
            radius,
            finest,
            resolution.finer,
        )
    owner_of = np.array([id(s.leaf) for s in surfaces], dtype=np.int64)
    starts: list[_Cells] = []
    for index, surface in enumerate(surfaces):
        nu = max(1, math.ceil(surface.patch.size[0] / radius))
        nv = max(1, math.ceil(surface.patch.size[1] / radius))
        du, dv = surface.patch.size[0] / nu, surface.patch.size[1] / nv
        grid_u, grid_v = np.meshgrid(
            (np.arange(nu) + 0.5) * du, (np.arange(nv) + 0.5) * dv, indexing="ij"
        )
        n = nu * nv
        starts.append(
            (
                np.full(n, index, dtype=np.int64),
                np.asarray(grid_u.ravel(), dtype=np.float64),
                np.asarray(grid_v.ravel(), dtype=np.float64),
                np.full(n, du),
                np.full(n, dv),
            )
        )
    kept_points: list[Array] = []
    kept_normals: list[Array] = []
    kept_surface: list[NDArray[np.int64]] = []
    cells: Iterator[_Cells] = iter([_joined(starts)])
    while True:
        # A share of the round's cells at a time, in order of their surface: each
        # cell is settled on its own, so the cells kept and split, and their order,
        # are the same as all at once; and the cells split are kept as they are,
        # their quarters made a share at a time in the next round.
        split_parts: list[_Cells] = []
        for which, u, v, size_u, size_v in cells:
            for first in range(0, len(u), CELLS_AT_ONCE):
                share = slice(first, first + CELLS_AT_ONCE)
                kept, split = _settle_cells(
                    part, surfaces, owner_of, resolution, finest,
                    which[share], u[share], v[share], size_u[share], size_v[share],
                )  # fmt: skip
                kept_points.append(kept[0])
                kept_normals.append(kept[1])
                kept_surface.append(kept[2])
                split_parts.append(split)
        split_cells = _joined(split_parts)
        del split_parts
        if not len(split_cells[0]):
            break
        cells = _quarters(split_cells)
    return OracleCoverage(
        np.concatenate(kept_points) if kept_points else np.zeros((0, 3)),
        np.concatenate(kept_normals) if kept_normals else np.zeros((0, 3)),
        np.concatenate(kept_surface) if kept_surface else np.zeros(0, dtype=np.int64),
        radius,
        finest,
        resolution.finer,
    )


#: Cells a round of :func:`_coverage` settles at a time: each holds its corners and its surface's side
#: either way while it is settled, so millions at once (a part's letters at a fine radius) would hold gigabytes.
CELLS_AT_ONCE = 200_000

#: Cells of :func:`_coverage`: each one's surface, middle (u, v) and size (u, v), in order of their surface.
_Cells = tuple[NDArray[np.int64], Array, Array, Array, Array]


def _joined(parts: Sequence[_Cells]) -> _Cells:
    """Lists of cells as one, in order."""
    return (
        np.concatenate([p[0] for p in parts]),
        np.concatenate([p[1] for p in parts]),
        np.concatenate([p[2] for p in parts]),
        np.concatenate([p[3] for p in parts]),
        np.concatenate([p[4] for p in parts]),
    )


def _quarters(cells: _Cells) -> Iterator[_Cells]:
    """The quarters of cells (in order of their surface), in order of their surface: of each surface's, every one's first quarter, then every one's second, and so on; a surface and a quarter at a time.

    The order the round would have all its quarters in, sorted by their
    surface, without ever holding them all.
    """
    which, u, v, size_u, size_v = cells
    half_u, half_v = size_u / 2, size_v / 2
    for _, start, end in _groups(which):
        rows = slice(start, end)
        for sign_u, sign_v in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            yield (
                which[rows],
                u[rows] + sign_u * half_u[rows] / 2,
                v[rows] + sign_v * half_v[rows] / 2,
                half_u[rows],
                half_v[rows],
            )


def _settle_cells(
    part: Oracle,
    surfaces: Sequence[Surface],
    owner_of: NDArray[np.int64],
    resolution: Resolution,
    finest: float,
    which: NDArray[np.int64],
    u: Array,
    v: Array,
    size_u: Array,
    size_v: Array,
) -> tuple[tuple[Array, Array, NDArray[np.int64]], tuple[NDArray[np.int64], Array, Array, Array, Array]]:  # fmt: skip
    """One share of a round of :func:`_coverage`, its cells in order of their surface: the points kept (their points, outward normals and surfaces), and the cells to split (their surfaces, middles and sizes, not yet split)."""
    reach: Array = fv.hypot(size_u, size_v) / 2
    where: NDArray[np.int8] = np.empty(len(u), dtype=np.int8)
    for index, start, end in _groups(which):
        where[start:end] = surfaces[index].patch.inside(
            u[start:end], v[start:end], reach[start:end]
        )
    on_patch = where >= 0
    which, u, v, size_u, size_v = (
        which[on_patch],
        u[on_patch],
        v[on_patch],
        size_u[on_patch],
        size_v[on_patch],
    )
    reach, where = reach[on_patch], where[on_patch]
    if not len(u):
        nothing = np.zeros((0, 3))
        return (nothing, nothing, which), (which, u, v, size_u, size_v)
    points = np.empty((len(u), 3))
    normals = np.empty((len(u), 3))
    valid = np.empty(len(u), dtype=bool)
    corners = np.empty((len(u), 4, 3))
    bend = np.empty((len(u), 2))
    for index, start, end in _groups(which):
        patch, cell = surfaces[index].patch, slice(start, end)
        points[cell], normals[cell], valid[cell] = patch.at(u[cell], v[cell])
        half_u, half_v = size_u[cell] / 2, size_v[cell] / 2
        corner_u = np.stack(
            [
                u[cell] - half_u,
                u[cell] + half_u,
                u[cell] + half_u,
                u[cell] - half_u,
            ],
            axis=1,
        )
        corner_v = np.stack(
            [
                v[cell] - half_v,
                v[cell] - half_v,
                v[cell] + half_v,
                v[cell] + half_v,
            ],
            axis=1,
        )
        corners[cell] = patch.at(corner_u.ravel(), corner_v.ravel())[0].reshape(
            -1, 4, 3
        )
        bend[cell] = _bend(patch, size_u[cell], size_v[cell])
    # A cell as small as it may be is kept or not, whatever is near it; a
    # cell partly off its patch, or wider than the radius anywhere it may
    # reach (a finer box's), is split, whatever is near it.
    wide = np.maximum(size_u, size_v)
    local = resolution.at(points, reach)
    # Exactly ``finest`` where the radius there is the radius everywhere.
    small = wide <= finest * (local / resolution.radius)
    fits = wide <= local * (1 + 1e-9)
    asked = np.flatnonzero((where == 1) & fits & ~small)
    near = np.zeros(len(u), dtype=bool)
    near[asked] = _near_other(
        part,
        points[asked],
        corners[asked],
        normals[asked],
        reach[asked] + OFF,
        owner_of[which[asked]],
        bend[asked],
    )
    decided = (where == 1) & fits & ~near
    # Only the cells kept if the surface is there are asked whether it is.
    ending = np.flatnonzero(valid & (decided | small))
    on, outward = _sides(part, points[ending], normals[ending])
    keep = ending[on]
    split = ~decided & ~small
    return (points[keep], outward[on], which[keep]), (
        which[split],
        u[split],
        v[split],
        size_u[split],
        size_v[split],
    )


def _witness(part: Oracle, points: Array, radius: float | Array) -> NDArray[np.bool_]:
    """Search for a point where the part's surface may be within ``radius`` of each point.

    First each nearby surface piece's own nearest point (exact for every
    piece); then, for the points none of those serves, near where two pieces
    meet, a point on both, found by projecting onto each in turn; then near
    where three meet, the corner on all three (an edge into a corner runs on
    one side of it only, and the point on two pieces found beside a point
    may be on the other); last, beside a nearest point where pieces touch,
    tangent, the first point along the piece the part's first-order shape
    tells them apart at (:func:`_cusps`). A point
    found counts only if the part's surface may be there: it is ON (settled
    exactly), or it is where the spec lets the surface be anywhere, between
    the part's two forms (inside all it may hold, and on or outside what it
    must; or on what it may hold and outside what it must) as face
    accounting reads them. Each round's candidates are classified together.
    A point whose two forms' bounds are both beyond ``radius`` has none to
    find (every such place is on a surface of one form or the other, and a
    bound is at most the distance to it): it isn't searched.
    """
    if points.ndim != 2 or points.shape[1] != 3 or not np.all(np.isfinite(points)):
        raise ValueError("points are finite, (n, 3)")
    reach = np.broadcast_to(np.asarray(radius, dtype=float), (len(points),)).copy()
    if np.any(~(reach >= 0)):
        raise ValueError("a witness radius is 0 or more")
    surfaces = part.surfaces()
    by_step: dict[int, list[int]] = {}
    for n, surface in enumerate(surfaces):
        for k in surface.steps:
            by_step.setdefault(k, []).append(n)
    # A box round each patch where it is cheap to know (else all space): one beyond twice the reach can't serve.
    boxes = np.array([
        [*b[0], *b[1]] if (b := s.patch.box()) is not None else [-np.inf] * 3 + [np.inf] * 3
        for s in surfaces
    ], dtype=float).reshape(-1, 6)  # fmt: skip
    found = np.zeros(len(points), dtype=bool)
    if not len(points):
        return found
    # A point where the surface may be is its own witness (a built point on an edge of the spec's, as built).
    found[:] = _may_be_surface(part, points)
    hopeful = np.flatnonzero(
        ~found
        & (
            (np.abs(_fold(part, points, OUTER, reach, float(reach.max()))) <= reach)
            | (np.abs(_fold(part, points, INNER, reach, float(reach.max()))) <= reach)
        )
    )
    rows_all, steps_all = [], []
    for rows, steps in part._tree.within(points[hopeful], reach[hopeful]):
        rows_all.append(hopeful[rows])
        steps_all.append(steps)
    if not rows_all:
        return found
    rows_of, step_of = np.concatenate(rows_all), np.concatenate(steps_all)
    order = np.argsort(rows_of, kind="stable")
    rows_of, step_of = rows_of[order], step_of[order]
    close: dict[int, list[Surface]] = {}
    nearest: dict[int, list[tuple[Surface, Array]]] = {}
    feet: list[Array] = []
    owner: list[int] = []
    for row, start, end in _groups(rows_of):
        x = points[row]
        listed = np.array(
            sorted({n for k in step_of[start:end] for n in by_step.get(int(k), ())}),
            dtype=np.int64,
        )
        if not len(listed):
            continue
        outside = np.maximum(
            np.maximum(boxes[listed, :3] - x, x - boxes[listed, 3:]), 0.0
        )
        listed = listed[fv.norm(outside, axis=1) <= 2 * reach[row] + OFF]
        mine = close.setdefault(row, [])
        for n in listed.tolist():
            s = surfaces[n]
            q = s.patch.foot(x)
            gap = float(fv.norm(q - x))
            if gap <= reach[row]:
                feet.append(q)
                owner.append(row)
                nearest.setdefault(row, []).append((s, q))
            if gap <= 2 * reach[row] + OFF:
                mine.append(s)
    found[_served(part, feet, owner)] = True
    # Where two pieces meet, then where three do: near a corner each edge
    # into it runs on only one side of it, and a point on two pieces found
    # beside the point may be on the side where theirs doesn't (part 4118: a
    # counterbore's floor, its bore and a pocket's rounded corner). A corner
    # within reach is on every two of its pieces' edges, each found within
    # twice the reach (alternating projections land near the nearest point
    # of where two meet): only those three are tried.
    met: dict[int, set[tuple[int, ...]]] = {}
    for many in (2, 3):
        meets: list[Array] = []
        owner = []
        for row, mine in close.items():
            if found[row]:
                continue
            x = points[row]
            edges = met.setdefault(row, set())
            for chosen in itertools.combinations(range(len(mine)), many):
                if many == 3 and not edges.issuperset(
                    itertools.combinations(chosen, 2)
                ):
                    continue
                on_all = _meet([mine[n].patch for n in chosen], x)
                if on_all is None:
                    continue
                gap = float(fv.norm(on_all - x))
                if many == 2 and gap <= 2 * reach[row] + OFF:
                    edges.add(chosen)
                if gap <= reach[row]:
                    meets.append(on_all)
                    owner.append(row)
        found[_served(part, meets, owner)] = True
    left = {row: pairs for row, pairs in nearest.items() if not found[row]}
    if left:
        found[_cusps(part, points, left, reach)] = True
    return found


def _served(
    part: Oracle, candidates: list[Array], owner: list[int]
) -> NDArray[np.int64]:
    """The rows (``owner``, one per candidate) one of whose candidates is where the part's surface may be: on it, or between its forms."""
    if not candidates:
        return np.zeros(0, dtype=np.int64)
    on = _may_be_surface(part, np.array(candidates, dtype=float))
    rows: NDArray[np.int64] = np.unique(np.array(owner, dtype=np.int64)[on])
    return rows


def _may_be_surface(part: Oracle, where: Array) -> NDArray[np.bool_]:
    """Whether the part's surface may be at each point: on it (ON, settled exactly), or between its two forms, as face accounting reads them; or within :data:`OFF` of a cone's apex the rest of the part leaves bare, which no tangent plane settles (docs/V2-stage4.md, 13.4)."""
    inner, outer = part.limits(where)
    clear = (inner == Side.OUT) | (inner == Side.ON)
    same = inner == outer
    found: NDArray[np.bool_] = (
        (same & (inner == Side.ON))
        | ((outer == Side.IN) & clear)
        | ((outer == Side.ON) & (inner == Side.OUT))
    )
    apexes = part.apexes
    unsure = np.flatnonzero((inner == Side.UNKNOWN) | (outer == Side.UNKNOWN))
    if len(apexes) and len(unsure):
        # Unknown there only because of the apex: material over it, or a cut through it, would settle the side.
        gap = fv.norm(where[unsure][:, None, :] - apexes[None, :, :], axis=2).min(
            axis=1
        )
        found[unsure[gap <= OFF]] = True
    return found


#: The sine of an angle under which two facets at a point are one face two solids share (two cuts meeting
#: flush), not two surfaces tangent there and turning apart.
_SHARED = 1e-12
#: How far along a piece from where it touches another, tangent, :func:`_cusps` walks (mm): the sides of a
#: cusp whose curvatures differ by 1/r turn apart past :data:`_THROUGH` some r * 1.4e-6 from where they
#: touch, so within it for r up to about 700 mm.
_CUSP = 1e-3
#: The ways round a point, in the plane of its facets, :func:`_cusps` walks along.
_CUSP_WAYS = 8


def _cusps(
    part: Oracle,
    points: Array,
    nearest: Mapping[int, list[tuple[Surface, Array]]],
    reach: Array,
) -> NDArray[np.int64]:
    """The rows of ``points`` one of whose pieces' nearest points (within ``reach``) is where pieces touch, tangent, the part's surface running on from it between them.

    There every facet of the part's solids lies in one plane (:func:`_touching`),
    so the first-order shape the part is settled by tells only the plane's two
    sides apart, both in the air where two cuts touch: whatever lies between
    them (a cusp of material, where a pocket's rounded corner meets another
    pocket's wall: part 9213) is beyond it there, and along the pieces until
    they turn apart past :data:`_THROUGH`. Along the piece from such a point,
    each of :data:`_CUSP_WAYS` ways round it in that plane, steps doubling
    from ``reach`` find the first place they can be told apart; the place
    counts (:func:`_may_be_surface`) if the facets were turning apart at
    every step before it (one face two solids share never is:
    :data:`_SHARED`), within :data:`_CUSP`: the surface found there runs on
    between the pieces, the material thinning, to where they touch. Told
    apart at the first step, nothing is known between, and the place counts
    only within ``reach`` of the point, as any found is.
    """
    rows = np.array(
        [row for row, pairs in nearest.items() for _ in pairs], dtype=np.int64
    )
    pieces = [s for pairs in nearest.values() for s, _ in pairs]
    feet = np.array(
        [q for pairs in nearest.values() for _, q in pairs], dtype=float
    ).reshape(-1, 3)
    touching, normal, _ = _touching(part, feet)
    starts = np.flatnonzero(touching)
    if not len(starts):
        return np.zeros(0, dtype=np.int64)
    n = normal[starts]
    helper = np.where(
        np.abs(n[:, :1]) < 0.9, np.array([[1.0, 0.0, 0.0]]), np.array([[0.0, 1.0, 0.0]])
    )
    t1 = np.cross(n, helper)
    t1 /= fv.norm(t1, axis=1, keepdims=True)
    t2 = np.cross(n, t1)
    turn = 2.0 * np.pi * np.arange(_CUSP_WAYS) / _CUSP_WAYS
    ways = (fv.cos(turn)[None, :, None] * t1[:, None, :]
            + fv.sin(turn)[None, :, None] * t2[:, None, :]).reshape(-1, 3)  # fmt: skip
    walker = np.repeat(starts, _CUSP_WAYS)
    row_of = rows[walker]
    step = reach[row_of].copy()
    served = np.zeros(len(reach), dtype=bool)
    first = True
    while len(walker):
        at = np.array([pieces[k].patch.foot(feet[k] + d * w)
                       for k, d, w in zip(walker.tolist(), step.tolist(), ways, strict=True)], dtype=float)  # fmt: skip
        still, _, spread = _touching(part, at)
        told = np.flatnonzero(~still)
        if first:
            gap = fv.norm(at[told] - points[row_of[told]], axis=1)
            told = told[gap <= reach[row_of[told]]]
        if len(told):
            served[row_of[told[_may_be_surface(part, at[told])]]] = True
        first = False
        step = 2 * step
        go_on = still & (spread > _SHARED) & (step <= _CUSP) & ~served[row_of]
        walker, row_of, step, ways = (
            walker[go_on],
            row_of[go_on],
            step[go_on],
            ways[go_on],
        )
    return np.flatnonzero(served)


def _touching(part: Oracle, points: Array) -> tuple[NDArray[np.bool_], Array, Array]:
    """At each point, whether two facets or more of the part's solids are there, all in one plane through it (their normals on one line, as :func:`probes` and :class:`_Settle` tell lines apart); with one facet's normal, and the sine of the widest angle between the facets' lines.

    Each solid is asked once about the points near it, however many steps it
    is in (a body a rounding is kept within), so no facet is counted twice.
    """
    n = len(points)
    first = np.full((n, 3), np.nan)
    count = np.zeros(n, dtype=np.int64)
    apart = np.zeros(n)  # the greatest 1 - |cos| of a facet's normal with the first's
    spread = np.zeros(n)
    asked: dict[int, NDArray[np.bool_]] = {}
    for p, k in part._tree.within(points, np.full(n, 2 * ON)):
        for index in np.unique(k).tolist():
            near = np.unique(p[k == index])
            for leaf in leaves(part.steps[index].node):
                done = asked.setdefault(id(leaf), np.zeros(n, dtype=bool))
                rows = near[~done[near]]
                if not len(rows):
                    continue
                done[rows] = True
                found = leaf.locals(points[rows])
                given = found.normals.reshape(len(rows), -1, 3)
                used = (found.where == SURFACE)[:, None] & ~np.isnan(given[:, :, 0])
                normals = np.nan_to_num(given)
                unset = np.isnan(first[rows, 0]) & used.any(axis=1)
                first[rows[unset]] = normals[unset, np.argmax(used[unset], axis=1)]
                line = np.nan_to_num(first[rows])
                cos = np.abs(fv.dot(normals, line[:, None, :]))
                sin = fv.norm(np.cross(normals, line[:, None, :]), axis=2)
                count[rows] += used.sum(axis=1)
                apart[rows] = np.maximum(
                    apart[rows], np.where(used, 1.0 - cos, 0.0).max(axis=1, initial=0.0)
                )
                spread[rows] = np.maximum(
                    spread[rows], np.where(used, sin, 0.0).max(axis=1, initial=0.0)
                )
    return (count >= 2) & (apart <= _THROUGH), np.nan_to_num(first), spread


#: Two mixes of a step's number, summed and xor-ed over a point's steps: its set's signature.
_SET_MIX = (np.uint64(0x9E3779B97F4A7C15), np.uint64(0xD6E8FEB86659FD93))


def _step_sets(
    point_of: NDArray[np.int64],
    step_of: NDArray[np.int64],
    rows: NDArray[np.int64],
    allowed: NDArray[np.bool_],
    n: int,
) -> tuple[NDArray[np.int64], list[tuple[int, ...]]]:
    """Each row's steps (the ``allowed`` ones among those near it), as a group: which group each row is in, and each group's steps, ascending.

    Rows are told apart by a signature of their sets (two mixes of each
    step's number, summed and xor-ed, and how many), then each row's steps
    are checked one by one against those of the row its group was taken
    for; should two different sets share a signature, they are grouped
    exactly after all. The grouping is exact either way.
    """
    slot = np.full(n, -1, dtype=np.int64)
    slot[rows] = np.arange(len(rows))
    keep = (slot[point_of] >= 0) & allowed[step_of]
    width = max(len(allowed), 1)
    key = np.unique(slot[point_of[keep]] * width + step_of[keep])
    row_of, step = key // width, key % width  # by row, then step
    count = np.bincount(row_of, minlength=len(rows))
    start = np.concatenate([[0], np.cumsum(count)[:-1]]).astype(np.int64)
    mixed = step.astype(np.uint64) + np.uint64(1)
    sums = np.zeros(len(rows), dtype=np.uint64)
    xors = np.zeros(len(rows), dtype=np.uint64)
    np.add.at(sums, row_of, mixed * _SET_MIX[0])
    np.bitwise_xor.at(xors, row_of, (mixed * _SET_MIX[1]) ^ (mixed >> np.uint64(3)))
    table = np.stack([sums, xors, count.astype(np.uint64)], axis=1)
    _, first, group = np.unique(table, axis=0, return_index=True, return_inverse=True)
    group = group.reshape(-1).astype(np.int64)
    # Each step of each row against the same place in its group's first row.
    offset = np.arange(len(step)) - start[row_of]
    theirs = step[start[first[group[row_of]]] + offset]
    if not np.array_equal(theirs, step):
        sets = [
            tuple(step[start[k] : start[k] + count[k]].tolist())
            for k in range(len(rows))
        ]
        found: dict[tuple[int, ...], int] = {}
        group = np.array(
            [found.setdefault(t, len(found)) for t in sets], dtype=np.int64
        )
        return group, list(found)
    return group, [
        tuple(step[start[k] : start[k] + count[k]].tolist()) for k in first.tolist()
    ]


def _groups(sorted_rows: NDArray[np.int64]) -> Iterator[tuple[int, int, int]]:
    """Each distinct row of a sorted array, with the range of positions it takes."""
    if not len(sorted_rows):
        return
    cuts = np.flatnonzero(np.diff(sorted_rows)) + 1
    starts = np.concatenate([[0], cuts])
    ends = np.concatenate([cuts, [len(sorted_rows)]])
    for start, end in zip(starts, ends, strict=True):
        yield int(sorted_rows[start]), int(start), int(end)


def _meet(pieces: Sequence[Patch], x: Array, rounds: int = 200) -> Array | None:
    """A point on every one of the pieces near ``x`` (where two meet, an edge; three, a corner), by projecting onto each in turn; None if they don't all meet near it."""
    q = np.asarray(x, dtype=float)
    for _ in range(rounds):
        q_next = q
        for piece in pieces:
            q_next = piece.foot(q_next)
        if float(fv.norm(q_next - q)) <= 1e-13 * (1 + float(fv.norm(q))):
            q = q_next
            break
        q = q_next
    # On the last piece by making; on the others only where they meet there.
    if any(float(fv.norm(piece.foot(q) - q)) > 10 * ON for piece in pieces[:-1]):
        return None
    return q


# ----------------------------------------------------------------------
# Along lines, and round circles
# ----------------------------------------------------------------------
@dataclass(frozen=True, eq=False)
class Along:
    """The part along each of many segments: where each meets a surface, and what lies between.

    Segment ``i``'s crossings are ``t[start[i]:start[i + 1]]``, in order
    (distances along it, from 0 to its length), each with the part's side
    there (``at``). Its open pieces are ``pieces[start[i] + i : start[i + 1]
    + i + 1]``, one more than its crossings: the piece before the first
    crossing, between each two, and after the last, each with the one side
    that holds all along it (except, beside a place where the line only
    grazes a surface, for the points within
    :data:`~forge_checks.shapes.ON` of it there).
    """

    t: Array
    at: NDArray[np.int8]
    pieces: NDArray[np.int8]
    start: NDArray[np.int64]


def _places(
    part: Oracle, origins: Array, directions: Array, lengths: Array
) -> tuple[NDArray[np.int64], Array]:
    """Every place each segment meets a surface of a solid of a step near it, in order along each: (segment, distance along it).

    Places nearer each other than twice :data:`~forge_checks.shapes.ON` are one.
    """
    lines_of: list[NDArray[np.int64]] = []
    ts_of: list[Array] = []
    rays_all, steps_all = [], []
    for rays, steps in part._tree.along(origins, directions, 1e-6, lengths):
        rays_all.append(rays)
        steps_all.append(steps)
    if rays_all:
        ray_of, step_of = np.concatenate(rays_all), np.concatenate(steps_all)
        order = np.lexsort((ray_of, step_of))
        ray_of, step_of = ray_of[order], step_of[order]
        for _, first, last in _groups(step_of):
            rows = ray_of[first:last]
            for leaf in leaves(part.steps[int(step_of[first])].node):
                found = leaf.crossings(origins[rows], directions[rows])
                line, column = np.nonzero(np.isfinite(found))
                t = found[line, column]
                keep = (t >= 0) & (t <= lengths[rows[line]])
                lines_of.append(rows[line[keep]])
                ts_of.append(t[keep])
    line = np.concatenate(lines_of) if lines_of else np.zeros(0, dtype=np.int64)
    t = np.concatenate(ts_of) if ts_of else np.zeros(0)
    order = np.lexsort((t, line))
    line, t = line[order], t[order]
    # Places nearer each other than twice ON are one: the first of them.
    apart = np.ones(len(t), dtype=bool)
    apart[1:] = (line[1:] != line[:-1]) | (t[1:] - t[:-1] > 2 * ON)
    line, t = line[apart], t[apart]
    return line, t


def _along(
    part: Oracle,
    origins: Array,
    directions: Array,
    lengths: Array,
    *,
    air_only: bool = False,
) -> Along:
    """Every place each segment meets a surface of a solid of a step near it, and each piece and place between settled exactly.

    The side of the part changes along a line only where the line meets the
    surface of one of the steps' solids (:meth:`~forge_checks.shapes.Solid.crossings`),
    so one point in each open piece between those places settles the whole
    piece, and each place is settled on its own: where the pieces either side
    of it differ (in and out), it is on the part's surface; where they are the
    same, it may be on the surface (where two solids only touch) or not (a
    hole's floor in the plate's far face, where the hole runs on into the air
    below): it is classified. Places nearer each other than twice
    :data:`~forge_checks.shapes.ON` are one place.

    ``air_only``: classify the places only on segments whose pieces are all
    air (asking whether a segment is air all along); on the others, a place
    is left as the pieces either side of it say.
    """
    origins = np.asarray(origins, dtype=np.float64)
    directions = np.asarray(directions, dtype=np.float64)
    lengths = np.asarray(lengths, dtype=np.float64)
    n = len(origins)
    if (
        origins.shape != (n, 3)
        or directions.shape != (n, 3)
        or lengths.shape != (n,)
        or not (np.all(np.isfinite(origins)) and np.all(np.isfinite(directions)))
        or np.any(~(lengths >= 0))
        or np.any(~np.isfinite(lengths))
    ):
        raise ValueError(
            "segments are finite: origins and directions (n, 3), lengths (n,) of 0 or more"
        )
    if np.any(np.abs(fv.norm(directions, axis=1) - 1.0) > 1e-12):
        raise ValueError("a segment's direction is a unit vector")
    line, t = _places(part, origins, directions, lengths)
    count = np.bincount(line, minlength=n)
    start = np.concatenate([[0], np.cumsum(count)]).astype(np.int64)
    # Each piece's ends: 0, the places in order, the length.
    piece_start = start + np.arange(n + 1)
    lo = np.empty(len(t) + n)
    hi = np.empty(len(t) + n)
    first_piece = piece_start[:-1]
    last_piece = piece_start[1:] - 1
    lo[first_piece] = 0.0
    hi[last_piece] = lengths
    # The places, in order, end one piece and start the next.
    owner = np.repeat(np.arange(n), count)
    place_piece = piece_start[owner] + (np.arange(len(t)) - start[owner])
    hi[place_piece] = t
    lo[place_piece + 1] = t
    piece_line = np.repeat(np.arange(n), count + 1)
    middle = origins[piece_line] + ((lo + hi) / 2)[:, None] * directions[piece_line]
    pieces = part.classify(middle) if len(middle) else np.zeros(0, dtype=np.int8)
    before, after = pieces[place_piece], pieces[place_piece + 1]
    at = np.full(len(t), Side.ON, dtype=np.int8)
    unknown = (before == Side.UNKNOWN) | (after == Side.UNKNOWN)
    at[unknown & (before != after)] = Side.UNKNOWN
    ask = (before == after) | (before == Side.ON) | (after == Side.ON)
    if air_only:
        solid = np.zeros(n, dtype=bool)
        solid[piece_line[pieces != Side.OUT]] = True
        ask &= ~solid[owner]
    if ask.any():
        where = origins[owner[ask]] + t[ask][:, None] * directions[owner[ask]]
        at[ask] = part.classify(where)
    return Along(t, at, pieces, start)


def _around(part: Oracle, centre: Array, u: Array, v: Array, radius: float) -> Array:
    """Every place a circle meets the surface of a solid of a step near it (:meth:`~forge_checks.shapes.Solid.circle_crossings`), in order.

    Between two of them the part's side doesn't change round the circle, nor
    does what it is just off it: a circle that runs along a face (a rim's
    edge in the face round it) passes onto or off it only where it crosses
    the surface of another piece. Places nearer each other than twice
    :data:`~forge_checks.shapes.ON` round the circle are one place.
    """
    centre, u, v = (np.asarray(x, dtype=np.float64) for x in (centre, u, v))
    if (
        any(x.shape != (3,) or not np.all(np.isfinite(x)) for x in (centre, u, v))
        or not (math.isfinite(radius) and radius > 0)
        or abs(float(fv.norm(u)) - 1) > 1e-12
        or abs(float(fv.norm(v)) - 1) > 1e-12
        or abs(float(fv.matmul(u, v))) > 1e-12
    ):
        raise ValueError(
            "a circle has a finite centre, square unit axes and a radius above 0"
        )
    seen: set[int] = set()
    found: list[Array] = []
    # Every step whose box comes within the circle's radius of its centre (and a hair more).
    for _, steps in part._tree.within(centre[None, :], np.array([radius + 1e-6])):
        for k in np.unique(steps).tolist():
            for leaf in leaves(part.steps[k].node):
                if id(leaf) not in seen:
                    seen.add(id(leaf))
                    found.append(leaf.circle_crossings(centre, u, v, radius))
    a = np.sort(np.concatenate(found)) if found else np.zeros(0)
    apart = np.ones(len(a), dtype=bool)
    apart[1:] = a[1:] - a[:-1] > 2 * ON / radius
    return np.asarray(a[apart])


# ----------------------------------------------------------------------
# Volume and topology
# ----------------------------------------------------------------------
def _fold(
    part: Oracle,
    points: Array,
    form: str,
    reach: float | Array,
    enough: float = math.inf,
) -> Array:
    """The steps' bounds folded in order: negative inside the form, positive outside, 1-Lipschitz.

    Only steps within ``reach`` of a point are folded for it: a step farther
    off doesn't touch the ball of that radius round it, so the answer about
    that ball is the same. With ``enough``, the steps far from a point are
    bounded by their boxes alone there (see :func:`~forge_checks.csg.bound`):
    still a bound, its sign exact and its size at most the distance to the
    surface, but not 1-Lipschitz.
    """
    n = len(points)
    value = np.full(n, _INF)
    radius = np.broadcast_to(np.asarray(reach, dtype=float), (n,)).copy()
    rows_all, steps_all = [], []
    for rows, steps in part._tree.within(points, radius):
        rows_all.append(rows)
        steps_all.append(steps)
    if not rows_all:
        return value
    rows_of, step_of = np.concatenate(rows_all), np.concatenate(steps_all)
    order = np.lexsort((rows_of, step_of))
    rows_of, step_of = rows_of[order], step_of[order]
    cuts = np.flatnonzero(np.diff(step_of)) + 1
    for chunk in np.split(np.arange(len(step_of)), cuts):
        if not len(chunk):
            continue
        step = part.steps[int(step_of[chunk[0]])]
        if step.form not in (BOTH, form):
            continue
        rows = rows_of[chunk]
        b = bound(step.node, points[rows], enough)
        value[rows] = (
            np.minimum(value[rows], b) if step.adds else np.maximum(value[rows], -b)
        )
    return value


def _cells(lo: Array, hi: Array, size: float) -> tuple[Array, float]:
    counts = np.maximum(np.ceil((hi - lo) / size).astype(np.int64), 1)
    axes = [lo[k] + (np.arange(counts[k]) + 0.5) * size for k in range(3)]
    grid = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)
    return grid, size


#: Cells looked at together when counting volume: enough for NumPy, few enough for memory.
_CELLS = 1 << 18
_EIGHTHS = np.array(
    [[dx, dy, dz] for dx in (-1, 1) for dy in (-1, 1) for dz in (-1, 1)],
    dtype=np.float64,
)


def _volume(part: Oracle, rel: float, budget: int) -> Interval:
    """The volume of each form, by cells.

    A cell whose centre's folded bound is beyond its half-diagonal is wholly in
    the form or wholly out of it (the bound is no more than the distance to
    the form's surface); the others are
    split in eight, level by level, until what they leave unknown is below
    ``rel`` of what is known to be in, or the budget of cells is spent. The
    cells are worked in batches, so memory stays bounded however many there
    are. The interval runs from the inner form's least to the outer form's
    most: it holds the part's volume, whatever the shape is where it is known
    only between limits.
    """
    lo, hi = np.array(part.lo) - 1e-6, np.array(part.hi) + 1e-6
    ends = []
    for form in (INNER, OUTER):
        size = float(max(hi - lo)) / 8
        unsure, _ = _cells(lo, hi, size)
        inside, spent = 0.0, 0
        while True:
            half = size * math.sqrt(3) / 2
            kept = []
            for start in range(0, len(unsure), _CELLS):
                centres = unsure[start : start + _CELLS]
                f = _fold(part, centres, form, half, half)
                inside += float((f < -half).sum()) * (size * size * size)
                kept.append(centres[np.abs(f) <= half])
            spent += len(unsure)
            unsure = np.concatenate(kept) if kept else np.zeros((0, 3))
            unknown = len(unsure) * (size * size * size)
            if unknown <= rel * max(inside, 1e-300) or spent + 8 * len(unsure) > budget:
                ends.append((inside, inside + unknown))
                break
            size /= 2
            unsure = _split(unsure, size)
    return Interval(ends[0][0], ends[1][1])


def _split(centres: Array, size: float) -> Array:
    """Each cell's eight children (their side ``size``), made a batch at a time."""
    parts = [
        (
            centres[start : start + _CELLS, None, :] + _EIGHTHS[None, :, :] * (size / 2)
        ).reshape(-1, 3)
        for start in range(0, len(centres), _CELLS)
    ]
    return np.concatenate(parts) if parts else np.zeros((0, 3))


#: The most grid points a void count looks at, on each of its grids.
_GRID = 16_000_000
#: Grid lines settled together when counting voids.
_LINES = 4096
#: How near (in grid steps, along each axis) a void's air may come to other air before the count is looked at again more finely.
_NEAR = 2
#: How many times the void count's grid is made finer before the count is given up.
_FINER = 3


def _topology(part: Oracle, resolution: float | None) -> ExpectedTopology:
    """One solid, by the definitions (a cut that would cut the part in two is a CAN'T); and its sealed voids.

    The voids are counted on a grid. Neighbouring grid points are joined only
    where the part along the grid line between them is air all the way
    (:meth:`Oracle.along`), so a wall however thin keeps them apart, and a
    cut that runs on into air (a hole's floor in the plate's far face, a vent
    into a hollow) joins them. The air the grid's border reaches is the
    outside; the rest of the air is in sealed voids, counted as the pieces it
    makes.

    The grid is a quarter of the narrowest thing that makes air (a cut, a
    bore, a hollow; not a rounding) or finer, so each has grid points all
    along it. What it can't see is air finer than it: where later items fill
    a cut but for a sliver, or two cuts only just meet. So the part's
    surface is covered to the grid's step (:func:`_seeds`), and a point just
    off each covering point, in the air, is a **seed**: every piece of air
    has seeds round it, however small, unless it is narrower than the
    covering's finest cells everywhere (:data:`_SEED_FINEST` of the step).
    Each seed must be joined by a straight
    line all in air to a grid point near it, and where the air in front of
    seeds is thin (a passage), seeds of two pieces of air near each other
    must be joined by a straight line, or the count is not made: so no
    piece of air and no passage between two goes unseen (:func:`_join_seeds`).

    The count also stands only if no grid line meets air that no grid point
    is in, and no void's air comes within :data:`_NEAR` steps of other air
    (or of letters or a region, whose shape isn't known) anywhere; otherwise
    it is made again on a grid twice as fine, up to :data:`_FINER` times,
    and then left unchecked with the reason. It is made on two grids, the
    second moved half a step along each axis, and the two must agree.
    """
    size = resolution if resolution is not None else _grid_step(part)
    lo, hi = np.array(part.lo), np.array(part.hi)
    reason = ""
    for _ in range(_FINER + 1):
        counts = np.ceil((hi - lo) / size).astype(np.int64) + 5
        if int(np.prod(counts)) > _GRID:
            if reason:
                reason += f"; a grid of {size:.3g} mm would be too large"
            else:
                reason = (
                    f"the part is too large to count its voids on a {size:.3g} mm grid"
                )
            break
        found = []
        seeds = _seeds(part, size)
        for shift in (0.371, 0.871):
            voids, why = _voids_on_grid(
                part, size, lo - 2 * size + shift * size, counts, seeds
            )
            if why:
                reason = why
                break
            found.append(voids)
        else:
            if found[0] == found[1]:
                return ExpectedTopology(
                    1, found[0], None, ("through-holes are not counted yet",)
                )
            reason = (
                f"two grids of {size:.3g} mm, half a step apart, count {found[0]} and "
                f"{found[1]} voids"
            )
        size /= 2
    return ExpectedTopology(
        1, None, None, (reason, "through-holes are not counted yet")
    )


def _grid_step(part: Oracle) -> float:
    """A quarter of the narrowest thing that makes air, and at most a hundredth of the part's size.

    Roundings and chamfers don't count: what they take away lies along
    edges, beside air already there, and opens no way between two pieces of
    air the grid doesn't find (if one does, the checks of
    :func:`_voids_on_grid` see the air the grid misses, and the count is
    made again finer).
    """
    extent = float(max(np.array(part.hi) - np.array(part.lo)))
    narrow = [
        _width(leaf) for step in part.steps if not step.finish for leaf in _air(step)
    ]
    return max(min([extent / 100, *(w / 4 for w in narrow)]), 1e-3)


def _air(step: Step) -> Iterator[Solid]:
    """The solids that make air: a cut's, and what a body takes out of itself (a tube's bore, a hollow)."""
    if not step.adds:
        yield from leaves(step.node)
        return

    def taken(node: Node, away: bool) -> Iterator[Solid]:
        if isinstance(node, Solid):
            if away:
                yield node
        elif isinstance(node, (Union, Inter)):
            for p in node.parts:
                yield from taken(p, away)
        else:
            yield from taken(node.whole, away)
            yield from taken(node.less, not away)

    yield from taken(step.node, False)


def _width(solid: Solid) -> float:
    """How narrow a solid is at its narrowest, across any direction (infinite for an endless one)."""
    if isinstance(solid, Prism):
        return min(_width2d(solid.shape), solid.t1 - solid.t0)
    if isinstance(solid, Frustum):
        return min(2 * max(solid.r0, solid.r1), solid.t1 - solid.t0)
    if isinstance(solid, (Ball, Torus, Round)):
        return 2 * solid.r
    return _INF


def _width2d(shape: Shape2D) -> float:
    if isinstance(shape, Letters2D):
        return shape.finest
    if isinstance(shape, Disc):
        return 2 * shape.r
    if isinstance(shape, RoundRect):
        return 2 * min(shape.h1, shape.h2)
    if isinstance(shape, Polygon):
        # A convex polygon's width: across from each side, the farthest corner.
        pts = np.array(shape.corners)
        least = _INF
        for k in range(len(pts)):
            a, b = pts[k], pts[(k + 1) % len(pts)]
            n = np.array([b[1] - a[1], a[0] - b[0]]) / float(fv.norm(b - a))
            least = min(least, float(np.max(np.abs(fv.matmul(pts - a, n)))))
        return least
    return float(min(np.array(shape.hi) - np.array(shape.lo)))


@dataclass(frozen=True)
class _Seeds:
    """Points just off the part's surface, in the air, all over it, each with the way out of the part there."""

    points: Array
    normals: Array
    #: How far apart two seeds on one wall may be, at most, with no seed between them.
    spacing: float


#: The surface is covered for seeds to this many grid steps, and its finest cells this part of one.
_SEED_RADIUS, _SEED_FINEST = 2.0, 0.25


def _seeds(part: Oracle, size: float) -> _Seeds:
    """Seeds for a grid of ``size``: a point :data:`OFF` out from each point covering the part's surface.

    Every point of the part's surface is within the covering's radius of a
    covering point (but within its finest cells of where two surfaces
    meet), so two seeds on one wall with none between them are at most
    twice the radius and finest cells apart.
    """
    cover = part.coverage(_SEED_RADIUS * size, _SEED_FINEST * size)
    spacing = 2 * (_SEED_RADIUS + _SEED_FINEST) * size + 4 * OFF
    return _Seeds(cover.points + OFF * cover.normals, cover.normals, spacing)


#: Lines asked about at a time (each line's crossings with every solid near it are held at once).
_LINES_AT_ONCE = 32768


def _clear(part: Oracle, starts: Array, ends: Array) -> NDArray[np.bool_]:
    """Whether the part is air all along each straight line from a start to its end (both ends included)."""
    if len(starts) > _LINES_AT_ONCE:
        return np.concatenate([
            _clear(part, starts[k : k + _LINES_AT_ONCE], ends[k : k + _LINES_AT_ONCE])
            for k in range(0, len(starts), _LINES_AT_ONCE)
        ])  # fmt: skip
    gap = ends - starts
    length = fv.norm(gap, axis=1)
    found = np.zeros(len(starts), dtype=bool)
    usable = length > 0
    if usable.any():
        rows = np.flatnonzero(usable)
        along = _along(
            part,
            starts[rows],
            gap[rows] / length[rows, None],
            length[rows],
            air_only=True,
        )
        count = np.diff(along.start)
        piece_line = np.repeat(np.arange(len(rows)), count + 1)
        place_line = np.repeat(np.arange(len(rows)), count)
        blocked = np.zeros(len(rows), dtype=bool)
        blocked[piece_line[along.pieces != Side.OUT]] = True
        blocked[place_line[along.at != Side.OUT]] = True
        found[rows] = ~blocked
    if (~usable).any():
        found[~usable] = part.classify(starts[~usable]) == Side.OUT
    return found


def _voids_on_grid(
    part: Oracle,
    size: float,
    start: Array,
    counts: NDArray[np.int64],
    seeds: _Seeds | None = None,
) -> tuple[int, str]:
    """The sealed voids on one grid, or why they can't be counted on it."""
    nx, ny, nz = (int(c) for c in counts)
    axes = [start[k] + np.arange(counts[k]) * size for k in range(3)]
    air = np.ones((nx, ny, nz), dtype=bool)
    unknown = np.zeros((nx, ny, nz), dtype=bool)
    joined: list[NDArray[np.bool_]] = []
    strays: list[Array] = []
    for axis in range(3):
        # The grid lines along this axis: one through each point of the other two.
        others = [k for k in range(3) if k != axis]
        n_along = int(counts[axis])
        across = np.stack(
            np.meshgrid(axes[others[0]], axes[others[1]], indexing="ij"), axis=-1
        ).reshape(-1, 2)
        sides = np.empty((len(across), n_along), dtype=np.int8)
        edges = np.empty((len(across), n_along - 1), dtype=bool)
        for first in range(0, len(across), _LINES):
            rows = slice(first, first + _LINES)
            origins = np.zeros((len(across[rows]), 3))
            origins[:, others[0]] = across[rows, 0]
            origins[:, others[1]] = across[rows, 1]
            origins[:, axis] = axes[axis][0]
            sides[rows], edges[rows], stray = _grid_line(
                part, origins, axis, n_along, size
            )
            strays.append(stray)
        # Back to (x, y, z) order.
        shape = [int(counts[k]) for k in others] + [n_along]
        sides3 = np.moveaxis(sides.reshape(shape), 2, axis)
        edges3 = np.moveaxis(edges.reshape([*shape[:2], n_along - 1]), 2, axis)
        air &= sides3 == Side.OUT
        unknown |= sides3 == Side.UNKNOWN
        joined.append(edges3)
    if not (
        air[0].all() and air[-1].all() and air[:, 0].all() and air[:, -1].all()
        and air[:, :, 0].all() and air[:, :, -1].all()
    ):  # fmt: skip
        raise AssertionError(
            "the void count's grid reaches past the part on every side"
        )
    # Runs along z of points joined through air are one node each; x and y join runs.
    joined[2] &= air[:, :, :-1] & air[:, :, 1:]
    begins = air.copy()
    begins[:, :, 1:] &= ~joined[2]
    numbered = np.cumsum(begins.reshape(-1)).reshape(air.shape) - 1
    run: NDArray[np.int64] = np.where(air, numbered, -1).astype(np.int64)
    runs = int(begins.sum())
    parent: NDArray[np.int64] = np.arange(runs, dtype=np.int64)
    for axis in (0, 1):
        edge = (
            joined[axis]
            & np.take(air, range(counts[axis] - 1), axis=axis)
            & np.take(air, range(1, counts[axis]), axis=axis)
        )
        a = np.take(run, range(counts[axis] - 1), axis=axis)[edge]
        b = np.take(run, range(1, counts[axis]), axis=axis)[edge]
        pairs = np.unique(np.minimum(a, b) * runs + np.maximum(a, b))
        _join(parent, pairs // runs, pairs % runs)
    # Air between grid points (a wedge where an overhang meets a face, a gap
    # between two items): joined to the grid points round it that a straight
    # line all in air reaches.
    stray = np.concatenate(strays)
    if len(stray):
        reached = _reach(part, stray, start, size, air)
        if reached is None:
            return 0, (
                f"air finer than the {size:.3g} mm grid that no straight line through air joins to "
                f"a grid point near it (a thin gap or a hollow narrower than the grid)"
            )
        which, cell = reached
        order = np.argsort(which, kind="stable")
        which, cell = which[order], cell[order]
        a = run[cell[:, 0], cell[:, 1], cell[:, 2]]
        same = which[1:] == which[:-1]
        _join(parent, a[1:][same], a[:-1][same])
    if seeds is not None and len(seeds.points):
        parent, why = _join_seeds(part, seeds, start, size, air, run, parent)
        if why:
            return 0, why
    root = _roots(parent, np.arange(runs, dtype=np.int64))
    border = np.zeros(air.shape, dtype=bool)
    border[0] = border[-1] = border[:, 0] = border[:, -1] = True
    border[:, :, 0] = border[:, :, -1] = True
    outside = np.unique(root[run[border & air]])
    sealed = np.setdiff1d(np.unique(root), outside)
    if not len(sealed):
        return 0, ""
    # Each void must be well clear of all other air, and of what isn't known.
    label = np.where(air, root[np.maximum(run, 0)], -1)
    for v in sealed.tolist():
        if _crowded(label, unknown, v):
            return 0, (
                f"a void's air comes within {_NEAR} steps of the {size:.3g} mm grid of other air, "
                f"or of letters or a region"
            )
    return len(sealed), ""


def _reach(
    part: Oracle,
    stray: Array,
    start: Array,
    size: float,
    air: NDArray[np.bool_],
    every: bool = True,
) -> tuple[NDArray[np.int64], NDArray[np.int64]] | None:
    """For points of air between grid points: the air grid points round each that a straight line all in air reaches.

    The grid points looked at are the 64 of the four steps round each
    point's cell. Returns, for every pair joined, which point and the grid
    point's indices; or None if some point is joined to none and ``every``
    point must be.
    """
    corner = np.floor((stray - start) / size).astype(np.int64)
    offsets = np.array(
        [[i, j, k] for i in range(-1, 3) for j in range(-1, 3) for k in range(-1, 3)],
        dtype=np.int64,
    )
    cell: NDArray[np.int64] = (corner[:, None, :] + offsets[None, :, :]).reshape(-1, 3)
    which: NDArray[np.int64] = np.repeat(np.arange(len(stray)), len(offsets))
    inside = np.all((cell >= 0) & (cell < np.array(air.shape)), axis=1)
    which, cell = which[inside], cell[inside]
    is_air = air[cell[:, 0], cell[:, 1], cell[:, 2]]
    which, cell = which[is_air], cell[is_air]
    clear = _clear(part, stray[which], start + cell * size)
    if every and not np.all(np.bincount(which[clear], minlength=len(stray)) > 0):
        return None
    return which[clear], cell[clear]


def _join_seeds(
    part: Oracle,
    seeds: _Seeds,
    start: Array,
    size: float,
    air: NDArray[np.bool_],
    run: NDArray[np.int64],
    parent: NDArray[np.int64],
) -> tuple[NDArray[np.int64], str]:
    """Join each seed to the air grid points round it, and seeds of two pieces of air side by side to each other; or say why the count can't stand.

    Each seed is a node after the grid's runs. It is joined to the nearest
    air corner of its grid cell that a straight line all in air reaches, else
    to every such point of the 64 round it (:func:`_reach`'s); a seed joined
    to none is air the grid doesn't reach. Then every two seeds of different
    pieces of air within a wall's seed spacing of each other, the air in
    front of either thin (it ends within the spacing along its normal), must
    be joined by a straight line all in air, or the count can't stand: they
    may be the two sides of a passage the grid can't see. Air the grid can't
    see is thin, so along any way through it there are such seeds side by
    side where the pieces change. (Where the air in front of both is wide, a
    wall parts them.)
    """
    points, n = seeds.points, len(seeds.points)
    runs = len(parent)
    parent = np.concatenate([parent, np.arange(runs, runs + n, dtype=np.int64)])
    shape = np.array(air.shape)
    base = np.floor((points - start) / size).astype(np.int64)
    corners = np.array(
        [[i, j, k] for i in (0, 1) for j in (0, 1) for k in (0, 1)], dtype=np.int64
    )
    # Each seed's cell's corners: which are air, and how far (a corner at a time: a
    # million seeds' eight corners at once would take gigabytes).
    is_air = np.zeros((n, 8), dtype=bool)
    far = np.empty((n, 8))
    for c, corner in enumerate(corners):
        here = base + corner
        inside = np.flatnonzero(np.all((here >= 0) & (here < shape), axis=1))
        is_air[inside, c] = air[here[inside, 0], here[inside, 1], here[inside, 2]]
        far[:, c] = fv.norm(start + here * size - points, axis=1)
    order = np.argsort(np.where(is_air, far, np.inf), axis=1)
    del far
    joined = np.zeros(n, dtype=bool)
    for k in range(8):
        rows = np.flatnonzero(~joined & is_air[np.arange(n), order[:, k]])
        if not len(rows):
            continue
        target = base[rows] + corners[order[rows, k]]
        ok = _clear(part, points[rows], start + target * size)
        rows, target = rows[ok], target[ok]
        _join(parent, runs + rows, run[target[:, 0], target[:, 1], target[:, 2]])
        joined[rows] = True
    if not joined.all():
        rest = np.flatnonzero(~joined)
        reached = _reach(part, points[rest], start, size, air, every=False)
        if reached is not None:
            which, target = reached
            _join(
                parent,
                runs + rest[which],
                run[target[:, 0], target[:, 1], target[:, 2]],
            )
            joined[rest[which]] = True
    # A seed the grid doesn't reach: joined to the seeds nearest it that a straight line reaches.
    seed_node = runs + np.arange(n, dtype=np.int64)
    for nearest in (8, 64):
        gridded = np.zeros(runs + n, dtype=bool)
        gridded[_roots(parent, np.arange(runs, dtype=np.int64))] = True
        rest = np.flatnonzero(~gridded[_roots(parent, seed_node)])
        if not len(rest):
            break
        a, b = _nearest_points(points, rest, nearest, seeds.spacing)
        ok = _clear(part, points[a], points[b])
        _join(parent, runs + a[ok], runs + b[ok])
    # Seeds of two pieces of air side by side, either in thin air: a straight line joins them, or no count.
    a, b = _near_pairs(points, _roots(parent, seed_node), seeds.spacing)
    if len(a):
        asked = np.unique(np.concatenate([a, b]))
        thin = np.zeros(n, dtype=bool)
        ahead = points[asked] + seeds.spacing * seeds.normals[asked]
        thin[asked] = ~_clear(part, points[asked], ahead)
        either = thin[a] | thin[b]
        a, b = a[either], b[either]
    blocked = np.zeros(len(a), dtype=bool)
    for k in range(0, len(a), _LINES_AT_ONCE):
        pa, pb = a[k : k + _LINES_AT_ONCE], b[k : k + _LINES_AT_ONCE]
        ok = _clear(part, points[pa], points[pb])
        _join(parent, runs + pa[ok], runs + pb[ok])
        blocked[k : k + _LINES_AT_ONCE] = ~ok
    # Two seeds no line joins are of two pieces only if nothing else joined them.
    a, b = a[blocked], b[blocked]
    apart = _roots(parent, runs + a) != _roots(parent, runs + b)
    if apart.any():
        q = points[a[apart][0]]
        return parent, (
            f"two pieces of air finer than the {size:.3g} mm grid lie side by side near "
            f"({q[0]:.3g}, {q[1]:.3g}, {q[2]:.3g}) with no straight line through air between them"
        )
    # Every seed's piece of air has grid points in it.
    seed_root = _roots(parent, seed_node)
    gridded = np.zeros(runs + n, dtype=bool)
    gridded[_roots(parent, np.arange(runs, dtype=np.int64))] = True
    lost = ~gridded[seed_root]
    if lost.any():
        q = points[np.flatnonzero(lost)[0]]
        return parent, (
            f"air finer than the {size:.3g} mm grid near ({q[0]:.3g}, {q[1]:.3g}, {q[2]:.3g}) "
            f"that no straight line through air joins to a grid point"
        )
    return parent, ""


def _nearest_points(
    points: Array, rows: NDArray[np.int64], count: int, reach: float
) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
    """For each of ``rows``, the ``count`` other points nearest it within ``reach``: pairs (row, point)."""
    empty = np.zeros(0, dtype=np.int64)
    cells = np.floor(points / reach).astype(np.int64)
    lo = cells.min(axis=0) - 1
    dims = cells.max(axis=0) + 2 - lo
    key = np.ravel_multi_index((cells - lo).T, dims)
    order = np.argsort(key, kind="stable")
    sorted_key = key[order]
    found_a, found_b = [], []
    for first_row in range(0, len(rows), 1024):
        chunk = rows[first_row : first_row + 1024]
        both_i, both_j = [], []
        for offset in np.ndindex(3, 3, 3):
            other = np.ravel_multi_index(
                (cells[chunk] - lo + np.array(offset) - 1).T, dims
            )
            first = np.searchsorted(sorted_key, other, side="left")
            many = np.searchsorted(sorted_key, other, side="right") - first
            i = np.repeat(chunk, many)
            within = np.arange(len(i)) - np.repeat(np.cumsum(many) - many, many)
            both_i.append(i)
            both_j.append(order[np.repeat(first, many) + within])
        i, j = np.concatenate(both_i), np.concatenate(both_j)
        far = fv.norm(points[i] - points[j], axis=1)
        keep = (i != j) & (far <= reach)
        i, j, far = i[keep], j[keep], far[keep]
        by = np.lexsort((far, i))
        i, j = i[by], j[by]
        starts = np.flatnonzero(np.concatenate([[True], i[1:] != i[:-1]]))
        rank = np.arange(len(i)) - np.repeat(
            starts, np.diff(np.concatenate([starts, [len(i)]]))
        )
        found_a.append(i[rank < count])
        found_b.append(j[rank < count])
    if not found_a:
        return empty, empty
    return np.concatenate(found_a), np.concatenate(found_b)


def _near_pairs(
    points: Array, labels: NDArray[np.int64], reach: float
) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
    """Every pair of points (i < j) of different labels within ``reach`` of each other.

    The points are put in cells ``reach`` wide. Only points with a point of
    another label in a cell next to theirs are looked at, a few thousand at
    a time, so a crowd of points of one label (where a rounding meets a face)
    costs little.
    """
    empty = np.zeros(0, dtype=np.int64)
    if len(points) < 2:
        return empty, empty
    cells = np.floor(points / reach).astype(np.int64)
    lo = cells.min(axis=0) - 1
    dims = cells.max(axis=0) + 2 - lo
    key = np.ravel_multi_index((cells - lo).T, dims)
    order = np.argsort(key, kind="stable")
    sorted_key = key[order]
    # Each cell's least and greatest label; a point is asked about if a cell next to it has another.
    keys, starts = np.unique(sorted_key, return_index=True)
    least = np.minimum.reduceat(labels[order], starts)
    most = np.maximum.reduceat(labels[order], starts)
    offsets = [np.array(o) - 1 for o in np.ndindex(3, 3, 3)]
    asked = np.zeros(len(points), dtype=bool)
    for shift in offsets:
        other = np.ravel_multi_index((cells - lo + shift).T, dims)
        at = np.minimum(np.searchsorted(keys, other), len(keys) - 1)
        there = keys[at] == other
        asked |= there & ((least[at] != labels) | (most[at] != labels))
    rows = np.flatnonzero(asked)
    found_a, found_b = [], []
    for first_row in range(0, len(rows), 4096):
        chunk = rows[first_row : first_row + 4096]
        for shift in offsets:
            other = np.ravel_multi_index((cells[chunk] - lo + shift).T, dims)
            first = np.searchsorted(sorted_key, other, side="left")
            count = np.searchsorted(sorted_key, other, side="right") - first
            if not count.any():
                continue
            i = np.repeat(chunk, count)
            within = np.arange(len(i)) - np.repeat(np.cumsum(count) - count, count)
            j = order[np.repeat(first, count) + within]
            keep = (i < j) & (labels[i] != labels[j])
            i, j = i[keep], j[keep]
            keep = fv.norm(points[i] - points[j], axis=1) <= reach
            found_a.append(i[keep])
            found_b.append(j[keep])
    if not found_a:
        return empty, empty
    return np.concatenate(found_a), np.concatenate(found_b)


def _grid_line(
    part: Oracle, origins: Array, axis: int, n: int, size: float
) -> tuple[NDArray[np.int8], NDArray[np.bool_], Array]:
    """Along grid lines with ``n`` points ``size`` apart: each point's side, whether each two neighbours are joined through air, and a point in each piece of air no grid point is in."""
    lines = len(origins)
    directions = np.zeros((lines, 3))
    directions[:, axis] = 1.0
    found = part.along(origins, directions, np.full(lines, (n - 1) * size))
    count = np.diff(found.start)
    owner = np.repeat(np.arange(lines), count)
    # Each line's elements in order: piece, place, piece, ..., piece.
    first = 2 * found.start[:-1] + np.arange(lines)
    elements = np.empty(2 * len(found.t) + lines, dtype=np.int8)
    piece_line = np.repeat(np.arange(lines), count + 1)
    piece_index = np.arange(len(found.pieces)) - (found.start[piece_line] + piece_line)
    elements[first[piece_line] + 2 * piece_index] = found.pieces
    place_index = np.arange(len(found.t)) - found.start[owner]
    elements[first[owner] + 2 * place_index + 1] = found.at
    # Each grid point's element: after every place before it; on a place it is exactly at.
    t = found.t
    after = np.floor(t / size).astype(np.int64) + 1
    after = np.where((after - 1) * size > t, after - 1, after)
    after = np.where(after * size <= t, after + 1, after)
    passed = np.zeros((lines, n + 1), dtype=np.int64)
    np.add.at(passed, (owner, np.minimum(after, n)), 1)
    before = np.cumsum(passed, axis=1)[:, :n]
    exact = np.zeros((lines, n), dtype=np.int64)
    at_point = np.rint(t / size).astype(np.int64)
    on = (at_point >= 0) & (at_point < n) & (at_point * size == t)
    exact[owner[on], at_point[on]] = 1
    element = first[:, None] + 2 * before + exact
    sides = elements[element]
    bad = np.concatenate([[0], np.cumsum(elements != Side.OUT)])
    joins = bad[element[:, 1:] + 1] - bad[element[:, :-1]] == 0
    # Air no grid point is in: a run of air elements with no point's element in it.
    out = elements == Side.OUT
    line_of = np.repeat(np.arange(lines), 2 * count + 1)
    run = np.cumsum(~out) + line_of
    hosted = np.zeros(int(run.max()) + 2 if len(run) else 1, dtype=bool)
    mine = element.reshape(-1)
    hosted[run[mine[out[mine]]]] = True
    stray = out & ~hosted[run]
    middles = np.zeros((0, 3))
    if stray.any():
        # Its pieces with some length (a place alone is no room), by their middles.
        piece_lo = np.zeros(len(found.pieces))
        piece_hi = np.full(len(found.pieces), (n - 1) * size)
        inner = piece_index > 0
        piece_lo[inner] = t[found.start[piece_line[inner]] + piece_index[inner] - 1]
        last = piece_index < count[piece_line]
        piece_hi[last] = t[found.start[piece_line[last]] + piece_index[last]]
        piece_at = first[piece_line] + 2 * piece_index
        chosen = stray[piece_at] & (piece_hi - piece_lo > 1e-6)
        middle = (piece_lo + piece_hi)[chosen] / 2
        rows = piece_line[chosen]
        middles = origins[rows] + middle[:, None] * directions[rows]
    return sides, joins, middles


def _join(
    parent: NDArray[np.int64], a: NDArray[np.int64], b: NDArray[np.int64]
) -> None:
    """Join the trees of each pair: each root to the lesser root."""
    while len(a):
        ra, rb = _roots(parent, a), _roots(parent, b)
        keep = ra != rb
        a, b, ra, rb = a[keep], b[keep], ra[keep], rb[keep]
        if not len(a):
            return
        np.minimum.at(parent, np.maximum(ra, rb), np.minimum(ra, rb))


def _roots(parent: NDArray[np.int64], x: NDArray[np.int64]) -> NDArray[np.int64]:
    """Each node's root, shortening the paths walked."""
    r = parent[x]
    while True:
        up = parent[r]
        if np.array_equal(up, r):
            parent[x] = r
            return r
        r = up


def _crowded(label: NDArray[np.int64], unknown: NDArray[np.bool_], v: int) -> bool:
    """Whether void ``v``'s points come within :data:`_NEAR` steps (along each axis) of other air or of what isn't known."""
    where = np.argwhere(label == v)
    lo = np.maximum(where.min(axis=0) - _NEAR, 0)
    hi = np.minimum(where.max(axis=0) + _NEAR + 1, label.shape)
    box_ = tuple(slice(int(lo[k]), int(hi[k])) for k in range(3))
    sub = label[box_]
    mine = sub == v
    grown = mine.copy()
    for k in range(3):
        step = grown.copy()
        for d in range(1, _NEAR + 1):
            lead = [slice(None)] * 3
            trail = [slice(None)] * 3
            lead[k], trail[k] = slice(d, None), slice(None, -d)
            step[tuple(lead)] |= grown[tuple(trail)]
            step[tuple(trail)] |= grown[tuple(lead)]
        grown = step
    other = ((sub >= 0) & (sub != v)) | unknown[box_]
    return bool((grown & other).any())
