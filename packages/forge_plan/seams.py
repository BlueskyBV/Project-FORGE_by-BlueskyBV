"""Where a ball's or a cone's surface has its seam (and a ball its poles), as OpenCascade makes it: clear of what is on
it.

OpenCascade makes a ball about the frame's z, its surface's seam the
half-circle from pole to pole through +x; a cone about its axis, its side's
seam the line along it at the frame's first axis (``gp_Ax2``'s). Something
on the surface is joined to it, or cut into it, along a foot that follows
the same surface; one whose foot crosses the seam, or runs round a pole, is
joined across the seam's two edges, or round the pole's point, and
OpenCascade leaves the part holding only loosely, by millimetres, or
refuses it (generated parts 406, 660, 2270, 2276, 3005, 3295, 3932, 4031,
4989, 2626 and 2947: a boss, a post or a hole across a ball's seam or round
its pole; 476, 1073, 2288: by the pole; 644: a hole across a cone's seam).

A ball is the same ball turned about its centre, a cone the same cone
turned about its axis: where something on it comes within :data:`CLEAR` of
the seam or a pole, the planner makes it turned so that nothing does
(:func:`ball_motion`, :func:`cone_motion`); the ball or cone it cuts each
thing on it with is turned alike (``forge_plan.tools``), and a hollow's
inner ball. Where nothing on it comes so near, it is made as it always
was. Where something does, it is turned clear of everything; a ball cut
by a plane through its centre (a dome's flat face, the face a ball is
seated in) keeps its poles well out of that plane, and turns as little out
of its way up as that takes: kept up, the plane cuts it along one of its
own circles.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from forge_numeric import scalar as fs
from forge_spec.frames import Frame, Rigid
from forge_spec.geometry import reach

__all__ = ["CLEAR", "ball_motion", "cone_motion", "occ_first_axis"]

Vec = tuple[float, float, float]

#: How far clear of a seam and a pole what is on the surface keeps, on it (mm).
CLEAR = 1.0
#: The ways a ball's pole may be turned to (spread evenly over the ball), and the turns of its seam about each; the
#: turns of a cone about its axis.
_POLES, _SEAMS, _TURNS = 400, 36, 360
#: A ball cut by a plane through its centre keeps its poles at least this far (the sine of the angle) out of it.
_PLANE = 0.5


def _unit(v: Sequence[float]) -> Vec:
    n = fs.hypot(v[0], v[1], v[2])
    return (v[0] / n, v[1] / n, v[2] / n)


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Sequence[float], b: Sequence[float]) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _angle(c: float) -> float:
    return fs.acos(max(-1.0, min(1.0, c)))


def occ_first_axis(axis: Sequence[float]) -> Vec:
    """OpenCascade's own first axis for a frame about ``axis`` (``gp_Ax2(P, V)``'s): square to it, one of its
    coordinates nought. A cone's or a cylinder's side has its seam there."""
    a, b, c = axis
    aa, ba, ca = abs(a), abs(b), abs(c)
    if ba <= aa and ba <= ca:
        d = (-c, 0.0, a) if aa > ca else (c, 0.0, -a)
    elif aa <= ba and aa <= ca:
        d = (0.0, -c, b) if ba > ca else (0.0, c, -b)
    else:
        d = (-b, a, 0.0) if aa > ba else (b, -a, 0.0)
    return _unit(d)


def _on(ctx: Any, host: tuple[str, int, str]) -> list[tuple[Vec, float, Any]]:
    """What is on a surface (by its host): each copy's point, how far it reaches across the surface from it (its
    outline's reach, or the box round it where it has none), and the copy."""
    from forge_spec.items.solve import SOLVE

    found = []
    for item_id, copies in ctx.layout.instances.items():
        item = ctx.items.get(item_id)
        if item is None:
            continue
        for copy in copies:
            if copy.host != host:
                continue
            parts = SOLVE[item.kind].outline(item, ctx.layout, ("x", "y"))
            if parts:
                wide = reach(parts)
            else:
                lo, hi = copy.lo or copy.origin, copy.hi or copy.origin
                wide = fs.hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]) / 2.0
            found.append((copy.origin, wide, copy))
    return found


def _clearance(on: Sequence[tuple[Vec, float]], pole: Vec, seam: Vec) -> float:
    """The least, over what is on a ball (each its way from the centre and how far round the surface it reaches, as an
    angle), of how far it keeps from either pole and from the seam (the half-circle from pole to pole through
    ``seam``), as an angle."""
    third = _cross(pole, seam)
    least = math.inf
    for d, spread in on:
        a, x, y = _dot(d, pole), _dot(d, seam), _dot(d, third)
        poles = min(_angle(a), _angle(-a))
        along = fs.asin(min(1.0, abs(y))) if x >= 0.0 else poles  # nearest the seam's half, or one of its ends
        least = min(least, min(poles, along) - spread)
    return least


def _candidates(up: Vec | None) -> list[tuple[Vec, Vec]]:
    """Its own way up and down where a plane square to ``up`` cuts it, and poles spread evenly over the ball (a
    Fibonacci lattice), each with its seam turned evenly about it; only poles well out of the plane."""
    found = []
    golden = math.pi * (3.0 - math.sqrt(5.0))  # the golden angle
    poles: list[Vec] = [] if up is None else [up, (-up[0], -up[1], -up[2])]  # its seam turned about its way up first
    for k in range(_POLES):
        z = 1.0 - (2.0 * k + 1.0) / _POLES
        r = math.sqrt(max(1.0 - z * z, 0.0))
        s, c = fs.sincos(golden * k)
        poles.append((r * c, r * s, z))
    for pole in poles:
        if up is not None and abs(_dot(pole, up)) < _PLANE:
            continue
        helper = (1.0, 0.0, 0.0) if abs(pole[0]) < 0.9 else (0.0, 1.0, 0.0)
        e1 = _unit(_cross(helper, pole))
        e2 = _cross(pole, e1)
        for j in range(_SEAMS):
            s, c = fs.sincos(2.0 * math.pi * j / _SEAMS)
            found.append((pole, (c * e1[0] + s * e2[0], c * e1[1] + s * e2[1], c * e1[2] + s * e2[2])))
    return found


def ball_motion(ctx: Any, ball: str, index: int, centre: Vec, radius: float, up: Vec | None = None) -> Rigid | None:
    """The turn about a ball's centre it is made with (see the module): None where what is on its surface keeps
    :data:`CLEAR` of its seam and its poles as OpenCascade makes it, or nothing is on it. ``up``: the way it stands,
    where a plane through its centre square to it cuts it (a dome's flat face; the face it is seated in)."""
    on = [(_unit((p[0] - centre[0], p[1] - centre[1], p[2] - centre[2])), fs.asin(min(1.0, (wide + CLEAR) / radius)))
          for p, wide, _ in _on(ctx, (ball, index, "surface"))]  # fmt: skip
    if not on or _clearance(on, (0.0, 0.0, 1.0), (1.0, 0.0, 0.0)) >= 0.0:
        return None
    least = _clearance(on, (0.0, 0.0, 1.0), (1.0, 0.0, 0.0))
    best: tuple[bool, float, float] | None = None
    chosen = None
    for pole, seam in _candidates(up):
        found = _clearance(on, pole, seam)
        # Clear of everything first; then as little out of its way up as that takes (where a plane cuts it, along one
        # of its own circles where it stays up); then the most clear.
        key = (found >= 0.0, abs(_dot(pole, up)) if up is not None and found >= 0.0 else 0.0, found)
        if best is None or key > best:
            best, chosen = key, (pole, seam)
    if chosen is None or best is None or best[2] <= least:
        return None
    pole, seam = chosen
    return Rigid.between(Frame(centre, (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
                         Frame(centre, seam, _cross(pole, seam), pole))  # fmt: skip


def cone_motion(ctx: Any, cone: str, index: int, base: Vec, axis: Vec, radius: float) -> Rigid | None:
    """The turn about a cone's axis it is made with (see the module): None where what is on its side keeps
    :data:`CLEAR` of its seam as OpenCascade makes it, or nothing is on it. ``radius``: its side's least radius, which
    an angle round it is measured on."""
    x = occ_first_axis(axis)
    y = _cross(axis, x)
    on = []
    for p, wide, _ in _on(ctx, (cone, index, "side")):
        d = (p[0] - base[0], p[1] - base[1], p[2] - base[2])
        along = _dot(d, axis)
        r = (d[0] - along * axis[0], d[1] - along * axis[1], d[2] - along * axis[2])
        rho = max(fs.hypot(r[0], r[1], r[2]), radius, 1e-9)
        on.append((fs.atan2(_dot(r, y), _dot(r, x)), min(math.pi, (wide + CLEAR) / rho)))
    if not on:
        return None

    def clear(turn: float) -> float:
        least = math.inf
        for angle, spread in on:
            apart = abs(math.remainder(angle - turn, 2.0 * math.pi))
            least = min(least, apart - spread)
        return least

    if clear(0.0) >= 0.0:
        return None
    best, chosen = clear(0.0), 0.0
    for k in range(1, _TURNS):
        turn = 2.0 * math.pi * k / _TURNS
        found = clear(turn)
        if found > best:
            best, chosen = found, turn
    if chosen == 0.0:
        return None
    s, c = fs.sincos(chosen)
    return Rigid.turn_about(base, axis, c, s)
