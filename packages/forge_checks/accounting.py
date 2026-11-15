"""Face accounting: the built part is what was asked, no more and no less (docs/V2-stage2.md, 5.3).

It runs both ways, at the view's own build tolerance (never the design
tolerance, so an unasked 0.3 mm chamfer is found):

- **built points** (the view's coverage: every point of its surface within
  ``radius`` of one, or the radius there: docs/V2-stage4.md, 13.10) must
  each lie on a surface the spec asks for;
- **spec points** (the oracle's coverage of the spec's surfaces) must each
  be built.

Each point has its own tolerance ``t``: the view's there, plus a tenth, and
never less than :data:`FLOOR` (the oracle's own :data:`~.oracle.OFF`).

**The first try, cheap and sound.** A point ``p`` with outward normal ``n``
passes if the other side's material changes the right way round across the
segment from ``p - t n`` to ``p + t n``: inside behind, outside ahead. A
change along a segment no longer than ``t`` proves the other surface is
within ``t`` of ``p``, facing the same way. Against the spec, inside and
outside are its two forms: behind a built point must be inside all the part
may hold (its outer form) and ahead outside all it must hold (its inner
form). Where the forms agree that is the exact test; where they don't (a
rounding's zone at a corner, a thread's flanks, letters, a region) the
point passes as **bounded**, as does a built point between the forms, where
the spec lets the surface be anywhere: on either form's surface too where
the other is clear of it (a chamfer's mitred corner on the outer form, where
the inner form is cut back).

**A witness, for the points that fail it.** Near an edge, or on the flat
floor of a faceted hole between the true rim and the facets, the other
surface is near but not along the normal. Such a point passes only if a
point of the other surface is found within ``t``: for a built point, on the
spec's surface, or where the spec lets it be anywhere, between its forms (a
thread's run-out meeting its root, along the edge of the thread's zone:
:meth:`~.oracle.Oracle.witness`); for a spec point, on the built part's
(:meth:`~.view.GeometryView.distance`, which is exact). A
change of side across a spec point's segment would put the built surface
within ``t`` of it too, so for spec points the exact distance alone
decides (and costs half of classifying both ends).

A point that passes neither way **misses**: a built point where the spec
has no surface (an extra pin, a sealed void, a skin, a square end for a round
one) or a spec point nothing built is near (a missing counterbore, a hole
not cut, a rounding of the wrong radius). The part fails. A built point the
oracle can't place either side of (a cone's apex) is **unsure**: the part is
held.

A view farther from the true surface than it declares fails here too: its
facets' middles on a round face lie beyond their tolerance.

**A part far off as a whole** (drawn in inches, moved by a metre) fails at
once, before its surface is covered: where its box reaches more than
:data:`GROSS` past the box round all the spec's material, built surface is
there that no spec surface is near, and covering a part 25 times too large
would take its square in memory.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from .classes import Verdict
from .oracle import OFF, Oracle
from .view import Coverage, Resolution, Side, ViewProxy, covered

__all__ = ["FLOOR", "GROSS", "MARGIN", "Accounting", "Miss", "Tally", "account_faces"]

Array = NDArray[np.float64]

#: A point's tolerance is the view's there, and a tenth more.
MARGIN = 0.1
#: And never less than this, in mm: the oracle's surface points are within it of the part's surface.
FLOOR = OFF
#: A built part whose box reaches this far (mm) past the box round all the spec's material fails at once.
GROSS = 1.0


@dataclass(frozen=True)
class Miss:
    """A point that is not accounted for: built where the spec has nothing, or in the spec and not built."""

    side: str  # "built" or "spec"
    point: tuple[float, float, float]
    normal: tuple[float, float, float]
    tolerance: float
    why: str


@dataclass(frozen=True)
class Tally:
    """How one side's points fared."""

    points: int
    #: Passed by the first try where the spec's shape is known exactly (a spec point: built within its tolerance).
    exact: int
    bounded: int  # passed by the first try between the spec's two forms
    witnessed: int  # passed by a witness
    missed: int
    unsure: int

    @property
    def passed(self) -> int:
        return self.exact + self.bounded + self.witnessed


@dataclass(frozen=True)
class Accounting:
    """Face accounting's finding: the verdict, both sides' tallies, and the points that failed (the first of each)."""

    verdict: Verdict
    radius: float  # the coverage radius everywhere
    tolerance: tuple[float, float]  # the least and greatest point tolerance used
    built: Tally
    spec: Tally
    misses: tuple[Miss, ...]
    unsure: tuple[Miss, ...]
    finest: float  # the least coverage radius anywhere: a finer box's, or the radius everywhere


def account_faces(
    part: Oracle, view: ViewProxy, radius: float | Resolution, *, shown: int = 20
) -> Accounting:
    """Every built point on a spec surface, and every spec point built, to ``radius`` (both coverages; or the radius a :class:`~.view.Resolution` has at each place) and the view's tolerance."""
    resolution = radius if isinstance(radius, Resolution) else Resolution(float(radius))
    gross = _gross(part, view)
    if gross is not None:
        none = Tally(0, 0, 0, 0, 0, 0)
        return Accounting(Verdict.FAIL, resolution.radius, (FLOOR, FLOOR),
                          Tally(1, 0, 0, 0, 1, 0), none, (gross,), (), resolution.finest)  # fmt: skip
    built = covered(view, resolution)
    t_built = _tolerance(built.tolerance)
    built_tally, built_misses, built_unsure = _built_side(
        part, built.points, built.normals, t_built, shown
    )
    spec = part.coverage(resolution)
    t_spec = _spec_tolerance(built, t_built, spec.points)
    spec_tally, spec_misses = _spec_side(view, spec.points, spec.normals, t_spec, shown)
    if built_tally.missed or spec_tally.missed:
        verdict = Verdict.FAIL
    elif built_tally.unsure or spec_tally.unsure:
        verdict = Verdict.INCONCLUSIVE
    else:
        verdict = Verdict.PASS
    used = np.concatenate([t_built, t_spec])
    return Accounting(
        verdict,
        resolution.radius,
        (float(used.min(initial=FLOOR)), float(used.max(initial=FLOOR))),
        built_tally,
        spec_tally,
        built_misses + spec_misses,
        built_unsure,
        resolution.finest,
    )


def _gross(part: Oracle, view: ViewProxy) -> Miss | None:
    """Where the built part's box reaches more than :data:`GROSS` past the spec's: the farthest corner of it, as a miss; None where it doesn't."""
    built = view.bounds()
    lo, hi = np.asarray(built.lo), np.asarray(built.hi)
    spec_lo, spec_hi = np.asarray(part.lo), np.asarray(part.hi)
    past = np.maximum(spec_lo - lo, hi - spec_hi)
    k = int(np.argmax(past))
    if not past[k] > GROSS:
        return None
    corner = np.where(hi - spec_hi >= spec_lo - lo, hi, lo)
    way = np.zeros(3)
    way[k] = 1.0 if hi[k] - spec_hi[k] >= spec_lo[k] - lo[k] else -1.0
    return Miss(
        "built",
        (float(corner[0]), float(corner[1]), float(corner[2])),
        (float(way[0]), float(way[1]), float(way[2])),
        GROSS,
        f"the built part reaches {float(past[k]):.4g} mm past all the spec's material along {'xyz'[k]}",
    )


def _tolerance(view_tolerance: Array) -> Array:
    return np.asarray(np.maximum(view_tolerance * (1 + MARGIN), FLOOR))


def _spec_tolerance(built: Coverage, t_built: Array, spec_points: Array) -> Array:
    """Each spec point's tolerance: the view's greatest at the built points near it (:func:`_nearby_greatest`), as a point's.

    A built point whose own is raised to the floor raises no spec point's
    past it, so only the others are looked for: on a B-rep whose faces all
    keep within the floor, none, and nothing is searched.
    """
    above = t_built > FLOOR
    return _tolerance(
        _nearby_greatest(
            built.points[above],
            built.tolerance[above],
            spec_points,
            built.radius + float(t_built.max(initial=FLOOR)),
        )
    )


def _built_side(
    part: Oracle, points: Array, normals: Array, t: Array, shown: int
) -> tuple[Tally, tuple[Miss, ...], tuple[Miss, ...]]:
    behind = points - t[:, None] * normals
    ahead = points + t[:, None] * normals
    inner_behind, outer_behind = part.limits(behind)
    inner_ahead, outer_ahead = part.limits(ahead)
    # The inner form is within the outer: inside the inner is inside both, outside the outer outside both.
    exact = (inner_behind == Side.IN) & (outer_ahead == Side.OUT)
    # Where the point itself is, asked only of the points not passed so: each is on a surface, the costliest
    # to settle, and an exact point's own place changes nothing below.
    inner_here = np.full(len(points), Side.ON, dtype=np.int8)
    outer_here = inner_here.copy()
    asked = np.flatnonzero(~exact)
    if len(asked):
        inner_here[asked], outer_here[asked] = part.limits(points[asked])
    # Between the forms the surface may be anywhere, on either form's surface
    # too where the other is clear of it: a built point there, or whose
    # segment runs from what the part may hold to what it needn't, is where
    # the spec allows.
    clear_of_inner = (inner_here == Side.OUT) | (inner_here == Side.ON)
    between = ((outer_here == Side.IN) & clear_of_inner) | (
        (outer_here == Side.ON) & (inner_here == Side.OUT)
    )
    bounded = ~exact & (
        between | ((outer_behind == Side.IN) & (inner_ahead == Side.OUT))
    )
    rest = np.flatnonzero(~(exact | bounded))
    witnessed = np.zeros(len(points), dtype=bool)
    if len(rest):
        witnessed[rest] = part.witness(points[rest], t[rest])
    failed = np.flatnonzero(~(exact | bounded | witnessed))
    unknown = np.zeros(len(points), dtype=bool)
    for found in (
        inner_behind,
        outer_behind,
        inner_ahead,
        outer_ahead,
        inner_here,
        outer_here,
    ):
        unknown |= found == Side.UNKNOWN
    unsure = failed[unknown[failed]]
    missed = failed[~unknown[failed]]
    tally = Tally(
        len(points),
        int(exact.sum()),
        int(bounded.sum()),
        int(witnessed.sum()),
        len(missed),
        len(unsure),
    )
    return (
        tally,
        _misses("built", points, normals, t, missed[:shown], "no surface of the spec is within its tolerance"),
        _misses("built", points, normals, t, unsure[:shown], "the spec's shape isn't known either side of it"),
    )  # fmt: skip


def _spec_side(
    view: ViewProxy, points: Array, normals: Array, t: Array, shown: int
) -> tuple[Tally, tuple[Miss, ...]]:
    # A change of side across the segment would put the built surface within
    # t of the point, so the exact distance alone decides: within t, built
    # (asked as such: a view may answer it without measuring every distance).
    built = view.near(points, t)
    missed = np.flatnonzero(~built)
    tally = Tally(len(points), int(built.sum()), 0, 0, len(missed), 0)
    return tally, _misses(
        "spec",
        points,
        normals,
        t,
        missed[:shown],
        "nothing built is within its tolerance",
    )


def _misses(
    side: str,
    points: Array,
    normals: Array,
    t: Array,
    rows: NDArray[np.int64],
    why: str,
) -> tuple[Miss, ...]:
    return tuple(
        Miss(
            side,
            (float(points[k, 0]), float(points[k, 1]), float(points[k, 2])),
            (float(normals[k, 0]), float(normals[k, 1]), float(normals[k, 2])),
            float(t[k]),
            why,
        )
        for k in rows.tolist()
    )


def _nearby_greatest(
    points: Array, values: Array, queries: Array, reach: float
) -> Array:
    """For each query, the greatest of ``values`` at the ``points`` within ``reach`` of it (or a little farther); 0 if none.

    The points are put in cubes of side ``reach``; a query takes the greatest
    over the 27 cubes round its own, which hold every point within ``reach``.
    """
    found = np.zeros(len(queries))
    if not len(points) or not len(queries):
        return found
    cubes = _Cubes(points, reach)
    greatest = np.zeros(len(cubes.code))
    np.maximum.at(greatest, cubes.slot, values)
    home = np.floor(queries / reach).astype(np.int64)
    for step in _NEIGHBOURS:
        at, hit = cubes.find(home + step)
        found[hit] = np.maximum(found[hit], greatest[at[hit]])
    return found


_NEIGHBOURS = np.array(
    [[dx, dy, dz] for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1)],
    dtype=np.int64,
)


class _Cubes:
    """Points put in cubes of a side: which cubes hold any, numbered in order, and each point's."""

    def __init__(self, points: Array, side: float) -> None:
        cells = np.floor(points / side).astype(np.int64)
        self.lo = cells.min(axis=0)
        self.span = cells.max(axis=0) - self.lo + 1
        if math.prod(int(x) for x in self.span) >= 2**62:
            raise ValueError(
                f"cubes of {side:g} mm are too small for a part this large"
            )
        code = _code(cells - self.lo, self.span)
        self.code, slot = np.unique(code, return_inverse=True)
        self.slot: NDArray[np.int64] = slot.reshape(-1)

    def find(
        self, wanted: NDArray[np.int64]
    ) -> tuple[NDArray[np.int64], NDArray[np.bool_]]:
        """Where each wanted cube is among those held, and whether it is held."""
        inside = np.all((wanted >= self.lo) & (wanted < self.lo + self.span), axis=1)
        want = _code(np.where(inside[:, None], wanted - self.lo, 0), self.span)
        at = np.minimum(np.searchsorted(self.code, want), len(self.code) - 1)
        return at, inside & (self.code[at] == want)


def _code(cells: NDArray[np.int64], span: NDArray[np.int64]) -> NDArray[np.int64]:
    """Each cube's number within the span."""
    return np.asarray((cells[:, 0] * span[1] + cells[:, 1]) * span[2] + cells[:, 2])
