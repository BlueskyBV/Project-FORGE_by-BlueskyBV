"""The ``thread`` kind: a built thread held to the ISO 68-1 basic profile, at the turn it starts at (docs/definitions/thread.md).

Where a thread's helix starts round its axis is the build's to say, not the
spec's. So the built thread's points (every built point between the minor
and major cylinders over the threaded length, short of its ends) are each
put on the profile's own coordinate: ``u = (s - hand θ P / 2π - φ) mod P``,
``s`` along the axis and ``θ`` round it, and the turn ``φ`` that puts them
nearest the basic profile ``r(u)`` (a crest flat an eighth of the pitch
wide at the major radius, 60 degree flanks, a root flat a quarter wide at
5/8 of the sharp triangle's height in) is found: tried at every 1/720 of a
turn, then narrowed down.

- :class:`Profile`: how far the farthest built point is from the profile at
  that turn, along the radius. A plain rod, a wrong pitch or a wrong hand
  is far from it; the profile's own tolerance is ISO 2768-m on the thread's
  depth.
- :class:`Pitch`: the pitch that puts the points nearest the profile, found
  as the turn is, round the spec's.
- :class:`Hand`: the spec's hand must fit the profile, and better than the
  other hand.
- :class:`Length`: from the free end to where lines cast down the rod,
  half way into the thread's depth, last enter its material.

**Uncertainty:** the view's deflection, square to a flank, is a little more
along the radius (1/cos 30°); the pitch's, how far the best pitch can move
before the profile's misfit grows by that.

**Mutants and near-misses:** a plain rod, the other hand, a pitch a tenth
out (each must fail); the thread as asked (it must pass).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from ..classes import Tolerance, Verdict, bracket_mutants
from ..measure import FEWEST, Measurement, Probe, basis

__all__ = [
    "Hand",
    "Helix",
    "Length",
    "Pitch",
    "Profile",
    "measure",
    "mutants",
    "profile_radius",
]

Vec = tuple[float, float, float]
Array = NDArray[np.float64]

#: How many turns of the start are tried before narrowing down.
_TRIES = 720
#: A deflection square to a flank, along the radius.
_FLANK = 1 / math.cos(math.radians(30))


@dataclass(frozen=True)
class Helix:
    """A thread on the rod whose axis runs through ``centre`` along ``axis`` (towards its free end): ``radius`` its major radius, ``pitch``, ``hand`` (1 right, -1 left), over ``ends`` along the axis."""

    centre: Vec
    axis: Vec
    radius: float
    pitch: float
    hand: int
    ends: tuple[float, float]

    @property
    def depth(self) -> float:
        """The basic profile's depth: 5/8 of the sharp 60 degree triangle's height."""
        return 5 / 8 * math.sqrt(3) / 2 * self.pitch


@dataclass(frozen=True)
class Profile:
    helix: Helix


@dataclass(frozen=True)
class Pitch:
    helix: Helix


@dataclass(frozen=True)
class Hand:
    helix: Helix


@dataclass(frozen=True)
class Length:
    helix: Helix


def profile_radius(u: Array, radius: float, pitch: float) -> Array:
    """The basic profile's radius at ``u`` (0 to the pitch) from the middle of a crest."""
    off = np.minimum(u, pitch - u)
    deep = 5 / 8 * math.sqrt(3) / 2 * pitch
    return np.asarray(
        np.clip(radius - math.sqrt(3) * (off - pitch / 16), radius - deep, radius)
    )


@dataclass(frozen=True)
class _Points:
    s: Array
    theta: Array
    rho: Array
    deflection: float


def _points(helix: Helix, probe: Probe, margin: float) -> _Points | None:
    w, e1, e2 = basis(helix.axis)
    reach = 2 * float(probe.deflection.max(initial=0.0)) + 0.1 * helix.depth
    window = probe.band(
        helix.centre,
        helix.axis,
        (helix.radius - helix.depth - reach, helix.radius + reach),
        (helix.ends[0] + margin, helix.ends[1] - margin),
    )
    if len(window) < FEWEST * 10:
        return None
    d = window.points - np.asarray(helix.centre, dtype=np.float64)
    s = d @ w
    theta = np.arctan2(d @ e2, d @ e1)
    rho = np.sqrt((d @ e1) ** 2 + (d @ e2) ** 2)
    return _Points(s, theta, rho, float(window.deflection.max(initial=0.0)))


def _misfit(
    points: _Points, helix: Helix, pitch: float, hand: int, start: float
) -> Array:
    u = np.mod(points.s - hand * points.theta * pitch / (2 * math.pi) - start, pitch)
    return np.asarray(points.rho - profile_radius(u, helix.radius, pitch))


#: The points the turn and the pitch are searched with, at most (spread evenly through the window).
_SEARCHED = 20000


def _subset(points: _Points) -> _Points:
    if len(points.s) <= _SEARCHED:
        return points
    step = len(points.s) / _SEARCHED
    rows = (np.arange(_SEARCHED) * step).astype(np.int64)
    return _Points(
        points.s[rows], points.theta[rows], points.rho[rows], points.deflection
    )


def _farthest(
    points: _Points, helix: Helix, pitch: float, hand: int, start: float
) -> float:
    return float(np.abs(_misfit(points, helix, pitch, hand, start)).max())


def _coarse_start(
    points: _Points, helix: Helix, pitch: float, hand: int
) -> tuple[float, float]:
    """The turn, to 1/720 of the pitch, that puts the points nearest the profile: each point's phase binned, and every shift of the bins tried at once."""
    phase = np.mod(points.s - hand * points.theta * pitch / (2 * math.pi), pitch)
    bins = np.minimum((phase / pitch * _TRIES).astype(np.int64), _TRIES - 1)
    high = np.full(_TRIES, -np.inf)
    low = np.full(_TRIES, np.inf)
    np.maximum.at(high, bins, points.rho)
    np.minimum.at(low, bins, points.rho)
    held = np.flatnonzero(np.isfinite(high))
    centres = (held + 0.5) * pitch / _TRIES
    shifts = np.arange(_TRIES) * pitch / _TRIES
    profile = profile_radius(
        np.mod(centres[None, :] - shifts[:, None], pitch), helix.radius, pitch
    )
    worst = np.maximum(
        np.abs(high[held][None, :] - profile), np.abs(low[held][None, :] - profile)
    ).max(axis=1)
    k = int(np.argmin(worst))
    return float(shifts[k]), float(worst[k])


def _best_start(
    points: _Points, helix: Helix, pitch: float, hand: int
) -> tuple[float, float]:
    """The turn that puts the points nearest the profile, and the farthest point's distance from it then.

    Searched coarsely on a spread of the points (each one's phase binned),
    narrowed down on them by golden section, and the farthest of all the
    points measured at the turn found.
    """
    few = _subset(points)
    coarse, _ = _coarse_start(few, helix, pitch, hand)
    step = 2 * pitch / _TRIES
    lo, hi = coarse - step, coarse + step
    for _ in range(40):  # golden section on the farthest point's distance
        a = hi - (hi - lo) * 0.6180339887498949
        b = lo + (hi - lo) * 0.6180339887498949
        if _farthest(few, helix, pitch, hand, a) <= _farthest(
            few, helix, pitch, hand, b
        ):
            hi = b
        else:
            lo = a
    start = (lo + hi) / 2
    return start, _farthest(points, helix, pitch, hand, start)


def measure(
    target: Profile | Pitch | Hand | Length,
    nominal: float,
    tolerance: Tolerance | None,
    probe: Probe,
) -> Measurement:
    helix = target.helix
    margin = min(helix.pitch, (helix.ends[1] - helix.ends[0]) / 4)
    if isinstance(target, Length):
        return _length(helix, nominal, probe)
    points = _points(helix, probe, margin)
    if points is None:
        return Measurement(
            None,
            0,
            "no built thread between its minor and major cylinders",
            missing=True,
        )
    u_radial = points.deflection * _FLANK
    if isinstance(target, Profile):
        _, worst = _best_start(points, helix, helix.pitch, helix.hand)
        return Measurement.of(worst, u_radial, len(points.s),
                              f"{len(points.s)} built points, the farthest {worst:.3g} mm off the profile at its best turn")  # fmt: skip
    if isinstance(target, Hand):
        _, mine = _best_start(points, helix, helix.pitch, helix.hand)
        _, other = _best_start(points, helix, helix.pitch, -helix.hand)
        allowed = tolerance.plus if tolerance is not None else 0.1 * helix.depth
        reason = (
            f"its hand {mine:.3g} mm off the profile at best, the other {other:.3g}"
        )
        if mine + u_radial <= allowed and other > mine:
            verdict = Verdict.PASS
        elif mine - u_radial > allowed or other + u_radial < mine - u_radial:
            verdict = Verdict.FAIL
        else:
            verdict = Verdict.INCONCLUSIVE
        return Measurement(None, len(points.s), reason, verdict=verdict)
    return _pitch(points, helix, u_radial)


def _pitch(points: _Points, helix: Helix, u_radial: float) -> Measurement:
    """The pitch, round the spec's, whose best turn puts the points nearest the profile.

    Every pitch within a tenth of the spec's is tried coarsely; round the
    best, finely, each at its own best turn. The true pitch puts the points
    within their uncertainty of the profile, so it is among the pitches
    whose farthest point is within twice that of the best's: the measurement
    runs over them.
    """
    few = _subset(points)
    coarse = np.linspace(helix.pitch * 0.9, helix.pitch * 1.1, 81)
    rough = np.array(
        [_coarse_start(few, helix, float(p), helix.hand)[1] for p in coarse]
    )
    k = int(np.argmin(rough))
    if k in (0, len(coarse) - 1):
        return Measurement(
            None,
            len(points.s),
            "the best pitch is beyond a tenth of the spec's",
            missing=False,
        )
    step = float(coarse[1] - coarse[0])
    fine = np.linspace(coarse[k] - 2 * step, coarse[k] + 2 * step, 41)
    misfits = np.array([_best_start(few, helix, float(p), helix.hand)[1] for p in fine])
    best = int(np.argmin(misfits))
    good = fine[misfits <= misfits[best] + 2 * u_radial]
    tick = float(fine[1] - fine[0])
    lo, hi = float(good.min()) - tick, float(good.max()) + tick
    return Measurement.of((lo + hi) / 2, (hi - lo) / 2, len(points.s),
                          f"the pitches that fit {len(few.s)} built points within their uncertainty")  # fmt: skip


#: Lines cast along the rod to find where the thread starts.
_LINES = 64


def _length(helix: Helix, nominal: float, probe: Probe) -> Measurement:
    """From the free end to where the thread starts: lines cast down the rod half way into the thread's depth, from beyond its free end.

    Each line passes through teeth and grooves, and where the thread starts,
    into the rod's plain material for good. Where a groove is open there,
    the last time the line enters material is where the thread starts; the
    lines are spread round the rod, so half of them find it. They look two
    pitches past where it should start, but never past the rod's base
    (along the axis from the copy's point, where the rod stands): no thread
    starts there, and what the line meets beyond is the host's (generated
    part 423's boss, threaded all along, stands on a block a hole runs
    across, 1.3 mm past the boss's base: where a line came out of the hole
    into the block again, 2.3 mm past the base, was taken for where the
    thread starts).
    """
    w, e1, e2 = basis(helix.axis)
    whole = helix.ends[1]
    deflection = float(probe.deflection.max(initial=0.0))
    middle = helix.radius - helix.depth / 2
    above = 1.0 + helix.pitch
    u = 2 * deflection * _FLANK + helix.pitch / _LINES
    lowest = max(whole - nominal - 2 * helix.pitch, -u)
    for turn in range(8):
        angles = 2 * math.pi * (np.arange(_LINES) + turn / 8) / _LINES
        rings = middle * (np.cos(angles)[:, None] * e1 + np.sin(angles)[:, None] * e2)
        origins = (
            np.asarray(helix.centre, dtype=np.float64) + (whole + above) * w + rings
        )
        found = probe.view.crossings(origins, np.tile(-w, (_LINES, 1)))
        if found.grazed.any():
            continue
        s = whole + above - found.t
        keep = found.entering & (s >= lowest)
        if not keep.any():
            return Measurement(None, 0, "no thread found down the rod")
        starts = np.full(_LINES, np.inf)
        np.minimum.at(starts, found.ray[keep], s[keep])
        start = float(starts.min())
        length = whole - start
        return Measurement.of(
            length,
            u,
            _LINES,
            f"the thread starts {length:.4g} mm down from the free end",
        )
    return Measurement(None, 0, "every line down the rod grazed an edge", missing=False)


def mutants(
    nominal: float, tolerance: Tolerance | None, uncertainty: float
) -> tuple[tuple[float, Verdict], ...]:
    """A pitch or a length at its brackets; for the profile and the hand, its test builds the plain rod, the other hand and a wrong pitch."""
    if tolerance is None:
        return ()
    return bracket_mutants(nominal, tolerance, uncertainty)
