"""The surfaces the check kinds measure, and how each is found and fitted on a built part.

Each is a surface the spec asks for, placed by the judge's own placement:

- :class:`Plane`: a flat face, through a point, facing out of the material,
  within a reach of the point (a floor or a boss's top is a small part of a
  larger plane);
- :class:`Round`: a round surface (a bore, a boss, a rod, a pocket's
  corner, a fillet along a straight edge);
- :class:`Ball`: a ball's surface (a sphere, a dome);
- :class:`Cone`: a cone (a countersink, a cone's side, a chamfer round a
  round edge);
- :class:`Tube`: an arc of a torus's tube (a fillet round a round edge).

Each is found on the built part as the built points within a width of it
(:class:`~forge_checks.measure.Probe`), and fitted with the uncertainty of
:mod:`forge_checks.measure`. The width is the check's tolerance band both
ways and the view's deflection twice (:func:`width_for`): a surface built
off by more isn't found, and the spec's surface is missing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np
from forge_numeric import vector as fv
from numpy.typing import NDArray

from ..classes import Tolerance
from ..measure import (
    FEWEST,
    CircleFit,
    ConeFit,
    Probe,
    SphereFit,
    Window,
    basis,
    fit_circle,
    fit_cone,
    fit_offset,
    fit_sphere,
)

__all__ = [
    "Ball",
    "Cone",
    "FittedBall",
    "FittedCone",
    "FittedRound",
    "Plane",
    "Round",
    "Tube",
    "fitted_ball",
    "fitted_cone",
    "fitted_round",
    "fitted_tube",
    "plane_offset",
    "width_for",
]

Vec = tuple[float, float, float]
Array = NDArray[np.float64]


@dataclass(frozen=True)
class Plane:
    """A flat face the spec asks for: through ``point``, facing ``normal`` (out of the material); where the spec has it, within ``reach`` of ``point``, or, given ``half``, within the rectangle round ``point`` whose sides run along ``first`` (``half[0]`` each way) and along ``normal`` x ``first`` (``half[1]``).

    A rectangle is a floor's or a wall's own outline (round its corners), so
    the built points looked for are wherever it is built, however much of it
    something else has cut away, and nothing beside it that lies in its
    plane is.
    """

    point: Vec
    normal: Vec
    reach: float = math.inf
    first: Vec | None = None
    half: tuple[float, float] | None = None

    def __post_init__(self) -> None:
        if (self.first is None) != (self.half is None):
            raise ValueError(
                "a plane's rectangle has both its first side and its half sizes"
            )
        if self.first is not None and self.half is not None:
            n = np.asarray(self.normal, dtype=np.float64)
            f = np.asarray(self.first, dtype=np.float64)
            if abs(float(fv.matmul(n, f))) > 1e-9 * float(fv.norm(n) * fv.norm(f)):
                raise ValueError(
                    f"a plane's rectangle lies in it: {self.first} isn't square to {self.normal}"
                )
            if not min(self.half) > 0:
                raise ValueError(f"a plane's rectangle has some size: {self.half}")

    def box(self) -> tuple[Vec, float, float] | None:
        """Its rectangle as :meth:`~forge_checks.measure.Probe.flat` takes it, if it has one."""
        if self.first is None or self.half is None:
            return None
        return self.first, self.half[0], self.half[1]


@dataclass(frozen=True)
class Round:
    """A round surface: ``radius`` about the line through ``centre`` along ``axis``, from ``start`` to ``end`` along it.

    ``inside``: the material is outside it (a bore), so it faces the axis.
    """

    centre: Vec
    axis: Vec
    radius: float
    start: float
    end: float
    inside: bool


@dataclass(frozen=True)
class Ball:
    """A ball's surface: ``radius`` about ``centre`` (where the spec has it: all of it, or a dome's).

    ``inside``: the material is outside it (a hollow ball's inside), so it faces the centre.
    """

    centre: Vec
    radius: float
    inside: bool = False


@dataclass(frozen=True)
class Cone:
    """A cone: about the line through ``centre`` along ``axis``, radius ``radii[0]`` at ``ends[0]`` along it to ``radii[1]`` at ``ends[1]``.

    ``inside``: the material is outside it (a countersink), so it faces the axis.
    """

    centre: Vec
    axis: Vec
    radii: tuple[float, float]
    ends: tuple[float, float]
    inside: bool


@dataclass(frozen=True)
class Tube:
    """An arc of a torus's tube: ``radius`` about the circle of radius ``big`` round the line through ``centre`` along ``axis``, over ``arc`` (radians round the tube, from the way out from the axis towards ``axis``).

    ``inside``: the material is outside the tube (a fillet filling an inside corner).
    """

    centre: Vec
    axis: Vec
    big: float
    radius: float
    arc: tuple[float, float]
    inside: bool


def width_for(tolerance: Tolerance, deflection: float) -> float:
    """How far from the spec's surface a built point is looked for: the band both ways, and the deflection twice."""
    return tolerance.band + 2 * deflection + 1e-3


def plane_offset(
    plane: Plane, width: float, probe: Probe
) -> tuple[Window, float, float]:
    """The built points near a spec plane, how far along its normal they lie on average, and how far that may be off (NaN if too few)."""
    window = probe.flat(
        plane.point, plane.normal, width=width, reach=plane.reach, box=plane.box()
    )
    if len(window) < FEWEST:
        return window, math.nan, math.nan
    offset, uncertainty = fit_offset(window, plane.point, plane.normal)
    return window, offset, uncertainty


@dataclass(frozen=True, eq=False)
class FittedRound:
    """A round surface as built: a circle fitted across the spec's axis to the built points near it (``window``)."""

    fit: CircleFit
    centre: Array  # the fitted axis's point in the plane of the spec's centre
    e1: Array
    e2: Array
    axis: Array
    found: int
    window: Window

    def uncertainty_along(self, along: Array, radius: float = 0.0) -> float:
        """How far the fitted axis may be off along a direction; with ``radius``, its place there plus that many times the fitted radius (an edge's: ``radius`` is how far across the axis ``along`` runs, signed)."""
        return self.fit.uncertainty(
            float(fv.matmul(self.e1, along)), float(fv.matmul(self.e2, along)), radius
        )


def _straight(points: Array, deflection: Array, most: float) -> bool:
    """Whether points in a plane lie on a line where an arc of radius up to ``most`` through them would bend away from it measurably.

    An arc over the points' span strays from its chord by its sagitta; a
    circle no bigger than ``most`` would put points (each off by up to its
    deflection) farther from their best line than these are. So the
    surface they are on isn't round, or rounds far more gently than asked.
    """
    centre = points.mean(axis=0)
    rel = points - centre
    # The directions they spread most and next most along (their signs don't matter here).
    _, vectors = fv.eigh(fv.matmul(rel.T, rel))
    along = fv.matmul(rel, vectors[:, -1])
    off = fv.matmul(rel, vectors[:, -2])
    half = float(along.max() - along.min()) / 2
    if half <= 0:
        return False
    sag = most if half >= most else most - math.sqrt(most * most - half * half)
    return sag > 2 * (float(np.abs(off).max()) + float(deflection.max(initial=0.0)))


def _margin(width: float, length: float) -> float:
    """How far short of a surface's ends its points are taken: the width, but no more than a quarter of its length."""
    return min(width, length / 4)


def fitted_round(target: Round, width: float, probe: Probe) -> FittedRound | str:
    """The round surface as built, or why it can't be measured ("no built ..." when it isn't there)."""
    margin = _margin(width, target.end - target.start)
    window = probe.round(
        target.centre,
        target.axis,
        target.radius,
        target.start + margin,
        target.end - margin,
        inside=target.inside,
        width=width,
    )
    if len(window) < FEWEST:
        return f"no built round surface within {width:.3g} mm of the spec's"
    w, e1, e2 = basis(target.axis)
    c = np.asarray(target.centre, dtype=np.float64)
    d = window.points - c
    flat = np.stack([fv.matmul(d, e1), fv.matmul(d, e2)], axis=1)
    fit = fit_circle(flat, window.deflection, (0.0, 0.0), target.radius)
    if fit is None:
        if _straight(flat, window.deflection, target.radius + width):
            return "no built round surface: the built points there lie on a line"
        return "the built points don't fix a circle"
    return FittedRound(
        fit,
        c + fit.centre[0] * e1 + fit.centre[1] * e2,
        e1,
        e2,
        w,
        len(window),
        window,
    )


@dataclass(frozen=True, eq=False)
class FittedBall:
    """A ball's surface as built: a sphere fitted to the built points near it (``window``)."""

    fit: SphereFit
    found: int
    window: Window


def fitted_ball(target: Ball, width: float, probe: Probe) -> FittedBall | str:
    """The ball's surface as built, or why it can't be measured ("no built ..." when it isn't there)."""
    window = probe.ball(target.centre, target.radius, width=width, inside=target.inside)
    if len(window) < FEWEST + 1:
        return f"no built ball surface within {width:.3g} mm of the spec's"
    fit = fit_sphere(window.points, window.deflection, target.centre, target.radius)
    if fit is None:
        return "the built points don't fix a sphere"
    return FittedBall(fit, len(window), window)


@dataclass(frozen=True)
class FittedCone:
    """A cone as built: fitted about the spec's axis to the built points near it (``frame``: the axis and the two across it, as the fit's centre is given in)."""

    fit: ConeFit
    found: int
    frame: tuple[Array, Array, Array]


def fitted_cone(target: Cone, width: float, probe: Probe) -> FittedCone | str:
    """The cone as built, or why it can't be measured ("no built ..." when it isn't there)."""
    (r0, r1), (s0, s1) = target.radii, target.ends
    margin = _margin(width, s1 - s0)
    slope = (r1 - r0) / (s1 - s0)
    ends = (s0 + margin, s1 - margin)
    radii = (r0 + slope * margin, r1 - slope * margin)
    window = probe.turned(
        target.centre, target.axis, radii, ends, inside=target.inside, width=width
    )
    if len(window) < FEWEST + 1:
        return f"no built cone within {width:.3g} mm of the spec's"
    w, e1, e2 = basis(target.axis)
    d = window.points - np.asarray(target.centre, dtype=np.float64)
    # Fitted about the middle of its stretch, where its points are (ConeFit.at).
    middle = (s0 + s1) / 2
    fit = fit_cone(
        np.stack([fv.matmul(d, e1), fv.matmul(d, e2)], axis=1),
        fv.matmul(d, w) - middle,
        window.deflection,
        r0 + slope * (middle - s0),
        slope,
    )
    if fit is None:
        return "the built points don't fix a cone"
    return FittedCone(replace(fit, at=middle), len(window), (w, e1, e2))


@dataclass(frozen=True)
class FittedTube:
    """A torus's tube as built: a circle fitted, in the half-plane round the spec's axis, to the built points near it."""

    fit: CircleFit
    found: int


def fitted_tube(target: Tube, width: float, probe: Probe) -> FittedTube | str:
    """The tube as built, or why it can't be measured ("no built ..." when it isn't there)."""
    window = probe.tube(
        target.centre,
        target.axis,
        target.big,
        target.radius,
        target.arc,
        inside=target.inside,
        width=width,
    )
    if len(window) < FEWEST:
        return f"no built rounding within {width:.3g} mm of the spec's"
    w, _, _ = basis(target.axis)
    d = window.points - np.asarray(target.centre, dtype=np.float64)
    along = fv.matmul(d, w)
    radial = d - along[:, None] * w
    rho = np.sqrt(fv.dot(radial, radial))
    section = np.stack([rho, along], axis=1)
    fit = fit_circle(section, window.deflection, (target.big, 0.0), target.radius)
    if fit is None:
        if _straight(section, window.deflection, target.radius + width):
            return "no built rounding: the built points there lie on a line"
        return "the built points don't fix a circle round the tube"

    return FittedTube(fit, len(window))
