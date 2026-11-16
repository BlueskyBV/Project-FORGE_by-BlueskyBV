"""Products, norms and small linear algebra in a fixed order: the same bits on every machine.

NumPy's ``@``, ``dot``, ``einsum`` and ``linalg`` hand their sums to BLAS and
LAPACK, whose kernels add in an order (and fuse multiplies and adds) that
depends on the CPU, the library and its threads; and ``linalg.norm`` of a
vector is a BLAS dot. Here every product is a NumPy elementwise multiply and
every sum an addition in an order this module fixes: left to right along a
contracted axis of up to :data:`SHORT` terms, NumPy's ``add.reduce`` (its own
pairwise sum, scalar C, the same everywhere) along a longer one. Linear
systems are solved by Gaussian elimination with partial pivoting, row by
row; symmetric eigenproblems by cyclic Jacobi rotations; polynomial roots by
isolating them between the roots of the derivative.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any, cast

import numpy as np
from numpy.typing import NDArray

Array = NDArray[np.float64]

__all__ = [
    "SHORT",
    "cond_symmetric",
    "det",
    "dot",
    "eigh",
    "inv",
    "matmul",
    "norm",
    "real_roots",
    "solve",
    "sum_last",
    "unit",
]

#: Up to this many terms a sum is added left to right; beyond, by NumPy's pairwise ``add.reduce``.
SHORT = 8


def _f(x: Any) -> Array:
    return np.asarray(x, dtype=np.float64)


def sum_last(p: Array) -> Array:
    """The sum over the last axis: ((p0 + p1) + p2) + ... for a short axis, pairwise for a long one."""
    n = p.shape[-1]
    if n == 0:
        return np.zeros(p.shape[:-1])
    if n > SHORT:
        return cast(Array, np.add.reduce(np.ascontiguousarray(p), axis=-1))
    out = p[..., 0].copy()
    for k in range(1, n):
        out = out + p[..., k]
    return out


def dot(a: Any, b: Any) -> Array | float:
    """The sum over the last axes of ``a * b`` (broadcast): a vector's dot product, or rows' with rows.

    A float where both are vectors, as ``numpy.dot`` of two vectors.
    """
    a, b = _f(a), _f(b)
    out = sum_last(a * b)
    return float(out) if out.ndim == 0 else out


def norm(a: Any, axis: int | None = None) -> Array | float:
    """The Euclidean length: of a vector (``axis`` None and ``a`` 1-D), or along ``axis`` (by default the last)."""
    a = _f(a)
    if axis is None:
        if a.ndim <= 1:
            return (
                math.sqrt(float(sum_last((a * a).reshape(-1))))
                if a.ndim
                else abs(float(a))
            )
        a = a.reshape(-1)
        return math.sqrt(float(sum_last(a * a)))
    moved = np.moveaxis(a, axis, -1)
    return np.sqrt(sum_last(moved * moved))


def unit(a: Any) -> Array:
    """``a`` divided by its length (along the last axis); a ValueError where a length is zero or not finite."""
    a = _f(a)
    if a.ndim == 1:
        length = float(np.sqrt(sum_last(a * a)))
        if not math.isfinite(length) or length == 0.0:
            raise ValueError(f"not a direction: {a}")
        return cast(Array, a / length)
    lengths = np.sqrt(sum_last(a * a))
    if not np.all(np.isfinite(lengths) & (lengths > 0.0)):
        raise ValueError("not a direction")
    return cast(Array, a / lengths[..., None])


def matmul(a: Any, b: Any) -> Array | float:
    """``a @ b`` with NumPy's rules for 1-D and stacked operands, its sums in this module's order."""
    a, b = _f(a), _f(b)
    if a.ndim == 0 or b.ndim == 0:
        raise ValueError("matmul: an operand is a scalar")
    va, vb = a.ndim == 1, b.ndim == 1
    if va:
        a = a[None, :]
    if vb:
        b = b[:, None]
    if a.shape[-1] != b.shape[-2]:
        raise ValueError(f"matmul: shapes {a.shape} and {b.shape} don't fit")
    k = a.shape[-1]
    if k <= SHORT:
        out = a[..., :, 0:1] * b[..., 0:1, :]
        for j in range(1, k):
            out = out + a[..., :, j : j + 1] * b[..., j : j + 1, :]
    else:
        out = np.add.reduce(
            np.ascontiguousarray(
                a[..., :, None, :] * np.swapaxes(b, -1, -2)[..., None, :, :]
            ),
            axis=-1,
        )
    if va:
        out = out[..., 0, :]
    if vb:
        out = out[..., 0]
    return float(out) if np.ndim(out) == 0 else out


# ----------------------------------------------------------------------
# Linear systems
# ----------------------------------------------------------------------
def _eliminate(m: Array, rhs: Array) -> tuple[Array, Array, int, float]:
    """Gaussian elimination with partial pivoting (the first largest |pivot| below the diagonal): (U, rhs, swaps, smallest |pivot|)."""
    m = m.copy()
    rhs = rhs.copy()
    n = m.shape[0]
    swaps = 0
    smallest = math.inf
    for k in range(n):
        p = k + int(np.argmax(np.abs(m[k:, k])))
        if p != k:
            m[[k, p]] = m[[p, k]]
            rhs[[k, p]] = rhs[[p, k]]
            swaps += 1
        pivot = float(m[k, k])
        smallest = min(smallest, abs(pivot))
        if pivot == 0.0:
            continue
        if k + 1 < n:
            factors = m[k + 1 :, k] / pivot
            m[k + 1 :, k:] = m[k + 1 :, k:] - factors[:, None] * m[k, k:][None, :]
            rhs[k + 1 :] = (
                rhs[k + 1 :] - factors.reshape((-1,) + (1,) * (rhs.ndim - 1)) * rhs[k]
            )
    return m, rhs, swaps, smallest


def solve(a: Any, b: Any) -> Array:
    """x with ``a x = b`` for a square ``a`` (``b`` a vector or a matrix of right-hand sides); LinAlgError where ``a`` is singular."""
    a, b = _f(a), _f(b)
    n = a.shape[0]
    if a.shape != (n, n) or b.shape[0] != n:
        raise ValueError(f"solve: shapes {a.shape} and {b.shape}")
    u, y, _, smallest = _eliminate(a, b)
    if smallest == 0.0 or not math.isfinite(smallest):
        raise np.linalg.LinAlgError("Singular matrix")
    x = np.empty_like(y)
    for k in range(n - 1, -1, -1):
        acc = y[k].copy() if y.ndim > 1 else float(y[k])
        for j in range(k + 1, n):
            acc = acc - u[k, j] * x[j]
        x[k] = acc / u[k, k]
    return x


def det(a: Any) -> float:
    """The determinant, by the elimination :func:`solve` uses."""
    a = _f(a)
    n = a.shape[0]
    u, _, swaps, _ = _eliminate(a, np.zeros(n))
    out = -1.0 if swaps % 2 else 1.0
    for k in range(n):
        out = out * float(u[k, k])
    return out


def inv(a: Any) -> Array:
    a = _f(a)
    return solve(a, np.eye(a.shape[0]))


# ----------------------------------------------------------------------
# Symmetric eigenproblems
# ----------------------------------------------------------------------
_SWEEPS = 64


def eigh(s: Any) -> tuple[Array, Array]:
    """The eigenvalues (ascending) and unit eigenvectors (columns) of a symmetric matrix, by cyclic Jacobi rotations.

    Each eigenvector's largest component (the first such) is made positive,
    so the vectors are unique where the eigenvalues are distinct.
    """
    a = _f(s).copy()
    n = a.shape[0]
    a = (a + a.T) * 0.5
    v = np.eye(n)
    for _ in range(_SWEEPS):
        off = 0.0
        for p in range(n - 1):
            for q in range(p + 1, n):
                off += float(a[p, q]) * float(a[p, q])
        if off == 0.0:
            break
        scale = 0.0
        for k in range(n):
            scale += float(a[k, k]) * float(a[k, k])
        if off <= 1e-34 * scale:
            break
        for p in range(n - 1):
            for q in range(p + 1, n):
                apq = float(a[p, q])
                if apq == 0.0:
                    continue
                app, aqq = float(a[p, p]), float(a[q, q])
                theta = (aqq - app) / (2.0 * apq)
                t = (1.0 if theta >= 0 else -1.0) / (
                    abs(theta) + math.sqrt(theta * theta + 1.0)
                )
                c = 1.0 / math.sqrt(t * t + 1.0)
                sn = t * c
                rp, rq = a[p, :].copy(), a[q, :].copy()
                a[p, :] = c * rp - sn * rq
                a[q, :] = sn * rp + c * rq
                cp, cq = a[:, p].copy(), a[:, q].copy()
                a[:, p] = c * cp - sn * cq
                a[:, q] = sn * cp + c * cq
                a[p, q] = a[q, p] = 0.0
                vp, vq = v[:, p].copy(), v[:, q].copy()
                v[:, p] = c * vp - sn * vq
                v[:, q] = sn * vp + c * vq
    values = np.array([a[k, k] for k in range(n)])
    order = np.argsort(values, kind="stable")
    values, v = values[order], v[:, order]
    for k in range(n):
        big = int(np.argmax(np.abs(v[:, k])))
        if v[big, k] < 0:
            v[:, k] = -v[:, k]
    return values, v


def cond_symmetric(s: Any) -> float:
    """The 2-norm condition number of a symmetric matrix: its largest |eigenvalue| over its smallest."""
    values = np.abs(eigh(s)[0])
    small = float(values.min())
    return math.inf if small == 0.0 else float(values.max()) / small


# ----------------------------------------------------------------------
# Polynomial roots
# ----------------------------------------------------------------------
def _horner(c: Sequence[Array], s: Array) -> Array:
    out = np.zeros_like(s) + c[0]
    for k in range(1, len(c)):
        out = out * s + c[k]
    return out


def _derivative(c: Sequence[Array]) -> list[Array]:
    n = len(c) - 1
    return [c[k] * float(n - k) for k in range(n)]


def _bound(c: Sequence[Array]) -> Array:
    """A bound on every root's magnitude (Cauchy's, for a leading coefficient 1 after dividing)."""
    lead = np.abs(c[0])
    out = np.zeros_like(lead)
    for k in range(1, len(c)):
        out = np.maximum(out, np.abs(c[k]) / lead)
    return 1.0 + out


def real_roots(coeffs: Any, touch: float = 1e-6) -> Array:
    """Each polynomial's real roots, ascending and NaN-padded to its degree: one polynomial per row of ``coeffs`` (highest degree first).

    The real roots of the derivative (found the same way) split the line,
    within Cauchy's bound on the roots, into stretches where the polynomial is
    monotonic; a stretch whose ends differ in sign holds one simple root,
    found by bisection until no float lies between the ends (or the
    polynomial is 0 at a midpoint). A turning point where the polynomial comes
    within ``touch`` of zero, as an eigenvalue solver's near-real pair
    (|p(s)| <= |p''(s)|/2 (touch (1 + |s|))^2), is a double root: reported
    twice, in place of any simple roots found that close to it.
    """
    c = np.atleast_2d(_f(coeffs))
    rows = c.shape[0]
    cols = [c[:, k] for k in range(c.shape[1])]
    while len(cols) > 1 and not np.any(cols[0]):
        cols = cols[1:]
    degree = len(cols) - 1
    out = np.full((rows, max(degree, 0)), np.nan)
    if degree <= 0:
        return out
    if degree == 1:
        with np.errstate(divide="ignore", invalid="ignore"):
            out[:, 0] = -cols[1] / cols[0]
        return out
    dcols = _derivative(cols)
    turns = real_roots(np.stack(dcols, axis=1), touch)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        bound = _bound(cols)
    inner = np.where(
        np.isnan(turns), bound[:, None], np.clip(turns, -bound[:, None], bound[:, None])
    )
    edges = np.concatenate(
        [-bound[:, None], np.sort(inner, axis=1), bound[:, None]], axis=1
    )
    found: list[Array] = []
    with np.errstate(invalid="ignore", over="ignore"):
        for k in range(edges.shape[1] - 1):
            lo, hi = edges[:, k], edges[:, k + 1]
            flo, fhi = _horner(cols, lo), _horner(cols, hi)
            change = (
                np.isfinite(lo)
                & np.isfinite(hi)
                & (lo < hi)
                & (np.sign(flo) * np.sign(fhi) < 0)
            )
            root = np.full(rows, np.nan)
            if change.any():
                sub = [col[change] for col in cols]
                a, b, fa = lo[change], hi[change], flo[change]
                for _ in range(_BISECTIONS):
                    m = a + (b - a) * 0.5
                    inside = (m > a) & (m < b)
                    if not inside.any():
                        break
                    fm = _horner(sub, m)
                    hit = inside & (fm == 0.0)
                    left = inside & ~hit & (np.sign(fm) == np.sign(fa))
                    right = inside & ~hit & ~left
                    a = np.where(left | hit, m, a)
                    fa = np.where(left, fm, fa)
                    b = np.where(right | hit, m, b)
                root[change] = a + (b - a) * 0.5
            found.append(root)
        simple = np.stack(found, axis=1)
        d2cols = _derivative(dcols)
        doubles: list[Array] = []
        for k in range(turns.shape[1]):
            s = turns[:, k]
            reach = touch * (1.0 + np.abs(s))
            f = _horner(cols, s)
            near = np.isfinite(s) & (
                np.abs(f) <= np.abs(_horner(d2cols, s)) * 0.5 * reach * reach
            )
            if near.any():
                close = near[:, None] & (np.abs(simple - s[:, None]) <= reach[:, None])
                simple = np.where(close, np.nan, simple)
                doubles.append(np.where(near, s, np.nan))
                doubles.append(np.where(near, s, np.nan))
    every = np.concatenate([simple] + [d[:, None] for d in doubles], axis=1)
    every = np.sort(every, axis=1)[:, :degree]
    out[:, : every.shape[1]] = every
    return out


#: Enough halvings to reach adjacent floats from Cauchy's bound for any root not below ~1e-30.
_BISECTIONS = 200
