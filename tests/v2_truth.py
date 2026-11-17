"""Generated parts built as meshes: the generator's truth (forge_eval.truth), made with manifold3d.

Each step's solid is made as a fine polygon whose every vertex lies on the
true surface, as an exporter makes one: every round edge split into as many
sides as keep each side within :data:`SAG` of its arc (a power of two of
them, at least 64), so the whole mesh is within one small deflection of the
true part (:func:`deflection`), whatever the size of its round edges. Each
solid is carried on past its ends as far as its step allows (into air a cut
opens onto, into what a standing item is joined to), so no two solids meet
in one plane, and added or taken away in order. Forge itself never uses
manifold3d: these are reference parts, depending on neither the solver nor
the judge's placement or oracle.

A disc's vertices are half a step round from its axes, and so are a
rounded corner's (its quarter-circle's ends, where it meets the sides
along it, are no vertices: an edge runs from its last one to the next
corner, within the sag of the line it stands for), and a frustum's a
quarter step: with a power of two of sides, no vertex lies at an angle the
generator uses (a whole half degree), nor where a corner's rounding meets
the face a round-ended tab stands on, so no vertex of one solid meets
another's face or edge, which makes no clean mesh.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

import numpy as np
from forge_eval.truth import (
    QUADRANTS,
    Corner,
    Frustum,
    Kept,
    Letters,
    Outline2,
    Prism,
    Pushed,
    RingCorner,
    Step,
    Threaded,
    Truth,
    Turned,
    line_contours,
)
from numpy.typing import NDArray
from v2_meshes import exported, origins
from v2_reference import OVERLAP, THREAD_DEFLECTION, m3, swept

Array = NDArray[np.float64]

#: How far each side of a round edge's polygon may be from its arc (mm).
SAG = 0.0004


def sides(radius: float, sag: float = SAG) -> int:
    """How many sides a round edge of this radius is split into: a power of two, at least 64, each within ``sag`` of its arc."""
    if radius <= sag:
        return 64
    needed = math.pi / math.acos(1 - sag / radius)
    return max(64, int(2 ** math.ceil(math.log2(needed))))


def _sag(radius: float, sag: float = SAG) -> float:
    return radius * (1 - math.cos(math.pi / sides(radius, sag)))


def _outline(
    prism: Prism, rounded: tuple[bool, ...], sag: float = SAG
) -> list[tuple[float, float]]:
    """The prism's outline in its own plane, counter-clockwise: a rectangle with its ``rounded`` corners rounded (in the order of :data:`~forge_eval.truth.QUADRANTS`), as a polygon whose vertices lie on the true outline."""
    h1, h2 = prism.half
    r = prism.corner
    if r >= h1 and r >= h2 and all(rounded):
        n = sides(r, sag)
        return [
            (
                r * math.cos(2 * math.pi * (k + 0.5) / n),
                r * math.sin(2 * math.pi * (k + 0.5) / n),
            )
            for k in range(n)
        ]
    quarter = sides(r, sag) // 4
    points: list[tuple[float, float]] = []
    for k, ((q1, q2), on) in enumerate(zip(QUADRANTS, rounded, strict=True)):
        if not on or r <= 0:
            p = (q1 * h1, q2 * h2)
            if not points or math.dist(points[-1], p) > 1e-9:
                points.append(p)
            continue
        cx, cy = q1 * (h1 - r), q2 * (h2 - r)
        for j in range(quarter):
            a = math.pi / 2 * (k + (j + 0.5) / quarter)
            points.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    if math.dist(points[0], points[-1]) <= 1e-9:
        points.pop()
    return points


def _polygon(outline: Outline2, sag: float = SAG) -> list[tuple[float, float]]:
    """An outline of sides and arcs as a polygon whose vertices lie on it: each arc in as many pieces as keep each within ``sag`` of it (its corners on the arc, as an exporter's)."""
    points: list[tuple[float, float]] = []
    for a, _, centre, r, a0, sweep in outline.pieces():
        points.append(a)
        if centre is None:
            continue
        n = max(2, math.ceil(sides(r, sag) * abs(sweep) / (2 * math.pi)))
        points += [(centre[0] + r * math.cos(a0 + sweep * k / n), centre[1] + r * math.sin(a0 + sweep * k / n))
                   for k in range(1, n)]  # fmt: skip
    return points


def _placed(solid: Any, origin: Array, e1: Array, e2: Array, n: Array) -> Any:
    """A solid made in (e1, e2, n) coordinates, moved into the frame."""
    return solid.transform(np.column_stack([e1, e2, n, origin]))


def _letters(text: str, height: float, sag: float = SAG) -> Any:
    """A line of letters as a cross-section about its box's centre: each contour a polygon whose corners lie on its curves, each quadratic cut into chords within ``sag`` of it (a chord over dt of a quadratic strays |P0 - 2 P1 + P2| dt^2 / 4), the region manifold3d's nonzero one."""
    from forge_spec.font import CAP_HEIGHT

    scale = height / CAP_HEIGHT
    contours, length = line_contours(text)
    rings = []
    for run in contours:
        ring = []
        for a, c, b in run:
            bend = math.hypot(a[0] - 2 * c[0] + b[0], a[1] - 2 * c[1] + b[1]) * scale
            count = max(1, math.ceil(math.sqrt(bend / (4 * sag))))
            for j in range(count):
                t = j / count
                x = (1 - t) ** 2 * a[0] + 2 * (1 - t) * t * c[0] + t * t * b[0]
                y = (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * c[1] + t * t * b[1]
                ring.append(((x - length / 2) * scale, y * scale - height / 2))
        rings.append(ring)
    return m3().CrossSection(rings, fillrule=m3().FillRule.NonZero)


#: How far a rounding's piece runs on behind the two faces it rounds (into the air an outside edge has there, or
#: the material an inside one has): less than what stands on a face runs into it, so no face of one lies in the
#: other's plane.
BEHIND = 0.6 * OVERLAP
#: How far short of a face a rounding's straight run that ends on one stops (a vertical edge's at the face a
#: standing box is joined to): no end of it lies in that face; what it leaves is far within the mesh's deflection.
SHORT = 1e-4


def _corner_section(
    size: float, round_: bool, sag: float = SAG, phase: float = 0.5
) -> list[tuple[float, float]]:
    """A rounding's (or a bevel's) section in a right-angled corner, in (along one face, along the other) from the edge, counter-clockwise: the corner up to the round touching both faces ``size`` back (its vertices on the round), or up to the bevel's line; run on a hair behind both faces (:data:`BEHIND`)."""
    e = BEHIND
    if not round_:
        # The bevel's line carried on behind both faces: no vertex in either.
        return [(-e, -e), (size + e, -e), (-e, size + e)]
    # The round's own vertices, ``phase`` of a step on from where it touches a face: none there (a polygon's side
    # from there would graze the face, and a hair's difference between them makes slivers), and none at the
    # heights another piece's are at; from behind each face straight to the next on the round, which leaves of
    # the corner less than a side's sag.
    n = max(2, sides(size, sag) // 4)
    arc = [(size + size * math.cos(-math.pi / 2 - math.pi / 2 * (k + phase) / n),
            size + size * math.sin(-math.pi / 2 - math.pi / 2 * (k + phase) / n)) for k in range(n)]  # fmt: skip
    return [(-e, -e), (size, -e), *arc, (-e, size)]


def _phase(way: Any) -> float:
    """Where a piece's round's vertices start (:func:`_corner_section`), by the frame axis it runs along or turns about: so two pieces running different ways, which may meet, have none at one height."""
    return (1 + int(np.argmax(np.abs(np.asarray(way, dtype=float))))) / 4


#: How far past its quarter turn a rounded corner's ring is made, each way (radians): into the straight runs
#: it meets, so it and they overlap rather than meet in a plane; it strays from them by far less than the sag.
_PAST = 1e-3


def _rounding(step: Step, sag: float = SAG) -> Any:
    """A rounding's (or a bevel's) piece: a straight edge's section pushed along it (carried on past its ends as the step allows), or a rim's turned round its axis (a quarter turn of it a hair past each end)."""
    low, high = step.reach
    if isinstance(step.solid, Corner):
        c = step.solid
        a, b, w = (np.asarray(v, dtype=float) for v in (c.a, c.b, c.along))
        if float(np.dot(np.cross(a, b), w)) < 0:
            a, b = (
                b,
                a,
            )  # the section is the same either way round: keep the transform right-handed
        # Carried on past an end as the step allows; where it may not be, stopped just short of it.
        before, after = low or -SHORT, high or -SHORT
        made = m3().Manifold.extrude(
            m3().CrossSection(
                [_corner_section(c.size, c.round_, sag, _phase(c.along))]
            ),
            c.length + before + after,
        )
        return _placed(made, np.asarray(c.start, dtype=float) - before * w, a, b, w)
    r = step.solid
    assert isinstance(r, RingCorner)
    section = [(r.radius + u * r.a[0] + v * r.b[0], r.height + u * r.a[1] + v * r.b[1])
               for u, v in _corner_section(r.size, r.round_, sag, _phase(r.axis))]  # fmt: skip
    area = sum(
        x0 * y1 - x1 * y0
        for (x0, y0), (x1, y1) in zip(section, section[1:] + section[:1], strict=True)
    )
    if area < 0:
        section.reverse()
    w = np.asarray(r.axis, dtype=float)
    count = sides(r.radius + r.size, sag)
    # Its vertices a quarter of its step round: a power of two of them, so none lies at an angle a disc's or a
    # rounded corner's (half a step round, of a power of two of its own) has one at.
    quarter = math.pi / (2 * count)
    if r.first is None:
        helper = (
            np.array([1.0, 0.0, 0.0]) if abs(w[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        )
        first = np.cross(helper, w)
        first /= np.linalg.norm(first)
        start, degrees = quarter, 360.0
    else:
        assert r.turn is not None
        first = np.asarray(r.first, dtype=float)
        start = r.turn[0] - _PAST - quarter
        degrees = math.degrees(r.turn[1] + _PAST - start)
    made = m3().Manifold.revolve(m3().CrossSection([section]), count, degrees)
    u = math.cos(start) * first + math.sin(start) * np.cross(w, first)
    return _placed(made, np.asarray(r.centre, dtype=float), u, np.cross(w, u), w)


#: How far a block added to the part is grown round its sides (mm): a side pressed flush against a wall then
#: overlaps it, where meeting it in one plane would leave a crack of no width along the corner, which
#: manifold3d keeps as surface. Far within the mesh's deflection.
PRESSED = 1e-5


def _solid(step: Step, sag: float = SAG, *, pressed: bool = False) -> Any:
    if isinstance(step.solid, (Corner, RingCorner)):
        return _rounding(step, sag)
    low, high = step.reach
    if isinstance(step.solid, Letters):
        line = step.solid
        e1, e2, n = (
            np.asarray(v, dtype=float) for v in (line.right, line.up, line.normal)
        )
        made = m3().Manifold.extrude(
            _letters(line.text, line.height, sag),
            (line.high + high) - (line.low - low),
        )
        return _placed(
            made,
            np.asarray(line.centre, dtype=float) + (line.low - low) * n,
            e1,
            e2,
            n,
        )
    if isinstance(step.solid, Pushed):
        q = step.solid
        e1, e2, n = (np.asarray(v, dtype=float) for v in (q.first, q.second, q.normal))
        points = _polygon(q.outline, sag)
        if float(np.dot(np.cross(e1, e2), n)) < 0:
            # Keep the transform right-handed: the outline mirrored, and followed the other way round so it
            # still runs anticlockwise (a section's inside is where it winds positively).
            e2 = -e2
            points = [(u, -v) for u, v in reversed(points)]
        made = m3().Manifold.extrude(
            m3().CrossSection([points]), (q.high + high) - (q.low - low)
        )
        origin = np.asarray(q.origin, dtype=float) + (q.low - low) * n
        return _placed(made, origin, e1, e2, n)
    if isinstance(step.solid, Turned):
        t = step.solid
        w = np.asarray(t.axis, dtype=float)
        helper = (
            np.array([1.0, 0.0, 0.0]) if abs(w[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        )
        u = np.cross(helper, w)
        u /= np.linalg.norm(u)
        v = np.cross(w, u)
        (_, _), (reach, _) = t.outline.box()
        made = m3().Manifold.revolve(
            m3().CrossSection([_polygon(t.outline, sag)]), sides(reach, sag)
        )
        return _placed(made, np.asarray(t.base, dtype=float), u, v, w)
    if isinstance(step.solid, Kept):
        # Its prism (carried on past neither end), cut by its two planes, each carried on as the step allows.
        k = step.solid
        made = _solid(replace(step, solid=k.solid, reach=(0.0, 0.0)), sag, pressed=pressed)
        n = np.asarray(k.normal, dtype=float)
        at = float(np.dot(np.asarray(k.origin, dtype=float), n))
        made = made.trim_by_plane(tuple(n), at + k.low - low)
        return made.trim_by_plane(tuple(-n), -(at + k.high + high))
    if isinstance(step.solid, Prism):
        p = step.solid
        if pressed:
            p = replace(
                p,
                half=(p.half[0] + PRESSED, p.half[1] + PRESSED),
                corner=p.corner + PRESSED if p.corner else 0.0,
            )
        e1, e2, n = (np.asarray(v, dtype=float) for v in (p.first, p.second, p.normal))
        rounded: tuple[bool, ...] = p.rounded
        if float(np.dot(np.cross(e1, e2), n)) < 0:  # keep the transform right-handed
            e2 = -e2
            rounded = rounded[::-1]  # the second direction turned: each corner's mirror
        section = m3().CrossSection([_outline(p, rounded, sag)])
        made = m3().Manifold.extrude(section, (p.high + high) - (p.low - low))
        origin = np.asarray(p.centre, dtype=float) + (p.low - low) * n
        return _placed(made, origin, e1, e2, n)
    f = step.solid
    assert isinstance(f, Frustum)
    r0, r1 = f.radii
    slope = (r1 - r0) / f.length
    start, end = -low, f.length + high
    count = sides(max(r0, r1), sag)
    made = m3().Manifold.cylinder(
        end - start, r0 + slope * start, r0 + slope * end, count
    )
    w = np.asarray(f.axis, dtype=float)
    helper = np.array([1.0, 0.0, 0.0]) if abs(w[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = np.cross(helper, w)
    u /= np.linalg.norm(u)
    v = np.cross(w, u)
    turn = math.pi / (2 * count)  # a quarter step round
    u, v = (
        math.cos(turn) * u + math.sin(turn) * v,
        -math.sin(turn) * u + math.cos(turn) * v,
    )
    return _placed(made, np.asarray(f.base, dtype=float) + start * w, u, v, w)


#: How far in a mesh's thread's crests are from its major radius (mm).
CREST = 0.002


def _slices(radius: float) -> int:
    """How many slices a turn of a thread's twisted mesh is cut into: 72, or as many as keep the helix's chord at the crest within a quarter of :data:`THREAD_DEFLECTION` of it.

    Between slices each triangle runs straight where the true surface winds,
    and the triangles across the profile's corners stray half as far again:
    at 72, an M10's root strayed 0.0057 mm under its minor radius, past the
    0.0052 its mesh declared (generated part 3767). Its radius alone sets
    the chord's stray, so a wider thread is cut into more slices.
    """
    return max(
        72, math.ceil(math.pi / math.acos(1.0 - THREAD_DEFLECTION / (4.0 * radius)))
    )


def _threaded(t: Threaded, threads: set[int] | None = None) -> Any:
    """A thread's stretch of its rod, cut into the ISO 68-1 basic profile (tests/v2_reference.py's ``threaded``, either hand): its section, twisted as it rises.

    Across the axis at height s the section is the one at its start turned
    by hand 2 pi s / pitch: at each angle its radius is the basic profile's
    (a crest flat an eighth of the pitch wide at the major radius, 60 degree
    flanks, a root flat a quarter wide at the minor radius), at the profile's
    coordinate s - hand theta pitch / 2 pi.
    """
    pitch, r = t.pitch, t.radius
    deep = r - t.minor

    def profile(u: Array) -> Array:
        off = np.minimum(u, pitch - u)  # from the nearest crest's middle
        # Its crests 2 microns in (within the mesh's deflection): where the plain rod runs on into the thread,
        # the rod's polygon and the crests' never all but coincide.
        return np.asarray(
            np.clip(r - math.sqrt(3) * (off - pitch / 16), r - deep, r - CREST)
        )

    angles = 2 * math.pi * np.arange(360) / 360
    radius = profile(np.mod(-t.hand * angles * pitch / (2 * math.pi), pitch))
    section = m3().CrossSection(
        [np.stack([radius * np.cos(angles), radius * np.sin(angles)], axis=1).tolist()]
    )
    # Run on a hair before its start, into the plain rod (or what the rod stands on): no plane of either there.
    length = t.end - t.start + OVERLAP
    turns = length / pitch
    made = m3().Manifold.extrude(
        section, length, math.ceil(turns * _slices(r)), t.hand * 360 * turns
    )
    if threads is not None:
        threads.add(made.original_id())
    w = np.asarray(t.axis, dtype=float)
    helper = np.array([1.0, 0.0, 0.0]) if abs(w[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = np.cross(helper, w)
    u /= np.linalg.norm(u)
    return _placed(
        made,
        np.asarray(t.base, dtype=float) + (t.start - OVERLAP) * w,
        u,
        np.cross(w, u),
        w,
    )


def _rod_stretch(t: Threaded, reach: float, late: float) -> Any:
    """The rod's stretch a thread is cut over, from ``late`` past where it starts to ``reach`` past its end, a little wider than the rod (by ``reach``): what the threaded stretch replaces."""
    w = np.asarray(t.axis, dtype=float)
    helper = np.array([1.0, 0.0, 0.0]) if abs(w[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = np.cross(helper, w)
    u /= np.linalg.norm(u)
    # On past the free end into the air too, so its end is no plane of the rod's.
    made = m3().Manifold.cylinder(
        t.end - t.start - late + reach, t.radius + reach, t.radius + reach, 256
    )
    return _placed(
        made,
        np.asarray(t.base, dtype=float) + (t.start + late) * w,
        u,
        np.cross(w, u),
        w,
    )


#: How far a rounding's straight run stops short of an end in a zone (where it meets another at a corner), in
#: its size: a little more than the size, so no two runs' rounds touch there (their surfaces would be tangent at
#: the corner) and no run's end lies in another's face; what it leaves unrounded is within the zone.
TRIM = 1.1


def _trimmed(step: Step, zones: Sequence[tuple[Any, Any]]) -> Step | None:
    """A rounding's straight run, each end that lies in a zone stopped :data:`TRIM` times its size short; None when nothing is left of it."""
    c = step.solid
    assert isinstance(c, Corner)
    start, w = np.asarray(c.start, dtype=float), np.asarray(c.along, dtype=float)

    def zoned(p: Array) -> bool:
        return any(bool(np.all((p >= lo) & (p <= hi))) for lo, hi in zones)

    first = TRIM * c.size if zoned(start) else 0.0
    last = TRIM * c.size if zoned(start + c.length * w) else 0.0
    if c.length - first - last <= 1e-9:
        return None
    if not (first or last):
        return step
    low, high = step.reach
    solid = replace(c, start=tuple(start + first * w), length=c.length - first - last)
    return replace(
        step, solid=solid, reach=(0.0 if first else low, 0.0 if last else high)
    )


def _loops(steps: Sequence[Step]) -> dict[tuple[str, int, bool], list[Step]]:
    """A rounding's pieces round a loop of straight runs and rounded corners (a quarter of a ring at each): by item, copy and whether they fill, each loop's pieces."""
    found: dict[tuple[str, int, bool], list[Step]] = {}
    for step in steps:
        if isinstance(step.solid, (Corner, RingCorner)):
            found.setdefault((step.item, step.index, step.add), []).append(step)
    return {
        key: pieces
        for key, pieces in found.items()
        if any(
            isinstance(p.solid, RingCorner) and p.solid.turn is not None for p in pieces
        )
    }


def _rim_loop(
    h1: float, h2: float, r: float, count: int
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """A rectangle's outline with its corners rounded by ``r``, anticlockwise, each point with its outward normal: each corner's quarter in ``count`` / 4 steps, an eighth of a step on from where it starts.

    So no point lies at an angle a vertex round the same axis lies at: a
    rounded corner's or a disc's (half a step round), or a rounding's of the
    corner's edge (a quarter, a half or three quarters of a step on, either
    way round: :func:`_phase`), each of a power of two of them.
    """
    quarter = count // 4
    found = []
    for k, (sx, sy) in enumerate(QUADRANTS):
        cx, cy = sx * (h1 - r), sy * (h2 - r)
        for i in range(quarter):
            t = math.pi / 2 * (k + (i + 0.125) / quarter)
            found.append(
                (
                    (cx + r * math.cos(t), cy + r * math.sin(t)),
                    (math.cos(t), math.sin(t)),
                )
            )
    return found


def _swept_loop(pieces: Sequence[Step], sag: float = SAG) -> Any:
    """A loop's pieces made as one mesh: the rounding's section swept once round the loop (the edge, a rectangle with its corners rounded), so no two pieces' round surfaces, one running on into the next, are left to a boolean."""
    rings = [p.solid for p in pieces if isinstance(p.solid, RingCorner)]
    first = rings[0]
    n, e1 = np.asarray(first.axis, dtype=float), np.asarray(first.first, dtype=float)
    e2 = np.cross(n, e1)
    corners = [np.asarray(r.centre, dtype=float) + r.height * n for r in rings]
    centre = np.mean(corners, axis=0)
    rc = first.radius
    h1 = max(abs(float((c - centre) @ e1)) for c in corners) + rc
    h2 = max(abs(float((c - centre) @ e2)) for c in corners) + rc
    # In (out from the loop, along its axis): each face's way from the edge, as the corner's ring has it.
    out, up = first.a[0], first.b[1]
    section = [
        (out * u, up * v)
        for u, v in _corner_section(first.size, first.round_, sag, _phase(n))
    ]
    loop = _rim_loop(h1, h2, rc, sides(rc + first.size, sag))
    return _placed(swept(section, loop, 0.0), centre, e1, e2, n)


def build(truth: Truth, sag: float = SAG, threads: set[int] | None = None) -> Any:
    """The part, as a manifold3d solid, its round edges' sides within ``sag`` of their arcs; a thread cut into its rod's stretch, at the turn this builds it (``threads``: each thread's id as the library made it, for :func:`meshed`)."""
    part = None
    zones = [
        (np.asarray(lo, dtype=float), np.asarray(hi, dtype=float))
        for lo, hi in truth.zones
    ]
    loops = _loops(truth.steps)
    for step in truth.steps:
        key = (step.item, step.index, step.add)
        if key in loops:
            if step is not loops[key][0]:
                continue  # made with the first of its loop
            solid = _swept_loop(loops[key], sag)
            part = solid if part is None else part + solid if step.add else part - solid
            continue
        if isinstance(step.solid, Corner):
            found = _trimmed(step, zones)
            if found is None:
                continue
            step = found
        if isinstance(step.solid, Threaded):
            assert part is not None
            # The plain rod runs on a hair into the thread (OVERLAP; within the zone the truth leaves unsaid), so
            # its end crosses the thread's helical faces and no plane of one lies in the other's.
            part = (
                part
                - _rod_stretch(step.solid, 0.05, OVERLAP)
                + _threaded(step.solid, threads)
            )
            continue
        solid = _solid(step, sag, pressed=part is not None and step.add)
        if part is None:
            part = solid
        elif step.add:
            part = part + solid
        else:
            part = part - solid
    assert part is not None
    return part


def deflection(truth: Truth, sag: float = SAG, *, threads: bool = True) -> float:
    """How far the part's mesh (built at ``sag``) is from its true surface, honestly and with room: its widest round edge's side's sag, three times, and 0.0002 mm where round surfaces' facets cross (with ``threads``, a thread's twisted mesh too)."""
    worst = 0.0
    for step in truth.steps:
        s = step.solid
        if isinstance(s, Kept):
            s = s.solid  # cut by two planes, no round edge of its own
        if isinstance(s, Letters):
            worst = max(worst, sag)  # each chord within the sag of its curve
            continue
        if isinstance(s, Threaded):
            if threads:
                # its twisted mesh's triangles across the helix
                worst = max(worst, THREAD_DEFLECTION / 3)
            continue
        if isinstance(s, Corner):
            worst = max(worst, _sag(s.size, sag) if s.round_ else 0.0)
            continue
        if isinstance(s, RingCorner):
            worst = max(
                worst,
                _sag(s.radius + s.size, sag),
                _sag(s.size, sag) if s.round_ else 0.0,
            )
            continue
        if isinstance(s, (Pushed, Turned)):
            radii = [r for *_, r, _a0, _sweep in s.outline.pieces() if r > 0]
            if isinstance(s, Turned):
                radii.append(
                    s.outline.box()[1][0]
                )  # turned: its widest circle round the axis
        else:
            radii = [s.corner] if isinstance(s, Prism) else list(s.radii)
        for r in radii:
            if r > 0:
                worst = max(worst, _sag(r, sag))
    return 3 * worst + 2e-4


def meshed(truth: Truth, sag: float = SAG) -> tuple[Any, Any]:
    """The part's mesh as triangles (built at ``sag``), and how far each may be from the true surface.

    A thread's twisted triangles, and every triangle with a corner on one
    (another face's edge where the booleans cut it along the thread's mesh,
    as the thread's end is), as far as :func:`deflection` says the whole
    part may be; the rest, its round edges' sides' deflection alone.
    """
    threads: set[int] = set()
    solid = build(truth, sag, threads)
    vertices, faces = exported(solid)
    on = np.unique(faces[np.isin(origins(solid), sorted(threads))])
    threaded = np.isin(faces, on).any(axis=1)
    every, rest = deflection(truth, sag), deflection(truth, sag, threads=False)
    return vertices[faces], np.where(threaded, every, rest)


def moved(truth: Truth, by: Mapping[tuple[str, int], Sequence[float]]) -> Truth:
    """The part with some copies moved, as a layout that puts them elsewhere would make it: each step's solid, and each copy's point, moved by its copy's ``by`` (item, copy index)."""

    def shift(v: Sequence[float], d: Sequence[float]) -> tuple[float, float, float]:
        return (v[0] + d[0], v[1] + d[1], v[2] + d[2])

    steps = []
    for step in truth.steps:
        d = by.get((step.item, step.index), (0.0, 0.0, 0.0))
        solid = step.solid
        if isinstance(solid, Kept):
            solid = replace(solid, solid=replace(solid.solid, centre=shift(solid.solid.centre, d)),
                            origin=shift(solid.origin, d))  # fmt: skip
        elif isinstance(solid, (Prism, Letters, RingCorner)):
            solid = replace(solid, centre=shift(solid.centre, d))
        elif isinstance(solid, Pushed):
            solid = replace(solid, origin=shift(solid.origin, d))
        elif isinstance(solid, Corner):
            solid = replace(solid, start=shift(solid.start, d))
        else:
            solid = replace(solid, base=shift(solid.base, d))
        steps.append(replace(step, solid=solid))
    copies = {
        item: tuple(
            replace(c, point=shift(c.point, by.get((item, c.index), (0.0, 0.0, 0.0))))
            for c in found
        )
        for item, found in truth.copies.items()
    }
    return Truth(copies, tuple(steps), truth.zones)
