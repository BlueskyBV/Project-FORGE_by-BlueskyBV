"""A built part graded against the generator's model of it, both ways (docs/V2-stage4.md, 12.3).

The truth (:mod:`forge_eval.truth`) says which side of the part every point
is, outside its zones; the built part is asked through its view, as the
judge asks it. Four tests, each on points the truth is sure of:

- **The built part's surface.** Every point of its coverage at ``spacing``:
  the short segment along its normal, ``reach`` either way, runs from inside
  the truth to outside it. Both ends must be clear of every other surface of
  the truth by half of ``reach``, and of the built part's other faces, or the
  point tests nothing (at an edge, the segment of one face runs along the
  other; in a sharp inner corner, on into the material across). Where the
  truth's own surface comes nearer than ``reach`` (an edge whose other face
  meets its own at so shallow an angle, a hole breaking into a pocket's
  ceiling near where they first touch, that the segment's end lies just
  past nine tenths of ``reach`` from it; the tip of a letter's stroke
  thinner there than the segment is long, both its ends in the air beyond
  it; a knife edge of material between two strokes; two letters touching at
  their corners; a cusp of material where a pocket's rounded corner touches
  another pocket's wall), the point passes if, at a distance halved again
  and again, the truth is air somewhere ahead of it and material somewhere
  behind it at that distance, or material ahead of it with air that
  distance along the normal from it: the truth's surface, facing the way
  the point's does, that near (or twice it). The truth alone decides, so a face of the built
  part inside the material, in the air or facing the wrong way fails at
  every distance.
- **The truth's surface.** Every point where a line of a grid ``spacing``
  apart crosses the truth's surface, found to a nanometre by halving (and
  only where the truth was sure all along the search: a zone's edge is no
  surface of the part): within ``reach`` of the built part's surface.
- **Every copy's box.** ``per_box`` points drawn in the box round each copy
  of each item (its solids', grown by a millimetre), clear of the truth's
  surface by ``reach``: on the same side of the built part. A point the
  built part puts on its surface, or can't place, fails: the truth's surface
  is ``reach`` away.
- **The volume**, when the truth's own exact model is given: the built
  part's (an interval) meets the model's, widened by all the zones could
  hold (the volume they leave unsaid).

A grid's lines cross a surface wherever it is, so the second test needs no
sampling of each kind of solid's surface: it samples the part's surface the
truth itself defines, and only it.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
from forge_checks.view import Side, ViewProxy
from forge_numeric import vector as fv
from forge_units import Interval
from numpy.typing import NDArray

from .truth import Threaded, Truth, bounds

__all__ = ["Grade", "grade", "surface_of"]

Array = NDArray[np.float64]

#: The tests, in the order they run.
TESTS = ("built surface", "truth's surface", "copies' boxes")
#: How many halvings place a grid line's crossing (0.5 mm / 2^20 is half a nanometre).
_HALVINGS = 20
#: How many grid points the truth is asked about at once.
_CHUNK = 200_000
#: Where the grid starts within its first step, along each axis (shares of the step).
_SHIFT = np.array([0.1234567, 0.3141593, 0.2718282])
#: A segment's end this share of its length or nearer another of the built part's faces tests nothing.
_ALONE = 0.9
#: How many times a segment that doesn't run across the truth is halved, looking for the truth's surface nearer.
_SHORTER = 20


@dataclass(frozen=True)
class Grade:
    """How a built part compares with the generator's model of it: the points each test tried, those it failed, and the volumes."""

    tried: Mapping[str, int]
    failed: Mapping[str, Array]
    #: The points of the built part's coverage whose segment ends weren't clear of the truth's other surfaces.
    unsettled: int
    #: The built part's volume, and the truth's exact model's widened by its zones' (None: no model given).
    volumes: tuple[Interval, Interval] | None = None

    @property
    def passed(self) -> bool:
        volume_ok = self.volumes is None or self.volumes[0].overlaps(self.volumes[1])
        return volume_ok and all(not len(found) for found in self.failed.values())

    def problems(self) -> list[str]:
        """What failed, each with its count and a few of its points."""
        found = []
        for test in TESTS:
            wrong = self.failed[test]
            if len(wrong):
                shown = ", ".join(
                    "(" + ", ".join(f"{c:.3f}" for c in p) + ")" for p in wrong[:3]
                )
                found.append(
                    f"{test}: {len(wrong)} of {self.tried[test]} points, at {shown}"
                )
        if self.volumes is not None and not self.volumes[0].overlaps(self.volumes[1]):
            built, truth = self.volumes
            found.append(
                f"volume: built {built.lo:.4f} to {built.hi:.4f} mm3, the truth {truth.lo:.4f} to {truth.hi:.4f}"
            )
        return found


#: The ways a point is looked round from (each a unit vector): along each axis, and along each of the cube's
#: diagonals, which leave every plane through the point an axis lies in (a point on a box's edge, looked round
#: along the axes alone, stays on one face's plane or the other's and may never see the side it is on).
_ROUND = np.vstack([np.eye(3), -np.eye(3), np.array([(a, b, c) for a in (-1, 1) for b in (-1, 1)
                                                      for c in (-1, 1)]) / np.sqrt(3.0)])  # fmt: skip


def _clear(truth: Truth, points: Array, by: float) -> tuple[NDArray[np.bool_], NDArray[np.bool_]]:  # fmt: skip
    """Each point's side in the truth, and whether it is clear of the truth's surface: sure, and on the same side ``by`` away every way it is looked round from."""
    steps = np.vstack([np.zeros((1, 3)), _ROUND * by])
    moved = (points[None, :, :] + steps[:, None, :]).reshape(-1, 3)
    sides = truth.inside(moved).reshape(len(steps), len(points))
    sure = ~truth.unsure(moved).reshape(len(steps), len(points)).any(axis=0)
    return sides[0], sure & np.all(sides == sides[0], axis=0)


def _spread(n: int) -> Array:
    """``n`` unit vectors spread evenly over the sphere (a Fibonacci lattice)."""
    k = np.arange(n) + 0.5
    z = 1.0 - 2.0 * k / n
    turn = np.pi * (3.0 - np.sqrt(5.0)) * k
    across = np.sqrt(1.0 - z * z)
    return np.stack([across * fv.cos(turn), across * fv.sin(turn), z], axis=1)


#: The ways looked along from a point for the truth's material, its segment shortened: the axes, the cube's
#: diagonals, and 256 more spread over the sphere (at a knife edge, the material lies in a narrow wedge).
_LOOK = np.vstack([_ROUND, _spread(256)])

#: Where none of :data:`_LOOK` finds it, the ways looked along again: just off the point's own plane, each
#: tilt (radians) to either side, round :data:`_EDGEWAYS` directions in the plane. 256 ways over the sphere
#: are some 13 degrees apart; a bore grazing a slot's end wall met it in a wedge of 1.3 (generated part 8675).
#: Where an edge's two faces are tangent (a pocket's rounded corner meeting another pocket's wall, part 9213)
#: the material between them is a cusp, its wedge s / 2r across at s from the edge (r the radius the faces
#: turn apart at): at the first distance looked at (0.005 mm), the finest tilt sees one for r up to 470 mm.
_TILTS = np.radians([10.0, 3.0, 1.0, 0.3, 0.1, 0.03, 0.01, 0.003, 0.001, 0.0003])
_EDGEWAYS = 64
#: How many points :func:`_crossed_nearer` looks round at once (each along some 1,300 ways at most).
_AT_ONCE = 256


def _edge_ways(normals: Array) -> Array:
    """For each unit normal, the ways just off the plane it is normal to (:data:`_TILTS` each side, round :data:`_EDGEWAYS`): an array (points, ways, 3)."""
    helper = np.where(
        np.abs(normals[:, :1]) < 0.9,
        np.array([[1.0, 0.0, 0.0]]),
        np.array([[0.0, 1.0, 0.0]]),
    )
    t1 = np.cross(normals, helper)
    t1 /= fv.norm(t1, axis=1, keepdims=True)
    t2 = np.cross(normals, t1)
    turn = 2.0 * np.pi * np.arange(_EDGEWAYS) / _EDGEWAYS
    flat = (
        fv.cos(turn)[None, :, None] * t1[:, None, :]
        + fv.sin(turn)[None, :, None] * t2[:, None, :]
    )
    tilts = np.concatenate([_TILTS, -_TILTS])
    ways = (fv.cos(tilts)[None, :, None, None] * flat[:, None, :, :]
            + fv.sin(tilts)[None, :, None, None] * normals[:, None, None, :])  # fmt: skip
    return np.asarray(ways.reshape(len(normals), -1, 3), dtype=np.float64)


def _crossed_nearer(truth: Truth, points: Array, normals: Array, reach: float) -> NDArray[np.bool_]:  # fmt: skip
    """Whether the truth's surface, facing the way the point's normal does, is within ``reach`` / 2 ** k of each point (twice that), for some k from 1 to :data:`_SHORTER`.

    At that distance from the point (:func:`_crossed_at`) the truth must be
    air somewhere ahead and material somewhere behind (each way along the
    normal itself, or along one of :data:`_LOOK` on that side of the point's
    plane), the truth sure of both; or material somewhere ahead, and air a
    step of that distance along the normal from it. Along the normal alone
    is not enough: at an edge sharper than a right angle the material lies
    in a wedge the line behind doesn't enter, and where two solids touch
    along a line (two letters at their corners), the line ahead runs into
    the other.
    Where none of those ways finds it, the ways just off the point's own
    plane are looked along too (:func:`_edge_ways`): at a knife edge the
    wedge is thinner than the sphere's ways are apart. Where the edge's two
    faces are tangent, the material between them is ahead of the plane of the
    face that turns away from the other (the round corner's, part 9213):
    found there, a step along the normal from it reaches air above that
    face. The truth alone decides.
    """
    crossed = np.zeros(len(points), dtype=bool)
    for edgeways in (False, True):
        for k in range(1, _SHORTER + 1):
            left = np.flatnonzero(~crossed)
            if not len(left):
                return crossed
            for some in np.array_split(left, -(-len(left) // _AT_ONCE)):
                crossed[some] = _crossed_at(
                    truth, points[some], normals[some], math.ldexp(reach, -k), edgeways
                )
    return crossed


def _crossed_at(truth: Truth, p: Array, n: Array, size: float, edgeways: bool) -> NDArray[np.bool_]:  # fmt: skip
    """Whether, ``size`` from each point, the truth is air ahead and material behind, or material ahead with air ``size`` along the normal from it (:func:`_crossed_nearer`).

    Ways in the point's own plane count for neither side: a point on it the
    truth takes as material is on the truth's surface, not shown to be either
    side of it.
    """
    looks = (
        _edge_ways(n) if edgeways else np.broadcast_to(_LOOK, (len(p), *_LOOK.shape))
    )
    ways = np.concatenate([n[:, None, :], -n[:, None, :], looks], axis=1)
    there = p[:, None, :] + size * ways
    above = there + size * n[:, None, :]
    both = np.concatenate([there, above], axis=1).reshape(-1, 3)
    inside = truth.inside(both).reshape(len(p), 2, -1)
    sure = ~truth.unsure(both).reshape(len(p), 2, -1)
    material = sure[:, 0] & inside[:, 0]
    along = fv.dot(ways, n[:, None, :])
    air_ahead = (sure[:, 0] & ~inside[:, 0] & (along > 0)).any(axis=1)
    material_behind = (material & (along < 0)).any(axis=1)
    leaves = (material & (along > 0) & sure[:, 1] & ~inside[:, 1]).any(axis=1)
    found: NDArray[np.bool_] = (air_ahead & material_behind) | leaves
    return found


def surface_of(truth: Truth, spacing: float) -> Array:
    """Points of the truth's surface: where the lines of a grid ``spacing`` apart cross it, each placed within a nanometre by halving, where the truth is sure along the way."""
    lo, hi = truth.box()
    # Shifted off the thousandth-of-a-millimetre grid a part's faces are on, so that no plane or line of the
    # grid runs along a face, where the truth's answer on its very boundary would make a crossing of nothing.
    lo, hi = lo - spacing + _SHIFT * spacing, hi + spacing
    counts = np.floor((hi - lo) / spacing).astype(np.int64) + 2
    axes = [lo[k] + spacing * np.arange(counts[k]) for k in range(3)]
    # The grid is asked about one plane across its first axis at a time, so it is never held whole.
    yy, zz = (g.ravel() for g in np.meshgrid(axes[1], axes[2], indexing="ij"))
    starts: list[Array] = []
    ends: list[Array] = []
    previous: NDArray[np.bool_] | None = None
    for x in axes[0]:
        plane = np.column_stack([np.full(len(yy), x), yy, zz])
        sides = truth.inside(plane).reshape(counts[1], counts[2])
        for k, (before, after) in enumerate(
            ((sides[:-1, :], sides[1:, :]), (sides[:, :-1], sides[:, 1:]))
        ):
            i, j = np.nonzero(before != after)
            start = np.column_stack([np.full(len(i), x), axes[1][i], axes[2][j]])
            end = start.copy()
            end[:, 1 + k] += spacing
            starts.append(start)
            ends.append(end)
        if previous is not None:
            i, j = np.nonzero(previous != sides)
            end = np.column_stack([np.full(len(i), x), axes[1][i], axes[2][j]])
            start = end.copy()
            start[:, 0] -= spacing
            starts.append(start)
            ends.append(end)
        previous = sides
    a, b = np.concatenate(starts), np.concatenate(ends)
    if not len(a):
        return np.zeros((0, 3))
    at_a = _inside(truth, a)
    # A crossing whose search ever met a point the truth isn't sure of may be the edge of a zone, not the part's
    # surface (a thread's ring, which the truth takes away, ends at its minor radius): it is left out.
    touched = truth.unsure(a) | truth.unsure(b)
    for _ in range(_HALVINGS):
        middle = (a + b) / 2
        same = _inside(truth, middle) == at_a
        touched |= truth.unsure(middle)
        a[same] = middle[same]
        b[~same] = middle[~same]
    return np.asarray(((a + b) / 2)[~touched])


def _inside(truth: Truth, points: Array) -> NDArray[np.bool_]:
    return np.concatenate(
        [truth.inside(points[k : k + _CHUNK]) for k in range(0, len(points), _CHUNK)]
    )


def unsaid_volume(truth: Truth) -> float:
    """At most how much of the part the truth leaves unsaid: its zones' boxes, and each thread's ring between its minor and major radii."""
    total = sum(float(np.prod(np.subtract(hi, lo))) for lo, hi in truth.zones)
    for step in truth.steps:
        s = step.solid
        if isinstance(s, Threaded):
            total += (
                math.pi * (s.radius * s.radius - s.minor * s.minor) * (s.end - s.start)
            )
    return total


def grade(truth: Truth, built: ViewProxy, *, exact: ViewProxy | None = None, spacing: float = 0.5,
          reach: float = 0.01, per_box: int = 200, seed: int = 0) -> Grade:  # fmt: skip
    """Grade the built part (its view) against the truth: see the module's docstring for each test."""
    tried: dict[str, int] = {}
    failed: dict[str, Array] = {}

    # The built part's surface: in the truth behind each point, out of it ahead. A segment that comes near
    # another of the built part's faces (at an edge, or in a sharp inner corner, where it runs on into the
    # material across) tests nothing, as one near another of the truth's surfaces doesn't: asked only of the
    # segments that would fail, the few.
    cover = built.coverage(spacing)
    p, n = cover.points, cover.normals
    behind, clear_behind = _clear(truth, p - reach * n, reach / 2)
    ahead, clear_ahead = _clear(truth, p + reach * n, reach / 2)
    settled = clear_behind & clear_ahead
    wrong = np.flatnonzero(settled & ~(behind & ~ahead))
    if len(wrong):
        ends = np.concatenate(
            [p[wrong] - reach * n[wrong], p[wrong] + reach * n[wrong]]
        )
        crowded = (
            built.near(ends, np.full(len(ends), _ALONE * reach))
            .reshape(2, -1)
            .any(axis=0)
        )
        settled[wrong[crowded]] = False
        wrong = wrong[~crowded]
    if len(wrong):
        # Where the truth's own surface is nearer than ``reach``, the segment is
        # shortened, by halves: the point passes if it then runs from inside the
        # truth to outside it.
        wrong = wrong[~_crossed_nearer(truth, p[wrong], n[wrong], reach)]
    tried["built surface"] = int(settled.sum())
    failed["built surface"] = p[wrong]

    # The truth's surface: every crossing near the built part's.
    on = surface_of(truth, spacing)
    tried["truth's surface"] = len(on)
    failed["truth's surface"] = on[~built.near(on, np.full(len(on), reach))]

    # Points in every copy's box, clear of the truth's surface: on the same side of the built part.
    rng = np.random.default_rng(seed)
    drawn = []
    for item, copies in truth.copies.items():
        for copy in copies:
            boxes = [
                bounds(s.solid)
                for s in truth.steps
                if (s.item, s.index) == (item, copy.index)
            ]
            if not boxes:
                continue
            lo = np.min([b[0] for b in boxes], axis=0) - 1.0
            hi = np.max([b[1] for b in boxes], axis=0) + 1.0
            drawn.append(rng.uniform(lo, hi, size=(per_box, 3)))
    points = np.concatenate(drawn) if drawn else np.zeros((0, 3))
    sides, clear = _clear(truth, points, reach)
    points, sides = points[clear], sides[clear]
    made = built.classify(points)
    tried["copies' boxes"] = len(points)
    failed["copies' boxes"] = points[made != np.where(sides, Side.IN, Side.OUT)]

    volumes = None
    if exact is not None:
        model, unsaid = exact.volume(), unsaid_volume(truth)
        volumes = (built.volume(), Interval(model.lo - unsaid, model.hi + unsaid))
    return Grade(tried, failed, int((~settled).sum()), volumes)
