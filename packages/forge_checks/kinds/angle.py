"""The ``angle`` kind: a cone's full angle (a countersink's), or where copies are round a line.

**A cone** (:class:`~forge_checks.kinds.surfaces.Cone`): a cone fitted
about the spec's axis to the built points near it; its full angle, twice
the angle of its side to the axis.

**Round a line** (:class:`Turns`): items at angles round a round side's axis
(the side's fitted axis), or a circle's or an arc's copies round their
centre on a flat face (the centre of the circle fitted through their axes),
seen along the line, from its 0 degree direction towards its 90. Each copy
is where its fitted axis is (it runs out along the radius round a side, or
along the line on a flat face), or, for a post round a side, the middle of
its two fitted sides square to the way round. What is measured is the
start (the first copy's angle, or, for a circle, each copy's less its steps
from the first, as the start places them all) or the step (from each copy
to the next).

**Tolerance policy:** an angle: its own tolerance, or ISO 2768-m by the
length of the angle's shorter side (the cone's slant length; for copies
round a line, their distance from it, or a post's size round the side).

**Uncertainty:** the fits', as an angle: how far each copy's axis may be off
across the way to it from the line, and the line's own, over the distance
between them.

**Mutants and near-misses:** the angle at each limit of the tolerance,
``2u`` outside (it must fail) and ``2u`` inside (it must pass).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from ..classes import Tolerance, bracket_mutants, general
from ..measure import Measurement, Probe, basis, fit_circle, fit_cone
from .position import Centre, Middle, Spot, locate, ring
from .surfaces import Cone, Round, _margin, fitted_cone, fitted_round, width_for

__all__ = ["Turns", "measure", "mesh_deflection", "mutants"]

Vec = tuple[float, float, float]
Array = NDArray[np.float64]


@dataclass(frozen=True)
class Turns:
    """Where copies are round the line through ``centre`` along ``axis``, in degrees from ``zero`` towards ``axis`` x ``zero``.

    Round a side, the line as built is ``hub``'s fitted axis, and each copy
    is a round surface (its fitted axis) or the middle of a post's two sides
    square to the way round (two planes), seen from ``reach`` out. On a flat
    face (no hub), each copy is its built centre in the face's plane
    (:class:`~forge_checks.kinds.position.Spot`), and the line is the centre
    of the circle fitted through them (at least three), ``reach`` across.

    ``first`` is copy 0's nominal angle and ``spacing`` the nominal angle
    from each copy to the next. With ``step`` False the start is measured:
    each of the ``told`` copies' angles less its steps from the first (all
    of a circle's copies give its start; an arc's first alone does, its
    others being where its step puts them). With ``step`` True, the angle
    from each copy to the next.
    """

    centre: Vec
    axis: Vec
    zero: Vec
    copies: tuple[Round | Middle | Spot, ...]
    hub: Round | None
    first: float
    spacing: float
    step: bool = False
    told: tuple[int, ...] = (0,)
    reach: float = 0.0


def _near(angle: float, expected: float) -> float:
    """The turn of ``angle`` nearest ``expected``."""
    return expected + ((angle - expected + 180.0) % 360.0 - 180.0)


def _cone(target: Cone, tolerance: Tolerance, probe: Probe) -> Measurement:
    deflection = float(probe.deflection.max(initial=0.0))
    (r0, r1), (s0, s1) = target.radii, target.ends
    slant = math.hypot(r1 - r0, s1 - s0)
    # The band, as how far the cone's far end moves square to it.
    width = (
        2 * slant * math.tan(math.radians(min(tolerance.band, 60.0)))
        + 2 * deflection
        + 1e-3
    )
    cone = fitted_cone(target, width, probe)
    if isinstance(cone, str):
        return Measurement(None, 0, cone, missing=cone.startswith("no built"))
    b = cone.fit.b
    angle = math.degrees(2 * math.atan(abs(b)))
    u = math.degrees(2 * cone.fit.u_b / (1 + b * b))
    return Measurement.of(
        angle, u, cone.found, f"a cone fitted to {cone.found} built points"
    )


#: Points round and along a cone its sensitivity to deflection is read off (:func:`mesh_deflection`).
_ROUND, _ALONG = 64, 32
#: How far the needed deflection is kept below the one that would just do: a mesh's points lie otherwise.
_ROOM = 2.0


def mesh_deflection(target: Cone, tolerance: Tolerance) -> float:
    """The most a mesh may stray from the cone (mm) for its angle to be measured fine enough on the mesh's points (an eighth of the band; :func:`~forge_checks.classes.fine_enough`), with room.

    The fit's slope is uncertain by the sum of its weights' sizes times
    the points' deflection: read off the weights of a fit to points on the
    spec's cone itself, spread over the stretch of it the measurement takes
    (short of its ends by the same margin), the angle's uncertainty per
    millimetre of deflection.
    """
    (r0, r1), (s0, s1) = target.radii, target.ends
    # No length along its axis: no cone to fit, and nothing it asks of a mesh.
    if s1 == s0:
        return math.inf
    slant = math.hypot(r1 - r0, s1 - s0)
    width = 2 * slant * math.tan(math.radians(min(tolerance.band, 60.0))) + 1e-3
    margin = _margin(width, s1 - s0)
    slope = (r1 - r0) / (s1 - s0)
    s = np.repeat(np.linspace(s0 + margin, s1 - margin, _ALONG), _ROUND)
    turn = np.tile(np.linspace(0.0, 2 * math.pi, _ROUND, endpoint=False), _ALONG)
    r = r0 + slope * (s - s0)
    across = np.stack([r * np.cos(turn), r * np.sin(turn)], axis=1)
    unit = 1e-6  # small enough that the second-order term is nothing beside the first
    fit = fit_cone(across, s, np.full(len(s), unit), r0 - slope * s0, slope)
    if fit is None:
        return math.inf
    per_mm = math.degrees(2 * fit.u_b / (1 + fit.b * fit.b)) / unit
    return tolerance.band / 8 / per_mm / _ROOM


def _missing(reason: str, found: int) -> Measurement:
    return Measurement(None, found, reason, missing="no built" in reason)


def _turns(target: Turns, tolerance: Tolerance, probe: Probe) -> Measurement:
    deflection = float(probe.deflection.max(initial=0.0))
    w, _, _ = basis(target.axis)
    zero = np.asarray(target.zero, dtype=np.float64)
    zero = zero - (zero @ w) * w
    zero /= float(np.linalg.norm(zero))
    quarter = np.asarray(np.cross(w, zero), dtype=np.float64)
    centre = np.asarray(target.centre, dtype=np.float64)
    # How far a copy moves at the tolerance's angles, from its place.
    rounds = [c for c in target.copies if isinstance(c, Round)]
    rounds += [
        c.first.round
        for c in target.copies
        if isinstance(c, Spot) and isinstance(c.first, Centre)
    ]
    farthest = max(
        [target.reach]
        + [
            float(np.linalg.norm(np.cross(np.asarray(c.centre) - centre, w)))
            for c in rounds
        ]
    )
    moved = farthest * math.tan(math.radians(min(tolerance.band, 60.0)))
    width = width_for(Tolerance(moved, moved), deflection)
    width += min((c.radius for c in rounds), default=0.0) / 4

    if target.hub is None:
        # On a flat face: round the circle through the copies' built centres.
        spots = tuple(c for c in target.copies if isinstance(c, Spot))
        if len(spots) != len(
            target.copies
        ):  # pragma: no cover - the compiler gives spots on a flat face
            raise ValueError(
                "copies round a circle on a flat face are their built centres"
            )
        built = ring(spots, (zero, quarter), width, probe)
        if isinstance(built, str):
            return _missing(built, 0)
        spans = _round_ring(target, built.points, built.spread)
        if isinstance(spans, str):
            return Measurement(None, built.found, spans, missing=False)
        return _spanned(target, spans, built.found)

    # Round a side: round its fitted axis.
    hub = fitted_round(
        target.hub, width_for(general(2 * target.hub.radius), deflection), probe
    )
    if isinstance(hub, str):
        return _missing(f"the side: {hub}", 0)
    line = np.array([float(hub.centre @ zero), float(hub.centre @ quarter)])
    u_line = np.array([hub.uncertainty_along(zero), hub.uncertainty_along(quarter)])
    found = hub.found
    angles: list[tuple[float, float]] = []
    for k, copy in enumerate(target.copies):
        expected = target.first + k * target.spacing
        if isinstance(copy, Middle):
            # A post's middle, how far across the way round from the line, seen from its reach out.
            turn = math.radians(expected)
            way = math.cos(turn) * quarter - math.sin(turn) * zero
            located = locate(copy, way, width, probe)
            if isinstance(located, str):
                return _missing(f"copy {k}: {located}", found)
            at, u_at, count = located
            across = at - float(
                line @ np.array([float(zero @ way), float(quarter @ way)])
            )
            u_across = (
                u_at
                + abs(float(zero @ way)) * float(u_line[0])
                + abs(float(quarter @ way)) * float(u_line[1])
            )
            angles.append((expected + math.degrees(math.atan2(across, target.reach)),
                           math.degrees(u_across / target.reach)))  # fmt: skip
            found += count
            continue
        if not isinstance(
            copy, Round
        ):  # pragma: no cover - the compiler gives round copies or posts' sides here
            raise ValueError(
                "round a side, a copy is a round surface or a post's two sides"
            )
        fit = fitted_round(copy, width, probe)
        if isinstance(fit, str):
            return _missing(f"copy {k}: {fit}", found)
        found += fit.found
        x = float(fit.centre @ zero) - float(line[0])
        y = float(fit.centre @ quarter) - float(line[1])
        ux = fit.uncertainty_along(zero) + float(u_line[0])
        uy = fit.uncertainty_along(quarter) + float(u_line[1])
        reach = math.hypot(x, y)
        if reach == 0:
            return Measurement(
                None,
                found,
                f"copy {k} is on the line: it has no angle round it",
                missing=False,
            )
        angle = _near(math.degrees(math.atan2(y, x)), expected)
        angles.append(
            (angle, math.degrees((abs(y) * ux + abs(x) * uy) / (reach * reach)))
        )

    if target.step:
        spans = [
            (angles[k + 1][0] - angles[k][0], angles[k][1] + angles[k + 1][1])
            for k in range(len(angles) - 1)
        ]
    else:
        spans = [(angles[k][0] - k * target.spacing, angles[k][1]) for k in target.told]
    return _spanned(target, spans, found)


def _values(target: Turns, points: Array) -> Array | None:
    """The start's estimates (each told copy's angle less its steps) or the steps, round the circle through ``points``; None if they fix no circle."""
    guess = points.mean(axis=0)
    radius = float(np.linalg.norm(points - guess, axis=1).mean())
    circle = fit_circle(
        points, np.zeros(len(points)), (float(guess[0]), float(guess[1])), radius
    )
    if circle is None:
        return None
    d = points - np.asarray(circle.centre)
    angles = [
        _near(
            math.degrees(math.atan2(float(y), float(x))),
            target.first + k * target.spacing,
        )
        for k, (x, y) in enumerate(d)
    ]
    if target.step:
        return np.array([angles[k + 1] - angles[k] for k in range(len(angles) - 1)])
    return np.array([angles[k] - k * target.spacing for k in target.told])


def _round_ring(
    target: Turns, points: Array, spread: Array
) -> list[tuple[float, float]] | str:
    """The start's estimates or the steps round the circle through the copies' built centres, each with how far it may be off.

    The circle's centre moves with every copy's centre, so each value may be
    off by the first-order worst case over every copy's own error along each
    axis (how fast the value changes with it, found by moving it a little and
    fitting again, times how far it may be off), not by the angles' errors
    added as if the centre moved with each copy alone.
    """
    base = _values(target, points)
    if base is None:
        return "the copies' centres don't fix a circle"
    h = 1e-6 * max(1.0, float(np.abs(points).max()))
    u = np.zeros(len(base))
    for j in range(len(points)):
        for axis in (0, 1):
            moved = points.copy()
            moved[j, axis] += h
            changed = _values(target, moved)
            if (
                changed is None
            ):  # pragma: no cover - a hair's move fixes the same circle
                return "the copies' centres don't fix a circle"
            u += np.abs((changed - base) / h) * float(spread[j, axis])
    return [(float(v), float(e)) for v, e in zip(base, u, strict=True)]


def _spanned(
    target: Turns, spans: list[tuple[float, float]], found: int
) -> Measurement:
    """Every estimate at once, from the least to the greatest: each must be within the tolerance."""
    if target.step:
        what = f"{len(spans)} steps between built copies"
    elif len(spans) == 1:
        what = "the first copy's angle"
    else:
        what = f"{len(spans)} copies' angles, less their steps"
    lo = min(v - u for v, u in spans)
    hi = max(v + u for v, u in spans)
    line = (
        "the side's fitted axis"
        if target.hub is not None
        else "the circle through them"
    )
    return Measurement.of((lo + hi) / 2, (hi - lo) / 2, found, f"{what}, round {line}")


def measure(
    target: Cone | Turns, nominal: float, tolerance: Tolerance, probe: Probe
) -> Measurement:
    if isinstance(target, Cone):
        return _cone(target, tolerance, probe)
    return _turns(target, tolerance, probe)


#: The angle at each limit of the tolerance, ``2u`` inside (it must pass) and outside (it must fail).
mutants = bracket_mutants
