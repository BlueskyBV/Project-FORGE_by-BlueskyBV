"""Do two triangles of a mesh meet anywhere but where they are joined?

A sound mesh's triangles meet only along the sides and at the corners they
share. Any other contact -- one crossing another, a corner resting on a face,
two lying over each other in one plane, a fan folded back on itself -- is a
self-intersection, and a mesh with one has no well-defined inside.

Triangles are closed sets here: touching counts. Pairs sharing corners are
judged on what lies beyond what they share:

- **no shared corner:** they meet if either lies across the other's plane and
  one's side passes through the other, or, in one plane, if they overlap;
- **one shared corner** ``v``: they meet beyond ``v`` if a side opposite ``v``
  passes through the other triangle, or a side from ``v`` lies in the other's
  plane pointing into it (in one plane: if the two angles at ``v`` overlap).
  Whatever the two share beyond ``v`` is a segment from ``v`` whose far end is
  on one of those sides, so nothing else need be looked at;
- **one shared side:** across planes they meet only along it; in one plane they
  meet beyond it when both lie on the same side of it: a fold;
- **all three corners:** the same triangle twice.

Every sign is exact (:mod:`.predicates`). Cheap tests that prove two
triangles apart come first -- one wholly on one side of the other's plane, or
a line through a side parting them as seen along an axis -- using only the
floating-point signs that are sure; the pairs they can't settle are decided
exactly.

>>> import numpy as np
>>> v = np.array([[0, 0, 0], [2, 0, 0], [0, 2, 0], [0.5, 0.5, -1], [0.5, 0.5, 1], [1, 1, 1]], float)
>>> f = np.array([[0, 1, 2], [3, 4, 5], [0, 4, 5]])
>>> pairs_meet(v, f, np.array([0, 0]), np.array([1, 2])).tolist()
[True, False]
"""

from __future__ import annotations

from fractions import Fraction

import numpy as np
from numpy.typing import NDArray

from .predicates import orient2d, orient2d_filtered, orient3d, orient3d_filtered

__all__ = ["pairs_meet", "simple_stars"]

Array = NDArray[np.float64]
Bools = NDArray[np.bool_]


def _flat(points: Array, axis: NDArray[np.int64]) -> Array:
    """Each point seen along its row's axis: the other two coordinates, in turn order."""
    rows = np.arange(len(points))
    return np.stack(
        [points[rows, (axis + 1) % 3], points[rows, (axis + 2) % 3]], axis=1
    )


def _axis(a: Array, b: Array, c: Array) -> NDArray[np.int64]:
    """For each triangle, an axis along which it is seen with area, exactly checked.

    The axis its normal is closest to, unless along that axis its exact area is
    zero (a nearly edge-on triangle); then another. A triangle with area has
    area along at least one axis.
    """
    normal = np.cross(b - a, c - a)
    preference = np.argsort(-np.abs(normal), axis=1, kind="stable")
    axis = preference[:, 0].astype(np.int64)
    for choice in (1, 2):
        flat = orient2d(_flat(a, axis), _flat(b, axis), _flat(c, axis)) == 0
        if not flat.any():
            break
        axis = np.where(flat, preference[:, choice], axis)
    return axis


def _on_segment(a: Array, b: Array, p: Array) -> Bools:
    """Given ``p`` on the line through ``a``, ``b`` (2D): is it between them, ends included?"""
    between = (np.minimum(a, b) <= p) & (p <= np.maximum(a, b))
    return np.asarray(between.all(axis=1), dtype=bool)


def _segments_meet_2d(p1: Array, p2: Array, p3: Array, p4: Array) -> Bools:
    d1, d2 = orient2d(p3, p4, p1), orient2d(p3, p4, p2)
    d3, d4 = orient2d(p1, p2, p3), orient2d(p1, p2, p4)
    proper = (d1 * d2 < 0) & (d3 * d4 < 0)
    touch = (
        ((d1 == 0) & _on_segment(p3, p4, p1))
        | ((d2 == 0) & _on_segment(p3, p4, p2))
        | ((d3 == 0) & _on_segment(p1, p2, p3))
        | ((d4 == 0) & _on_segment(p1, p2, p4))
    )
    return np.asarray(proper | touch, dtype=bool)


def _in_triangle_2d(p: Array, a: Array, b: Array, c: Array) -> Bools:
    o1, o2, o3 = orient2d(a, b, p), orient2d(b, c, p), orient2d(c, a, p)
    return ((o1 >= 0) & (o2 >= 0) & (o3 >= 0)) | ((o1 <= 0) & (o2 <= 0) & (o3 <= 0))


def _segment_meets_triangle_2d(
    p: Array, q: Array, a: Array, b: Array, c: Array
) -> Bools:
    return (
        _in_triangle_2d(p, a, b, c)
        | _in_triangle_2d(q, a, b, c)
        | _segments_meet_2d(p, q, a, b)
        | _segments_meet_2d(p, q, b, c)
        | _segments_meet_2d(p, q, c, a)
    )


def _triangles_meet_2d(
    t1: tuple[Array, Array, Array], t2: tuple[Array, Array, Array]
) -> Bools:
    a1, b1, c1 = t1
    a2, b2, c2 = t2
    meet = _in_triangle_2d(a2, a1, b1, c1) | _in_triangle_2d(a1, a2, b2, c2)
    for p, q in ((a1, b1), (b1, c1), (c1, a1)):
        for r, s in ((a2, b2), (b2, c2), (c2, a2)):
            meet = meet | _segments_meet_2d(p, q, r, s)
    return meet


def _segment_meets_triangle(p: Array, q: Array, a: Array, b: Array, c: Array) -> Bools:
    """Does the closed segment ``pq`` meet the closed triangle ``abc``? Exactly."""
    meet = np.zeros(len(p), dtype=bool)
    sp, sq = orient3d(a, b, c, p), orient3d(a, b, c, q)
    level = (sp == 0) & (sq == 0)
    across = (sp * sq <= 0) & ~level
    i = np.flatnonzero(across)
    if i.size:
        l1 = orient3d(p[i], q[i], a[i], b[i])
        l2 = orient3d(p[i], q[i], b[i], c[i])
        l3 = orient3d(p[i], q[i], c[i], a[i])
        meet[i] = ((l1 >= 0) & (l2 >= 0) & (l3 >= 0)) | (
            (l1 <= 0) & (l2 <= 0) & (l3 <= 0)
        )
    i = np.flatnonzero(level)
    if i.size:
        axis = _axis(a[i], b[i], c[i])
        meet[i] = _segment_meets_triangle_2d(
            _flat(p[i], axis), _flat(q[i], axis),
            _flat(a[i], axis), _flat(b[i], axis), _flat(c[i], axis),
        )  # fmt: skip
    return meet


def _ray_in_angle_2d(v: Array, x: Array, e1: Array, e2: Array) -> Bools:
    """Does the ray from ``v`` through ``x`` lie in the closed angle from ``v`` between ``e1`` and ``e2``?"""
    turn = orient2d(v, e1, e2)
    return (orient2d(v, e1, x) * turn >= 0) & (orient2d(v, x, e2) * turn >= 0)


def _ray_in_triangle(v: Array, x: Array, e1: Array, e2: Array) -> Bools:
    """With ``x`` in the plane of triangle ``v e1 e2``: does the ray from ``v`` through ``x`` enter it?"""
    axis = _axis(v, e1, e2)
    return _ray_in_angle_2d(
        _flat(v, axis), _flat(x, axis), _flat(e1, axis), _flat(e2, axis)
    )


# --- deciding, exactly ------------------------------------------------------------


def _apart(a1: Array, b1: Array, c1: Array, a2: Array, b2: Array, c2: Array) -> Bools:
    """No shared corner: do the two triangles meet? Exactly."""
    meet = np.zeros(len(a1), dtype=bool)
    o2 = np.stack([orient3d(a1, b1, c1, x) for x in (a2, b2, c2)], axis=1)
    o1 = np.stack([orient3d(a2, b2, c2, x) for x in (a1, b1, c1)], axis=1)
    parted = (o2 > 0).all(1) | (o2 < 0).all(1) | (o1 > 0).all(1) | (o1 < 0).all(1)
    level = (o2 == 0).all(1)
    i = np.flatnonzero(level)
    if i.size:
        axis = _axis(a1[i], b1[i], c1[i])
        meet[i] = _triangles_meet_2d(
            (_flat(a1[i], axis), _flat(b1[i], axis), _flat(c1[i], axis)),
            (_flat(a2[i], axis), _flat(b2[i], axis), _flat(c2[i], axis)),
        )
    i = np.flatnonzero(~parted & ~level)
    if i.size:
        t1 = (a1[i], b1[i], c1[i])
        t2 = (a2[i], b2[i], c2[i])
        hit = np.zeros(i.size, dtype=bool)
        for p, q in ((t1[0], t1[1]), (t1[1], t1[2]), (t1[2], t1[0])):
            hit |= _segment_meets_triangle(p, q, *t2)
        for p, q in ((t2[0], t2[1]), (t2[1], t2[2]), (t2[2], t2[0])):
            hit |= _segment_meets_triangle(p, q, *t1)
        meet[i] = hit
    return meet


def _at_corner(v: Array, p1: Array, q1: Array, p2: Array, q2: Array) -> Bools:
    """Triangles ``v p1 q1`` and ``v p2 q2``: do they meet anywhere but ``v``? Exactly."""
    meet = np.zeros(len(v), dtype=bool)
    o1, o2 = orient3d(v, p1, q1, p2), orient3d(v, p1, q1, q2)
    o3, o4 = orient3d(v, p2, q2, p1), orient3d(v, p2, q2, q1)
    parted = (o1 * o2 > 0) | (o3 * o4 > 0)
    level = (o1 == 0) & (o2 == 0)
    i = np.flatnonzero(level)
    if i.size:
        axis = _axis(v[i], p1[i], q1[i])
        fv, fp1, fq1, fp2, fq2 = (_flat(x[i], axis) for x in (v, p1, q1, p2, q2))
        meet[i] = (
            _ray_in_angle_2d(fv, fp1, fp2, fq2)
            | _ray_in_angle_2d(fv, fq1, fp2, fq2)
            | _ray_in_angle_2d(fv, fp2, fp1, fq1)
            | _ray_in_angle_2d(fv, fq2, fp1, fq1)
        )
    i = np.flatnonzero(~parted & ~level)
    if i.size:
        vi, p1i, q1i, p2i, q2i = v[i], p1[i], q1[i], p2[i], q2[i]
        hit = _segment_meets_triangle(p1i, q1i, vi, p2i, q2i)
        hit |= _segment_meets_triangle(p2i, q2i, vi, p1i, q1i)
        for sign, x, e1, e2 in (
            (o3[i], p1i, p2i, q2i),
            (o4[i], q1i, p2i, q2i),
            (o1[i], p2i, p1i, q1i),
            (o2[i], q2i, p1i, q1i),
        ):
            k = np.flatnonzero(sign == 0)
            if k.size:
                hit[k] |= _ray_in_triangle(vi[k], x[k], e1[k], e2[k])
        meet[i] = hit
    return meet


def _along_side(u: Array, w: Array, c1: Array, c2: Array) -> Bools:
    """Triangles ``u w c1`` and ``u w c2``: folded onto each other? Exactly."""
    meet = np.zeros(len(u), dtype=bool)
    i = np.flatnonzero(orient3d(u, w, c1, c2) == 0)
    if i.size:
        axis = _axis(u[i], w[i], c1[i])
        fu, fw = _flat(u[i], axis), _flat(w[i], axis)
        meet[i] = (
            orient2d(fu, fw, _flat(c1[i], axis)) * orient2d(fu, fw, _flat(c2[i], axis))
            > 0
        )
    return meet


# --- proving apart, cheaply -------------------------------------------------------


def _sure_one_side(a: Array, b: Array, c: Array, points: list[Array]) -> Bools:
    """Are all ``points`` surely strictly on one side of the plane through ``a, b, c``?"""
    signs, sures = zip(*(orient3d_filtered(a, b, c, x) for x in points), strict=True)
    sign = np.stack(signs, axis=1)
    sure = np.stack(sures, axis=1).all(axis=1)
    return np.asarray(
        sure & ((sign > 0).all(axis=1) | (sign < 0).all(axis=1)), dtype=bool
    )


def _sure_parted_by(
    line: tuple[Array, Array], own: list[Array], others: list[Array]
) -> Bools:
    """Seen in 2D: are ``own`` surely strictly on one side of the line, ``others`` across it?"""
    p, q = line
    own_signs = [orient2d_filtered(p, q, x) for x in own]
    other_signs = [orient2d_filtered(p, q, x) for x in others]
    sure: Bools = np.ones(len(p), dtype=bool)
    for _, s in own_signs + other_signs:
        sure &= s
    first = own_signs[0][0]
    parted: Bools = sure & (first != 0)
    for sign, _ in own_signs[1:]:
        parted &= sign == first
    for sign, _ in other_signs:
        parted &= sign == -first
    return parted


def _sure_apart_2d(t1: list[Array], t2: list[Array], axis: NDArray[np.int64]) -> Bools:
    """No shared corner, seen along ``axis``: does a line through a side part them?"""
    f1 = [_flat(x, axis) for x in t1]
    f2 = [_flat(x, axis) for x in t2]
    apart = np.zeros(len(axis), dtype=bool)
    for mine, theirs in ((f1, f2), (f2, f1)):
        for k in range(3):
            p, q, r = mine[k], mine[(k + 1) % 3], mine[(k + 2) % 3]
            apart |= _sure_parted_by((p, q), [r], theirs)
    return apart


def _sure_apart(t1: list[Array], t2: list[Array]) -> Bools:
    """No shared corner: surely apart? The cheapest proofs first, each on the pairs still open."""
    apart = _sure_one_side(t1[0], t1[1], t1[2], t2)
    for proof in range(3):
        left = np.flatnonzero(~apart)
        if not left.size:
            break
        x, y = [p[left] for p in t1], [p[left] for p in t2]
        if proof == 0:
            apart[left] = _sure_one_side(y[0], y[1], y[2], x)
        elif proof == 1:
            apart[left] = _sure_apart_2d(x, y, _axis_float(x[0], x[1], x[2]))
        else:
            apart[left] = _sure_apart_2d(x, y, _axis_float(y[0], y[1], y[2]))
    return apart


def _sure_apart_at_corner(
    v: Array, p1: Array, q1: Array, p2: Array, q2: Array
) -> Bools:
    """One shared corner: surely meeting only there? The cheapest proofs first, each on what's left."""
    apart = _sure_one_side(v, p1, q1, [p2, q2])
    left = np.flatnonzero(~apart)
    if left.size:
        apart[left] = _sure_one_side(v[left], p2[left], q2[left], [p1[left], q1[left]])
        left = left[~apart[left]]
    if left.size:
        vl, a1, b1, a2, b2 = (x[left] for x in (v, p1, q1, p2, q2))
        axis = _axis_float(vl, a1, b1)
        fv, fp1, fq1, fp2, fq2 = (_flat(x, axis) for x in (vl, a1, b1, a2, b2))
        parted = _sure_parted_by((fv, fp1), [fq1], [fp2, fq2])
        parted |= _sure_parted_by((fv, fq1), [fp1], [fp2, fq2])
        parted |= _sure_parted_by((fv, fp2), [fq2], [fp1, fq1])
        parted |= _sure_parted_by((fv, fq2), [fp2], [fp1, fq1])
        apart[left] = parted
    return apart


def _sure_apart_along_side(u: Array, w: Array, c1: Array, c2: Array) -> Bools:
    """One shared side: surely meeting only along it?"""
    signs, sure = orient3d_filtered(u, w, c1, c2)
    apart: Bools = sure & (signs != 0)
    axis = _axis_float(u, w, c1)
    fu, fw = _flat(u, axis), _flat(w, axis)
    apart |= _sure_parted_by((fu, fw), [_flat(c1, axis)], [_flat(c2, axis)])
    return apart


def _axis_float(a: Array, b: Array, c: Array) -> NDArray[np.int64]:
    """The axis a triangle's normal is closest to (any axis gives a sound test)."""
    return np.asarray(np.argmax(np.abs(np.cross(b - a, c - a)), axis=1), dtype=np.int64)


# --- the pairs --------------------------------------------------------------------


def simple_stars(
    vertices: Array, faces: NDArray[np.int64], good: Bools, least: int = 16
) -> Bools:
    """Corners whose triangles surely make one simple fan: no two of them meet beyond the corner.

    Two triangles sharing only a corner ``v`` meet beyond it exactly when
    their angles at ``v`` overlap (what two convex sets share is convex, so it
    reaches out from ``v``). So for a corner with ``least`` triangles or more,
    which would cost many pairs, the fan is checked whole: its triangles in
    order round ``v``, one cycle; seen along an axis that each of their
    normals points along the same way (decided exactly), their angles are
    consecutive turns the same way round, and they go round exactly once,
    counted by the turns that cover one direction. Then no two overlap.
    Corners that fail any test are left to the pairwise test.
    """
    simple = np.zeros(len(vertices), dtype=bool)
    usable = np.flatnonzero(good)
    corner = faces[usable].reshape(-1)  # each usable face's corners, in turn
    face = np.repeat(usable, 3)
    k = np.tile(np.arange(3), len(usable))
    # Each corner's triangles, found once for all corners.
    ranked = np.argsort(corner, kind="stable")
    counts = np.bincount(corner, minlength=len(vertices))
    first = np.cumsum(counts) - counts
    for v in np.flatnonzero(counts >= least).tolist():
        mine = ranked[first[v] : first[v] + counts[v]]
        rows, at = face[mine], k[mine]
        after = faces[rows, (at + 1) % 3]
        before = faces[rows, (at + 2) % 3]
        simple[v] = _one_simple_fan(vertices, v, after, before)
    return simple


def _one_simple_fan(
    vertices: Array, v: int, after: NDArray[np.int64], before: NDArray[np.int64]
) -> bool:
    """Do the triangles (v, after[i], before[i]) make one fan round v, going round once?"""
    nxt = {int(a): i for i, a in enumerate(after.tolist())}
    if len(nxt) != len(after) or set(nxt) != set(before.tolist()):
        return False  # not one closed cycle of triangles
    order = [0]
    while len(order) < len(after):
        following = nxt[int(before[order[-1]])]
        if following == 0:
            return False  # more than one cycle
        order.append(following)
    if nxt[int(before[order[-1]])] != 0:
        return False
    ray = after[order]  # the fan's sides from v, in turn order
    count = len(ray)
    centre = np.repeat(vertices[v][None], count, axis=0)
    here, there = vertices[ray], vertices[np.roll(ray, -1)]
    for axis in range(3):
        drop = np.full(count, axis, dtype=np.int64)
        fc, fa, fb = _flat(centre, drop), _flat(here, drop), _flat(there, drop)
        turn = orient2d(fc, fa, fb)
        if not ((turn > 0).all() or (turn < 0).all()):
            continue
        sense = int(turn[0])
        # How many of the turns cover the direction of the first side (each
        # from its own first side, that one included, to the next, excluded)?
        first = np.repeat(fa[:1], count, axis=0)
        start = orient2d(fc, fa, first) * sense
        end = orient2d(fc, first, fb) * sense
        inside = (start > 0) & (end > 0)
        level = np.flatnonzero(start == 0)  # in line with the first side: which way?
        along = level[_same_way(fc[level], fa[level], first[level])]
        return int(inside.sum()) + len(along) == 1
    return False


def _same_way(origin: Array, a: Array, b: Array) -> Bools:
    """With ``a`` and ``b`` in line with ``origin`` (2D): do they lie the same way from it? Exactly."""
    out = np.zeros(len(origin), dtype=bool)
    for k in range(len(origin)):
        o, x, y = (
            [Fraction(float(c)) for c in point] for point in (origin[k], a[k], b[k])
        )
        out[k] = (x[0] - o[0]) * (y[0] - o[0]) + (x[1] - o[1]) * (y[1] - o[1]) > 0
    return out


def pairs_meet(
    vertices: Array,
    faces: NDArray[np.int64],
    i: NDArray[np.int64],
    j: NDArray[np.int64],
    simple: Bools | None = None,
) -> Bools:
    """For each pair ``faces[i], faces[j]``: do they meet anywhere but where they are joined?

    Both triangles must have area, and three different corners. ``simple``
    marks corners whose fans :func:`simple_stars` has proved simple: pairs
    sharing only such a corner meet nowhere else, untested.
    """
    fi, fj = faces[i], faces[j]
    same = fi[:, :, None] == fj[:, None, :]
    shared = same.sum(axis=(1, 2))
    in_j = same.any(axis=2)  # which of fi's corners fj has
    in_i = same.any(axis=1)  # which of fj's corners fi has
    meet = shared == 3

    k = np.flatnonzero(shared == 0)
    if k.size:
        t1 = [vertices[fi[k, n]] for n in range(3)]
        t2 = [vertices[fj[k, n]] for n in range(3)]
        apart = _sure_apart(t1, t2)
        open_ = np.flatnonzero(~apart)
        if open_.size:
            meet[k[open_]] = _apart(*(x[open_] for x in t1), *(x[open_] for x in t2))

    k = np.flatnonzero(shared == 1)
    if k.size:
        a = np.argmax(in_j[k], axis=1)  # the shared corner, in fi
        b = np.argmax(in_i[k], axis=1)  # and in fj
        if simple is not None:
            keep = ~simple[fi[k, a]]
            k, a, b = k[keep], a[keep], b[keep]
        v = vertices[fi[k, a]]
        p1, q1 = vertices[fi[k, (a + 1) % 3]], vertices[fi[k, (a + 2) % 3]]
        p2, q2 = vertices[fj[k, (b + 1) % 3]], vertices[fj[k, (b + 2) % 3]]
        apart = _sure_apart_at_corner(v, p1, q1, p2, q2)
        open_ = np.flatnonzero(~apart)
        if open_.size:
            meet[k[open_]] = _at_corner(*(x[open_] for x in (v, p1, q1, p2, q2)))

    k = np.flatnonzero(shared == 2)
    if k.size:
        lone_i = np.argmin(in_j[k], axis=1)  # fi's corner fj lacks
        lone_j = np.argmin(in_i[k], axis=1)
        u = vertices[fi[k, (lone_i + 1) % 3]]
        w = vertices[fi[k, (lone_i + 2) % 3]]
        c1 = vertices[fi[k, lone_i]]
        c2 = vertices[fj[k, lone_j]]
        apart = _sure_apart_along_side(u, w, c1, c2)
        open_ = np.flatnonzero(~apart)
        if open_.size:
            meet[k[open_]] = _along_side(*(x[open_] for x in (u, w, c1, c2)))
    return np.asarray(meet, dtype=bool)
