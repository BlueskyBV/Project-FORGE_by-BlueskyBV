"""Rigorous measurement of implicit solids.

The idea that makes this module worth having: **discretisation error is reported
as uncertainty, not hidden as a point estimate.**

Every mesh-based volume calculation in every CAD system answers "what is the
volume?" with a single number whose error is unknown to the caller. Forge answers
with an interval that provably contains the true volume, derived as follows.

For a field with Lipschitz bound ``L``, a cube of half-diagonal ``r`` centred at
``c`` lies entirely inside the solid when ``f(c) <= -r*L``, and entirely outside
when ``f(c) >= r*L``. Neither test can be fooled: the field cannot change faster
than ``L``, so it cannot reach zero within the cube. Cells that satisfy neither
test straddle the boundary and are subdivided. At the refinement limit, the
remaining straddling cells contribute their full volume to the *upper* bound and
nothing to the *lower* bound, because that is all that is known about them.

The result is a genuine enclosure::

    volume in [inside_volume, inside_volume + boundary_volume]

which flows straight into :class:`~forge_units.Quantity` and therefore into
three-valued gate evaluation. A mass budget of 40 g compared against a measured
``[39.6, 40.3] g`` yields ``INCONCLUSIVE`` and asks for more refinement -- rather
than ``PASS`` at 39.95 g, which is the answer a point estimate would have given
and which no one could have checked.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from forge_units import Interval, Quantity, parse_unit

from .ibounds import cell_box
from .sdf import SDF, Box, EmptyResultError, GeometryError

Array = np.ndarray

#: Default refinement limit. Eight levels over a 60 mm envelope resolves to a
#: quarter of a millimetre, which bounds the volume of a typical bracket to
#: better than 0.5%.
DEFAULT_MAX_DEPTH = 9

#: Cap on live cells per refinement level. Reaching it stops refinement and
#: widens the reported interval rather than exhausting memory: a wider honest
#: answer beats a narrow one that killed the worker.
DEFAULT_MAX_CELLS = 3_000_000


@dataclass(frozen=True, slots=True)
class MassProperties:
    """Measured properties of a solid, every one carrying its uncertainty."""

    volume: Quantity
    centre_of_mass: tuple[Quantity, Quantity, Quantity]
    bounding_box_lo: tuple[Quantity, Quantity, Quantity]
    bounding_box_hi: tuple[Quantity, Quantity, Quantity]
    #: Cells that remained ambiguous at the refinement limit, as a fraction of
    #: the reported volume. This is the honest measure of how converged the
    #: measurement is.
    relative_uncertainty: float
    depth_reached: int
    cells_evaluated: int
    converged: bool

    def mass(self, density: Quantity) -> Quantity:
        """Mass, with the volume's uncertainty and the density's combined."""
        return (self.volume * density).to("g")

    def bounding_box_size(self) -> tuple[Quantity, Quantity, Quantity]:
        sizes = []
        for lo, hi in zip(self.bounding_box_lo, self.bounding_box_hi):
            size = hi - lo
            low = float(size.magnitude.lo)
            if low < 0.0:
                # A size is never negative, whatever the faces' enclosures
                # overlap to.
                # And never less than nothing at its top either: a solid
                # with no material at all has faces enclosed past each other.
                size = Quantity(Interval(0.0, max(0.0, float(
                    size.magnitude.hi))), size.unit)
            sizes.append(size)
        return tuple(sizes)  # type: ignore[return-value]

    def as_dict(self) -> dict[str, object]:
        return {
            "volume": self.volume.as_dict(),
            "centre_of_mass": [q.as_dict() for q in self.centre_of_mass],
            "bounding_box": {
                "lo": [q.as_dict() for q in self.bounding_box_lo],
                "hi": [q.as_dict() for q in self.bounding_box_hi],
            },
            "relative_uncertainty": self.relative_uncertainty,
            "depth_reached": self.depth_reached,
            "cells_evaluated": self.cells_evaluated,
            "converged": self.converged,
        }


def _initial_cell(solid: SDF) -> tuple[Array, Array]:
    """Centre and half-extent of a box that provably contains the solid.

    The root cell matches the envelope's aspect ratio rather than being a cube.
    For a 60 x 24 x 6 plate a cubic root would spend its refinement budget
    resolving 63 mm of empty air in the thin direction; an aspect-matched root
    keeps every cell proportional to the part, which makes the half-diagonal --
    and therefore the width of the ambiguous band -- substantially smaller at the
    same depth.
    """
    envelope = solid.envelope
    if envelope.is_empty:
        raise EmptyResultError(
            "the construction produced an empty envelope; no solid remains",
            hint="a boolean subtraction may have removed all material, or an "
            "intersection may have no overlap",
        )
    size = np.array(envelope.size, dtype=float)
    if not np.all(np.isfinite(size)):
        raise GeometryError(
            "the solid has an unbounded envelope and cannot be measured",
            hint="an unbounded primitive such as a half-space must be "
            "intersected with a finite body before measurement",
        )
    if np.any(size <= 0.0):
        raise EmptyResultError(
            "the solid's envelope is degenerate in at least one axis",
            size=size.tolist(),
        )
    # Grow slightly so the boundary is strictly interior to the root cell. Very
    # flat envelopes are floored to a fraction of the largest extent so that a
    # near-planar part does not produce needle-shaped cells.
    padded = size * 1.05
    padded = np.maximum(padded, float(size.max()) * 0.02)
    centre = np.array(envelope.centre, dtype=float)
    return centre, padded / 2.0


def _subdivide(centres: Array, half: Array) -> tuple[Array, Array]:
    """Split each cell into eight children."""
    child_half = half / 2.0
    offsets = np.array(
        [
            [sx, sy, sz]
            for sx in (-1.0, 1.0)
            for sy in (-1.0, 1.0)
            for sz in (-1.0, 1.0)
        ]
    ) * child_half
    children = (centres[:, None, :] + offsets[None, :, :]).reshape(-1, 3)
    return children, child_half


_SQRT3 = math.sqrt(3.0)


def _tight_centroid_bound(
    certain_moment: float,
    certain_volume: float,
    cell_volume_lo: Array,
    cell_volume_hi: Array,
    cell_position_lo: Array,
    cell_position_hi: Array,
    *,
    maximise: bool,
    iterations: int = 24,
) -> float:
    """Exact bound on the centroid coordinate over the residual uncertainty.

    The naive bound divides the moment interval by the volume interval, which is
    sound but badly loose, because it lets the numerator take its extreme while
    the denominator independently takes the opposite one. In reality both are
    driven by the *same* unknown fill fractions, so those combinations are not
    achievable.

    The centroid is a linear-fractional function of the fill fractions::

        c(phi) = (A + sum phi_i m_i x_i) / (B + sum phi_i m_i)

    and optimising a linear-fractional function over a box has an exact solution
    by Dinkelbach's method: for a trial value ``lambda``, the inner problem
    ``min/max [numerator - lambda * denominator]`` is separable and solved by
    inspection -- each cell takes its maximum fill when ``(x_i - lambda)`` has
    the favourable sign and its minimum otherwise. Iterating on ``lambda``
    converges to the true extreme in a handful of steps.

    On a 60 mm plate this tightens the reported centroid from about +/-0.6 mm to
    better than +/-0.05 mm, from exactly the same cells.
    """
    sign = -1.0 if maximise else 1.0
    lam = (
        (certain_moment) / certain_volume
        if certain_volume > 0.0
        else float(np.mean(cell_position_lo + cell_position_hi) / 2.0)
    )
    for _ in range(iterations):
        # Each cell independently picks the fill fraction and the position that
        # push (numerator - lam * denominator) in the desired direction.
        position = np.where(
            sign * (cell_position_lo - lam) < sign * (cell_position_hi - lam),
            cell_position_lo,
            cell_position_hi,
        )
        contribution = position - lam
        fill = np.where(
            sign * contribution < 0.0, cell_volume_hi, cell_volume_lo
        )
        numerator = certain_moment + float((fill * position).sum())
        denominator = certain_volume + float(fill.sum())
        if denominator <= 0.0:
            return lam
        updated = numerator / denominator
        if abs(updated - lam) < 1e-12 * max(1.0, abs(lam)):
            return updated
        lam = updated
    return lam


def _residual_cell_bounds(
    field: Array, half: Array, lipschitz: float
) -> tuple[Array, Array]:
    """Per-cell lower and upper bounds on the solid's volume inside the cell.

    A cell that is still ambiguous at the refinement limit is not completely
    unknown, and treating it as ``[0, full]`` throws away the information its
    own distance value carries.

    For an ``L``-Lipschitz field, ``|f(x) - f(c)| <= L*|x - c|``. So every point
    within ``-f(c)/L`` of the centre is inside the solid, and every point within
    ``f(c)/L`` of the centre is outside it. Each of those balls contains an
    axis-aligned cube of side ``2*rho/sqrt(3)``, which clipped to the cell gives
    a sound volume bound with no further field evaluations. Dividing by ``L``
    matters for blended geometry, where ``L`` is ``sqrt(n)`` for a blend folded
    over ``n`` operands rather than one. Nothing here cross-checks the interval
    bounds, so an understated ``L`` would go straight into an unsound volume.

    In practice this roughly halves the residual uncertainty, because most
    boundary cells sit near one edge of the ambiguous band rather than exactly
    on the surface.
    """
    scale = max(lipschitz, 1e-9)
    inside_radius = np.maximum(-field, 0.0) / scale
    outside_radius = np.maximum(field, 0.0) / scale
    full = np.prod(2.0 * half)

    inner_side = np.minimum(
        (2.0 * inside_radius / _SQRT3)[:, None], 2.0 * half[None, :]
    )
    outer_side = np.minimum(
        (2.0 * outside_radius / _SQRT3)[:, None], 2.0 * half[None, :]
    )
    provably_inside = np.prod(inner_side, axis=1)
    provably_outside = np.prod(outer_side, axis=1)
    return provably_inside, full - provably_outside


def measure_mass_properties(
    solid: SDF,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_cells: int = DEFAULT_MAX_CELLS,
    target_relative_uncertainty: float | None = None,
    length_unit: str = "mm",
) -> MassProperties:
    """Measure a solid, returning enclosures rather than point estimates.

    Refinement continues until ``max_depth``, until the cell budget is reached,
    or until ``target_relative_uncertainty`` is met, whichever comes first. The
    result always encloses the true value; the only thing these limits change is
    how wide the enclosure is, and the width is reported.

    Raises
    ------
    EmptyResultError
        If the construction encloses no volume at all. Forge fails closed here:
        an empty solid is a compilation failure, never a part with zero mass.
    """
    centres, half = _initial_cell(solid)
    centres = centres.reshape(1, 3)

    lipschitz = max(solid.lipschitz, 1e-9)
    inside_volume = 0.0
    inside_moment = np.zeros(3)
    boundary_lower = 0.0
    boundary_upper = 0.0
    residual_volume_lo: Array = np.zeros(0)
    residual_volume_hi: Array = np.zeros(0)
    residual_corner_lo: Array = np.zeros((0, 3))
    residual_corner_hi: Array = np.zeros((0, 3))
    inner_lo = np.array([np.inf] * 3)
    inner_hi = np.array([-np.inf] * 3)
    outer_lo = np.array([np.inf] * 3)
    outer_hi = np.array([-np.inf] * 3)

    cells_evaluated = 0
    depth = 0
    converged = True

    while True:
        radius = float(np.linalg.norm(half))
        cell_volume = float(8.0 * half[0] * half[1] * half[2])
        cells_evaluated += centres.shape[0]

        # Bound the field over each whole cell. Interval evaluation decides a
        # cell outright whenever the enclosure stays on one side of zero, which
        # on flat and axis-aligned geometry is almost always. The Lipschitz
        # estimate is kept as a second opinion and the tighter of the two wins,
        # so a node that cannot bound itself well still benefits.
        cell_lo, cell_hi = solid.bounds(cell_box(centres, half))
        field = solid(centres)
        margin = radius * lipschitz
        lower = np.maximum(cell_lo, field - margin)
        upper = np.minimum(cell_hi, field + margin)

        definitely_inside = upper <= 0.0
        definitely_outside = lower >= 0.0
        ambiguous = ~(definitely_inside | definitely_outside)

        if np.any(definitely_inside):
            interior = centres[definitely_inside]
            inside_volume += cell_volume * interior.shape[0]
            inside_moment += cell_volume * interior.sum(axis=0)
            inner_lo = np.minimum(inner_lo, (interior - half).min(axis=0))
            inner_hi = np.maximum(inner_hi, (interior + half).max(axis=0))
            outer_lo = np.minimum(outer_lo, (interior - half).min(axis=0))
            outer_hi = np.maximum(outer_hi, (interior + half).max(axis=0))

        straddling = centres[ambiguous]
        straddling_field = field[ambiguous]

        if straddling.shape[0] == 0:
            break

        # Would the current residual already satisfy the caller's target?
        residual_lower, residual_upper = _residual_cell_bounds(
            straddling_field, half, lipschitz
        )
        pending_lo = inside_volume + boundary_lower + float(residual_lower.sum())
        pending_hi = inside_volume + boundary_upper + float(residual_upper.sum())
        good_enough = (
            target_relative_uncertainty is not None
            and pending_hi > 0.0
            and (pending_hi - pending_lo) / pending_hi <= target_relative_uncertainty
        )

        at_limit = depth >= max_depth - 1
        too_many = straddling.shape[0] * 8 > max_cells

        if at_limit or too_many or good_enough:
            if too_many and not (at_limit or good_enough):
                converged = False
            boundary_lower += float(residual_lower.sum())
            boundary_upper += float(residual_upper.sum())
            corner_lo = straddling - half
            corner_hi = straddling + half
            # Moment contribution of a straddling cell. Its volume lies in
            # [residual_lower, residual_upper] and its centroid somewhere in
            # [corner_lo, corner_hi], so the moment is the interval product of
            # the two. Both factors are known more precisely than "between
            # nothing and everything", and using that is what keeps the reported
            # centre of mass from being uselessly wide -- the naive bound puts a
            # 60 mm plate's centroid at 30 +/- 0.7 mm where this one gets to
            # +/- 0.05 mm from the same cells.
            residual_volume_lo = residual_lower
            residual_volume_hi = residual_upper
            residual_corner_lo = corner_lo
            residual_corner_hi = corner_hi
            outer_lo = np.minimum(outer_lo, corner_lo.min(axis=0))
            outer_hi = np.maximum(outer_hi, corner_hi.max(axis=0))
            break

        centres, half = _subdivide(straddling, half)
        depth += 1

    if inside_volume + boundary_upper <= 0.0:
        raise EmptyResultError(
            "the construction encloses no volume",
            hint="check for a subtraction that removed all material, an "
            "intersection with no overlap, or a dimension driven to zero",
            depth_reached=depth,
            cells_evaluated=cells_evaluated,
        )

    volume_interval = Interval(
        inside_volume + boundary_lower, inside_volume + boundary_upper
    )
    boundary_volume = boundary_upper - boundary_lower

    # Centre of mass by interval division. The denominator is strictly positive
    # whenever any interior cell was found, which the check above guarantees.
    centroid: list[Quantity] = []
    volume_unit = parse_unit(f"{length_unit}^3")
    length = parse_unit(length_unit)
    for axis in range(3):
        if inside_volume <= 0.0 and residual_volume_hi.size == 0:
            centroid.append(
                Quantity(Interval(float(outer_lo[axis]), float(outer_hi[axis])), length)
            )
            continue
        if residual_volume_hi.size == 0:
            value = inside_moment[axis] / inside_volume
            centroid.append(Quantity(Interval.exact(value), length))
            continue
        lower = _tight_centroid_bound(
            float(inside_moment[axis]),
            inside_volume,
            residual_volume_lo,
            residual_volume_hi,
            residual_corner_lo[:, axis],
            residual_corner_hi[:, axis],
            maximise=False,
        )
        upper = _tight_centroid_bound(
            float(inside_moment[axis]),
            inside_volume,
            residual_volume_lo,
            residual_volume_hi,
            residual_corner_lo[:, axis],
            residual_corner_hi[:, axis],
            maximise=True,
        )
        if lower > upper:
            lower, upper = upper, lower
        centroid.append(Quantity(Interval(lower, upper), length))

    if not np.all(np.isfinite(inner_lo)):
        # No cell was proved wholly inside, so nothing is known about where
        # the faces are within the outer box. This used to set the inner box
        # to the outer one -- a bounding box reported to zero width: a bent
        # arm plate measured at depth 6 as exactly 126 x 79 x 53 mm, against
        # a true 120 x 74 x 16.3.
        inner_lo, inner_hi = outer_hi.copy(), outer_lo.copy()

    relative = (
        volume_interval.width / volume_interval.hi
        if volume_interval.hi > 0
        else 1.0
    )

    return MassProperties(
        volume=Quantity(volume_interval, volume_unit),
        centre_of_mass=(centroid[0], centroid[1], centroid[2]),
        bounding_box_lo=tuple(  # type: ignore[arg-type]
            Quantity(Interval(float(outer_lo[i]), float(inner_lo[i])), length)
            for i in range(3)
        ),
        bounding_box_hi=tuple(  # type: ignore[arg-type]
            Quantity(Interval(float(inner_hi[i]), float(outer_hi[i])), length)
            for i in range(3)
        ),
        relative_uncertainty=relative,
        depth_reached=depth,
        cells_evaluated=cells_evaluated,
        converged=converged,
    )


def _slab_holds_material(
    solid: SDF, lo: Array, hi: Array, axis: int, *, lipschitz: float,
    max_cells: int, max_depth: int,
) -> tuple[str, float]:
    """Whether any material lies in the box ``[lo, hi]``: ``("empty", _)``,
    ``("found", reach)`` with ``reach`` how far along ``axis`` -- towards
    ``hi[axis]`` -- material provably goes, or ``("unknown", _)`` when the
    budget ran out first. Every answer is a proof, never an estimate."""
    size = np.maximum(hi - lo, 1e-12)
    # Cells about as thick as the slab, so a thin slab over a wide face
    # starts as one layer of near-cubes rather than one flat cell.
    side = max(float(size[axis]), float(size.max()) / 64.0)
    counts = np.maximum(1, np.ceil(size / side)).astype(int)
    counts[axis] = 1
    half = size / counts / 2.0
    axes = [lo[i] + half[i] * (2 * np.arange(counts[i]) + 1) for i in range(3)]
    centres = np.stack(np.meshgrid(*axes, indexing="ij"), -1).reshape(-1, 3)
    for _ in range(max_depth + 1):
        if centres.shape[0] == 0:
            return "empty", 0.0
        cell_lo, cell_hi = solid.bounds(cell_box(centres, half))
        field = solid(centres)
        radius = float(np.linalg.norm(half))
        lower = np.maximum(cell_lo, field - radius * lipschitz)
        upper = np.minimum(cell_hi, field + radius * lipschitz)
        if np.any(upper <= 0.0):
            # A whole cell of material: it reaches the cell's far face.
            inside = centres[upper <= 0.0]
            return "found", float((inside[:, axis] + half[axis]).max())
        if np.any(field < 0.0):
            # A point of material, and a ball of it around the point.
            at = field < 0.0
            reach = centres[at, axis] + (-field[at]) / lipschitz
            return "found", float(min(reach.max(), hi[axis]))
        live = ~(lower >= 0.0)
        centres = centres[live]
        if centres.shape[0] == 0:
            return "empty", 0.0
        if centres.shape[0] * 8 > max_cells:
            return "unknown", 0.0
        centres, half = _subdivide(centres, half)
    return "unknown", 0.0


def refine_extents(
    solid: SDF,
    properties: MassProperties,
    *,
    tolerance: float = 0.01,
    max_cells: int = 100_000,
    max_depth: int = 9,
    max_rounds: int = 24,
    time_budget: float = 3.0,
) -> MassProperties:
    """The same measurement with each face of its bounding box closed in on.

    The octree's bounding box is a by-product of measuring the volume, and
    as loose as the cells at the depth it stopped: a 4 mm flight-controller
    plate came back 3.675 +/- 0.525 mm thick, so an "equals 4 mm" claim
    passed -- correctly, and as it would have for a 3.5 mm plate. Each face
    is now bisected on its own: a slab beyond a trial position is proved
    empty (the face is inside it) or found to hold material (the face is
    beyond it), cell by cell, with the same interval and Lipschitz tests as
    the octree. Never wider than it was, and still an enclosure: a slab that
    cannot be decided within the budget leaves that face where it was.
    """
    lipschitz = max(solid.lipschitz, 1e-9)
    lo_q = [(float(q.magnitude.lo), float(q.magnitude.hi))
            for q in properties.bounding_box_lo]
    hi_q = [(float(q.magnitude.lo), float(q.magnitude.hi))
            for q in properties.bounding_box_hi]
    outer_lo = np.array([a for a, _ in lo_q])
    outer_hi = np.array([b for _, b in hi_q])
    # The search space across each face: the octree's outer box, which
    # provably holds all the material.
    box_lo, box_hi = outer_lo.copy(), outer_hi.copy()

    def close_in(axis: int, sign: int, near: float, far: float) -> tuple[
            float, float]:
        """``near`` is reached by material, nothing lies beyond ``far``;
        both along ``sign`` on ``axis``."""
        def probe(start: float, end: float) -> tuple[str, float]:
            """Material in the slab from ``start`` to ``end`` along ``sign``."""
            lo, hi = box_lo.copy(), box_hi.copy()
            if sign > 0:
                lo[axis], hi[axis] = start, end
                return _slab_holds_material(
                    solid, lo, hi, axis, lipschitz=lipschitz,
                    max_cells=max_cells, max_depth=max_depth)
            # The search only ever runs towards +axis: mirror the solid.
            lo[axis], hi[axis] = -start, -end
            answer, reach = _slab_holds_material(
                _Mirrored(solid, axis), lo, hi, axis, lipschitz=lipschitz,
                max_cells=max_cells, max_depth=max_depth)
            return answer, -reach

        def beyond(a: float, b: float) -> bool:
            return (a > b) if sign > 0 else (a < b)

        # A budget per face, not a correctness limit: a face not closed in on
        # by then keeps the enclosure it has, which is still an enclosure.
        deadline = time.monotonic() + time_budget

        for _ in range(max_rounds):
            if abs(far - near) <= tolerance or time.monotonic() > deadline:
                break
            trial = (near + far) / 2.0
            answer, reach = probe(trial, far)
            if answer == "empty":
                far = trial
                continue
            if answer == "found":
                near = far if not beyond(far, reach) else reach
                continue
            # Undecided next to the face: prove less on the far side, and
            # look for material on the near side instead.
            moved = False
            outer = (trial + far) / 2.0
            if probe(outer, far)[0] == "empty":
                far, moved = outer, True
            answer, reach = probe(near, trial)
            if answer == "found" and beyond(reach, near):
                near, moved = reach, True
            if not moved:
                break
        return near, far

    new_lo, new_hi = [], []
    length = properties.bounding_box_lo[0].unit
    for axis in range(3):
        (lo_out, lo_in), (hi_in, hi_out) = lo_q[axis], hi_q[axis]
        if not all(np.isfinite([lo_out, lo_in, hi_in, hi_out])):
            new_lo.append(properties.bounding_box_lo[axis])
            new_hi.append(properties.bounding_box_hi[axis])
            continue
        top_near, top_far = close_in(axis, +1, hi_in, hi_out)
        bottom_near, bottom_far = close_in(axis, -1, lo_in, lo_out)
        new_lo.append(Quantity(Interval(bottom_far, bottom_near), length))
        new_hi.append(Quantity(Interval(top_near, top_far), length))
    from dataclasses import replace as _replace
    return _replace(properties, bounding_box_lo=tuple(new_lo),
                    bounding_box_hi=tuple(new_hi))


class _Mirrored:
    """A solid reflected through the plane ``axis = 0``: what a search that
    only ever runs towards +axis needs to find a face on the -axis side."""

    def __init__(self, solid: SDF, axis: int) -> None:
        self._solid = solid
        self._axis = axis

    def __call__(self, points: Array) -> Array:
        flipped = np.array(points, dtype=float, copy=True)
        flipped[..., self._axis] *= -1.0
        return self._solid(flipped)

    def bounds(self, box):  # noqa: ANN001 - an interval pair, as `SDF.bounds`
        lo, hi = box
        lo = np.array(lo, dtype=float, copy=True)
        hi = np.array(hi, dtype=float, copy=True)
        a = self._axis
        lo[..., a], hi[..., a] = -hi[..., a].copy(), -lo[..., a].copy()
        return self._solid.bounds((lo, hi))


# ----------------------------------------------------------------------
# Interference and clearance
# ----------------------------------------------------------------------
def minimum_separation(
    first: SDF,
    second: SDF,
    *,
    samples: int = 60,
    length_unit: str = "mm",
) -> Quantity:
    """Smallest gap between two solids; negative when they interpenetrate.

    Evaluated on a grid over the intersection of the two envelopes, refined
    around the closest samples. The result is reported as an interval whose
    width reflects the grid spacing, so a "0.5 mm clearance required" gate over
    a measured ``[0.42, 0.58]`` is inconclusive rather than a coin flip.
    """
    region = first.envelope.intersection(second.envelope)
    if region.is_empty:
        # The envelopes do not even overlap, so the solids certainly do not.
        gap = _envelope_gap(first.envelope, second.envelope)
        return Quantity(Interval(gap, float("inf")), parse_unit(length_unit))

    lo = np.array(region.lo, dtype=float)
    hi = np.array(region.hi, dtype=float)
    span = hi - lo
    padding = np.maximum(span * 0.05, 1e-6)
    lo, hi = lo - padding, hi + padding

    best = float("inf")
    best_point = (lo + hi) / 2.0
    current_lo, current_hi = lo, hi

    for _ in range(3):  # coarse pass then two refinements
        grid = _grid(current_lo, current_hi, samples)
        values = np.maximum(first(grid), second(grid))
        index = int(np.argmin(values))
        if values[index] < best:
            best = float(values[index])
            best_point = grid[index]
        extent = (current_hi - current_lo) / max(samples - 1, 1) * 2.0
        current_lo = best_point - extent
        current_hi = best_point + extent

    # The grid cannot have missed a closer point by more than the Lipschitz
    # bound times half the final cell diagonal.
    resolution = float(np.linalg.norm((current_hi - current_lo) / max(samples - 1, 1)))
    bound = resolution * max(first.lipschitz, second.lipschitz) / 2.0
    return Quantity(
        Interval(best - bound, best + bound), parse_unit(length_unit)
    )


def _envelope_gap(first: Box, second: Box) -> float:
    gaps = []
    for axis in range(3):
        gaps.append(
            max(
                first.lo[axis] - second.hi[axis],
                second.lo[axis] - first.hi[axis],
                0.0,
            )
        )
    return math.sqrt(sum(gap * gap for gap in gaps))


def _grid(lo: Array, hi: Array, samples: int) -> Array:
    axes = [np.linspace(lo[axis], hi[axis], samples) for axis in range(3)]
    mesh = np.meshgrid(*axes, indexing="ij")
    return np.stack([component.ravel() for component in mesh], axis=1)


def solids_interfere(first: SDF, second: SDF, *, samples: int = 60) -> bool:
    """Whether two solids share any interior point, by the separation test."""
    separation = minimum_separation(first, second, samples=samples)
    return separation.magnitude.lo < 0.0


# ----------------------------------------------------------------------
# Wall thickness
# ----------------------------------------------------------------------
def minimum_wall_thickness(
    solid: SDF,
    surface_points: Array,
    *,
    max_steps: int = 64,
    length_unit: str = "mm",
    ignore_below: float = 1e-4,
) -> tuple[Quantity, Array | None]:
    """Smallest through-thickness found by marching inward from the surface.

    From each surface sample the ray marches along the inward normal, stepping by
    the local distance to the boundary. Because that step can never cross the
    surface, the march converges on the exit point and the distance travelled is
    the local chord thickness. The minimum over all samples is the reported wall
    thickness.

    This is a *sampled* measurement and is reported as such: it can only find
    thin walls that a sample landed on. It is an upper bound on the true minimum,
    which is the conservative direction for a manufacturability check --
    reporting a wall thinner than it is would be the dangerous error, and this
    method cannot make it.

    Returns the thickness and the surface point where it was found.
    """
    points = np.asarray(surface_points, dtype=float).reshape(-1, 3)
    if points.size == 0:
        raise GeometryError(
            "wall-thickness measurement needs surface samples",
            hint="extract a surface mesh first",
        )

    normals = solid.gradient(points)
    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
    lengths[lengths < 1e-12] = 1.0
    inward = -normals / lengths

    envelope_diagonal = solid.envelope.diagonal
    start_offset = max(envelope_diagonal * 1e-5, 1e-6)
    position = points + inward * start_offset
    travelled = np.full(points.shape[0], start_offset)

    # A ray only measures a wall if it actually started *inside* the material.
    # Samples that land on a convex edge, or whose estimated normal points the
    # wrong way, begin outside and never enter; counting their near-zero travel
    # as a chord would report a wall thickness of nearly zero for a perfectly
    # sound part. They are excluded rather than clamped, because a ray that
    # measured nothing should contribute nothing.
    entered = solid(position) < 0.0
    active = entered.copy()

    for _ in range(max_steps):
        if not np.any(active):
            break
        current = position[active]
        distance = -solid(current)  # positive inside
        step = np.maximum(distance, envelope_diagonal * 1e-6)
        position[active] = current + inward[active] * step[:, None]
        travelled[active] += step
        still_inside = solid(position[active]) < 0.0
        indices = np.flatnonzero(active)
        active[indices[~still_inside]] = False

    # A ray still inside after the step budget never found the far wall, so its
    # chord is unbounded and unusable.
    completed = entered & ~active & (travelled > ignore_below)
    if not np.any(completed):
        raise GeometryError(
            "no through-thickness chord could be measured",
            hint="no surface sample produced a ray that entered the material "
            "and exited again within the step budget; the geometry may be "
            "unbounded, or the surface samples may be degenerate",
            samples=int(points.shape[0]),
            entered=int(entered.sum()),
            still_marching=int(active.sum()),
        )

    # A chord is a wall only where the ray leaves through the far side of
    # it -- a face turned roughly opposite to the one it entered by. At a
    # convex edge a sample on one face whose inward direction tilts out
    # through the other leaves through that other face after a few microns:
    # the lower-leg shell's top rim, where the near-vertical side meets the
    # top cap, read as a wall 0.006 mm thick on a part whose walls are all
    # 8. And a ray from a curved wall slanting into a hole's bore beside
    # it read 0.46 mm on the same part. Within 37 degrees of opposite
    # counts: a true wall's two faces are parallel, a ligament between two
    # holes is crossed square, and a thin knife edge's faces nearly so.
    exits = position[completed]
    exit_normals = solid.gradient(exits)
    exit_lengths = np.linalg.norm(exit_normals, axis=1, keepdims=True)
    exit_lengths[exit_lengths < 1e-12] = 1.0
    facing = np.einsum("ij,ij->i", exit_normals / exit_lengths,
                       -inward[completed])
    across = completed.copy()
    across[np.flatnonzero(completed)] = facing < -0.8
    if np.any(across):
        completed = across
    candidates = np.where(completed, travelled, np.inf)
    index = int(np.argmin(candidates))
    thickness = float(travelled[index])
    # The measurement resolution is the final step size; report it as spread.
    spread = max(envelope_diagonal * 1e-4, thickness * 1e-3)
    return (
        Quantity(
            Interval(max(0.0, thickness - spread), thickness + spread),
            parse_unit(length_unit),
        ),
        points[index],
    )


def surface_samples(solid: SDF, *, resolution: int = 48) -> Array:
    """Points near the zero level set, for thickness and visual checks."""
    envelope = solid.envelope.grown(solid.envelope.diagonal * 0.02)
    grid = _grid(
        np.array(envelope.lo, dtype=float),
        np.array(envelope.hi, dtype=float),
        resolution,
    )
    field = solid(grid)
    spacing = envelope.diagonal / resolution
    near = np.abs(field) < spacing
    candidates = grid[near]
    if candidates.size == 0:
        return candidates.reshape(0, 3)
    # Project onto the surface with two Newton steps along the gradient.
    for _ in range(2):
        value = solid(candidates)
        gradient = solid.gradient(candidates)
        norm = np.linalg.norm(gradient, axis=1, keepdims=True)
        norm[norm < 1e-12] = 1.0
        candidates = candidates - gradient / norm * value[:, None]
    # A point the two steps did not bring to the surface is not on it. At a
    # concave edge -- where a hollow dome's flat inner face meets its curved
    # one -- the gradient has no single direction, and the step can land a
    # tenth of a millimetre inside the material: a "surface" point from
    # which every chord is short, which reported a 2 mm wall as 1.92.
    # Measured: every other sample sits within 1e-14 mm of the surface.
    on = np.abs(solid(candidates)) <= spacing * 1e-4
    return candidates[on]


__all__ = [
    "MassProperties",
    "measure_mass_properties",
    "refine_extents",
    "minimum_separation",
    "solids_interfere",
    "minimum_wall_thickness",
    "surface_samples",
    "DEFAULT_MAX_DEPTH",
    "DEFAULT_MAX_CELLS",
]
