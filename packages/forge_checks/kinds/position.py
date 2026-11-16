"""The ``position`` kind: where an item is on its face, measured from the built face itself.

A position is measured the way the spec gives it (docs/definitions/place.md),
between two built things, never from the frame's coordinates: so a part
built in the wrong place on the build plate isn't failed for it, and a hole
measured from the wrong end is.

- **from an edge** (``side``): from the host face's edge (the fitted plane
  of the host's side face there) to the item's centre (its fitted axis, or
  the middle of its two fitted sides) or to its near edge;
- **from the centre** (``offset``, ``centred``): from the middle of the
  host face's two fitted edges to the item's centre.

Each end is a :data:`Ref`: a fitted plane, the middle of two, a fitted round
surface's axis, or its edge on one side (the axis and the fitted radius), a
fitted cone's axis or its rim at one end, the mean of several built centres
(a pattern's centre), or the centre of the circle through them (an arc's,
whose copies' mean is not its centre: :func:`ring`, which the ``pattern``
and ``angle`` kinds use for circles and arcs too).

**Tolerance policy:** a linear size: the position's own tolerance, or ISO
2768-m by the distance it gives (for ``centred``, by the distance to either
edge of the face).

**Uncertainty:** each end's, added.

**Mutants and near-misses:** the item moved to each limit of the tolerance,
``2u`` outside (it must fail) and ``2u`` inside (it must pass).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from forge_numeric import vector as fv
from numpy.typing import NDArray

from ..classes import Tolerance, bracket_mutants
from ..measure import FEWEST, CircleFit, Measurement, Probe, fit_circle
from .surfaces import (
    Ball,
    Cone,
    Plane,
    Round,
    fitted_ball,
    fitted_cone,
    fitted_round,
    plane_offset,
)

__all__ = [
    "BallCentre",
    "Centre",
    "ConeRim",
    "Hub",
    "Mean",
    "Middle",
    "Position",
    "Ref",
    "Ring",
    "RoundEdge",
    "Spot",
    "locate",
    "measure",
    "mutants",
    "ring",
]

Vec = tuple[float, float, float]
Array = NDArray[np.float64]


@dataclass(frozen=True)
class Middle:
    """Half way between two built things: two fitted planes (a face's two edges), or two fitted axes (a slot's two round ends)."""

    a: Ref
    b: Ref


@dataclass(frozen=True)
class Centre:
    """A fitted round surface's axis."""

    round: Round


@dataclass(frozen=True)
class BallCentre:
    """A fitted ball's centre."""

    ball: Ball


@dataclass(frozen=True)
class RoundEdge:
    """A fitted round surface's (or ball's) edge on the side ``along`` points to (``sign`` 1) or away from (-1)."""

    round: Round | Ball
    sign: float


@dataclass(frozen=True)
class ConeRim:
    """A fitted cone's axis (``sign`` 0), or its rim at ``at`` along it on the side ``along`` points to (``sign`` 1) or away from (-1)."""

    cone: Cone
    at: float
    sign: float


@dataclass(frozen=True)
class Mean:
    """The mean of several built things' places (a pattern's centre: its copies' axes)."""

    each: tuple[Ref, ...]


@dataclass(frozen=True)
class Spot:
    """A copy's built centre in a plane: where ``first`` puts it along the plane's first axis, and ``second`` along its second (a round item's fitted axis, for both)."""

    first: Ref
    second: Ref


@dataclass(frozen=True)
class Hub:
    """The centre of the circle through several copies' built centres, in the plane of the two axes ``plane`` (an arc's copies, at least three)."""

    each: tuple[Spot, ...]
    plane: tuple[Vec, Vec]


Ref = Plane | Middle | Centre | BallCentre | RoundEdge | ConeRim | Mean | Hub


@dataclass(frozen=True)
class Ring:
    """Copies' built centres in a plane, and the circle through them.

    ``points`` are each copy's centre along the plane's two axes ``e1`` and
    ``e2`` (from the frame's origin), ``spread`` how far each may be off
    along them; ``circle`` the circle fitted through them (None when there
    are fewer than three, or they don't fix one).
    """

    e1: Array
    e2: Array
    points: Array
    spread: Array
    circle: CircleFit | None
    found: int

    def centre_along(self, along: Array) -> tuple[float, float] | None:
        """Where the circle's centre is along a direction (from the frame's origin), and how far that may be off; None without a circle."""
        if self.circle is None:
            return None
        x, y = float(fv.matmul(self.e1, along)), float(fv.matmul(self.e2, along))
        c = self.circle.centre
        return c[0] * x + c[1] * y, self.circle.uncertainty(x, y, 0.0)


def ring(
    spots: tuple[Spot, ...],
    plane: tuple[Vec | Array, Vec | Array],
    width: float,
    probe: Probe,
) -> Ring | str:
    """The copies' built centres in the plane, and the circle through them; or why one can't be found.

    A round copy's fitted axis gives both its coordinates from one fit. The
    circle's points may each be off along its radius, whichever way that
    runs, by the sum of how far they may be off along the plane's two axes.
    """
    e1, e2 = (np.asarray(v, dtype=np.float64) for v in plane)
    points, spread, found = [], [], 0
    for k, spot in enumerate(spots):
        if isinstance(spot.first, Centre) and spot.first == spot.second:
            fit = fitted_round(spot.first.round, width, probe)
            if isinstance(fit, str):
                return f"copy {k}: {fit}"
            points.append(
                (float(fv.matmul(fit.centre, e1)), float(fv.matmul(fit.centre, e2)))
            )
            spread.append((fit.uncertainty_along(e1), fit.uncertainty_along(e2)))
            found += fit.found
            continue
        along = []
        for ref, way in ((spot.first, e1), (spot.second, e2)):
            located = locate(ref, way, width, probe)
            if isinstance(located, str):
                return f"copy {k}: {located}"
            along.append(located)
        points.append((along[0][0], along[1][0]))
        spread.append((along[0][1], along[1][1]))
        found += along[0][2] + along[1][2]
    at, off = np.array(points), np.array(spread)
    circle = None
    if len(spots) >= 3:
        guess = at.mean(axis=0)
        radius = float(fv.norm(at - guess, axis=1).mean())
        circle = fit_circle(
            at, off.sum(axis=1), (float(guess[0]), float(guess[1])), radius
        )
    return Ring(e1, e2, at, off, circle, found)


@dataclass(frozen=True)
class Position:
    """The distance from ``reference`` to ``item`` along ``along``, less ``less`` (a boss's height from the axis of the rod it stands on: less the rod's radius)."""

    along: Vec
    reference: Ref
    item: Ref
    less: float = 0.0


def locate(
    ref: Ref, along: Array, width: float, probe: Probe
) -> tuple[float, float, int] | str:
    """Where the built thing is along ``along``, how far that may be off, and from how many points; or why it wasn't found."""
    if isinstance(ref, Plane):
        window, offset, u = plane_offset(ref, width, probe)
        if len(window) < FEWEST:
            return f"no built face within {width:.3g} mm of the spec's plane through {ref.point}"
        normal = np.asarray(ref.normal, dtype=np.float64)
        normal /= float(fv.norm(normal))
        at = float(fv.dot(ref.point, along)) + offset * float(fv.matmul(normal, along))
        return at, u * abs(float(fv.matmul(normal, along))), len(window)
    if isinstance(ref, Middle):
        a = locate(ref.a, along, width, probe)
        b = locate(ref.b, along, width, probe)
        if isinstance(a, str):
            return a
        if isinstance(b, str):
            return b
        return (a[0] + b[0]) / 2, (a[1] + b[1]) / 2, a[2] + b[2]
    if isinstance(ref, Mean):
        found_all = [locate(each, along, width, probe) for each in ref.each]
        for found_one in found_all:
            if isinstance(found_one, str):
                return found_one
        places = [f for f in found_all if not isinstance(f, str)]
        count = len(places)
        return (
            sum(f[0] for f in places) / count,
            sum(f[1] for f in places) / count,
            sum(f[2] for f in places),
        )
    if isinstance(ref, Hub):
        found_ring = ring(ref.each, ref.plane, width, probe)
        if isinstance(found_ring, str):
            return found_ring
        centre = found_ring.centre_along(along)
        if centre is None:
            return "the copies' centres don't fix a circle"
        return centre[0], centre[1], found_ring.found
    if isinstance(ref, ConeRim):
        cone = fitted_cone(ref.cone, width, probe)
        if isinstance(cone, str):
            return cone
        w, e1, e2 = cone.frame
        axis_point = np.asarray(ref.cone.centre, dtype=np.float64) + (
            cone.fit.centre[0] * e1 + cone.fit.centre[1] * e2
        )
        at = float(fv.matmul(axis_point, along))
        # The rim on that side: the axis and the radius there, as far across as ``along`` allows.
        across = float(np.sqrt(max(0.0, 1.0 - fv.sq(float(fv.matmul(w, along))))))
        if ref.sign:
            at += ref.sign * cone.fit.radius_at(ref.at)[0] * across
        u_cone = cone.fit.uncertainty(
            float(fv.matmul(e1, along)),
            float(fv.matmul(e2, along)),
            ref.sign * across,
            ref.at,
        )
        return at, u_cone, cone.found
    if isinstance(ref, BallCentre) or (
        isinstance(ref, RoundEdge) and isinstance(ref.round, Ball)
    ):
        ball_target = ref.ball if isinstance(ref, BallCentre) else ref.round
        assert isinstance(ball_target, Ball)
        ball = fitted_ball(ball_target, width, probe)
        if isinstance(ball, str):
            return ball
        at = float(fv.dot(ball.fit.centre, along))
        sign = ref.sign if isinstance(ref, RoundEdge) else 0.0
        at += sign * ball.fit.radius
        return at, ball.fit.uncertainty(along.tolist(), sign), ball.found
    assert isinstance(ref.round, Round)
    found = fitted_round(ref.round, width, probe)
    if isinstance(found, str):
        return found
    at = float(fv.matmul(found.centre, along))
    if not isinstance(ref, RoundEdge):
        return at, found.uncertainty_along(along), found.found
    # The edge on that side: the axis and the radius, as far across as ``along`` allows,
    # bounded as one (on a short arc the axis and the radius move together).
    across = ref.sign * float(
        np.sqrt(max(0.0, 1.0 - fv.sq(float(fv.matmul(found.axis, along)))))
    )
    at += found.fit.radius * across
    return at, found.uncertainty_along(along, across), found.found


def measure(
    target: Position, nominal: float, tolerance: Tolerance, probe: Probe
) -> Measurement:
    width = tolerance.band + 2 * float(probe.deflection.max(initial=0.0)) + 1e-3
    along = np.asarray(target.along, dtype=np.float64)
    along /= float(fv.norm(along))
    # Both located before either is judged missing, so a measurement taken again finer
    # where it looked looks at both (as size's two planes, generated part 2010).
    reference = locate(target.reference, along, width, probe)
    item = locate(target.item, along, width, probe)
    if isinstance(reference, str):
        return Measurement(None, 0, reference)
    if isinstance(item, str):
        return Measurement(None, reference[2], item)
    return Measurement.of(
        item[0] - reference[0] - target.less,
        item[1] + reference[1],
        item[2] + reference[2],
        f"from its reference to it, {item[2] + reference[2]} built points fitted",
    )


#: The item at each limit of the tolerance, ``2u`` inside (it must pass) and outside (it must fail).
mutants = bracket_mutants
