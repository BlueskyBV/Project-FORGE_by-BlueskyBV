"""Forge's numbers, the same on every machine (forge_numeric; V2-stage4b-0c.md, item 0; ADR-0037).

Three kinds of test: each function against the platform's own ``math`` (two
ulps at most: Forge's is within one of the truth, a decent C library within
one), the array functions against the scalar ones bit for bit, and golden
digests: fixed inputs, made only with exact operations, whose outputs every
machine must reproduce to the last bit. CI runs this file on Linux, Windows
and macOS, x86 and ARM (``trust-core.yml``): that run is the rule's proof.
"""

from __future__ import annotations

import hashlib
import math
import unittest
from typing import ClassVar

import numpy as np
from forge_numeric import scalar as fs
from forge_numeric import vector as fv
from forge_numeric._bits import bits

#: The same inputs everywhere: PCG64's uniform draws (fixed by NumPy) scaled by exact powers of two.
SEED = 2026


def _inputs(n: int, lo_exp: int, hi_exp: int, seed: int = SEED) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return np.ldexp(
        rng.uniform(-1.0, 1.0, n), rng.integers(lo_exp, hi_exp, n).astype(np.int32)
    )


SPECIALS = [0.0, -0.0, 1.0, -1.0, 0.5, -0.5, 0.4375, 0.6875, 1.1875, 2.4375, math.pi, -math.pi,
            math.pi / 2, math.pi / 4, fs.PIO4, fs.MEDIUM, -fs.MEDIUM, 1e22, 1e300, -1e300, 1.7e308,
            math.inf, -math.inf, math.nan, 5e-324, -5e-324, 2.2250738585072014e-308, 709.78, -745.13,
            800.0, -800.0, 2.0, -2.0, 0.975, 2**-26, 2**-27, 2**-28, 2**-57]  # fmt: skip

#: Each function's domain for its random draws (as exponents of two) and its scalar twin.
CASES = {
    "sin": (fv.sin, fs.sin, -40, 24),
    "cos": (fv.cos, fs.cos, -40, 24),
    "tan": (fv.tan, fs.tan, -40, 12),
    "arctan": (fv.arctan, fs.atan, -80, 80),
    "arcsin": (fv.arcsin, fs.asin, -60, 1),
    "arccos": (fv.arccos, fs.acos, -60, 1),
    "exp": (fv.exp, fs.exp, -60, 10),
    "log": (fv.log, fs.log, -1074, 1024),
    "cbrt": (fv.cbrt, fs.cbrt, -1074, 1024),
}


def _same(a: float, b: float) -> bool:
    return (math.isnan(a) and math.isnan(b)) or (
        a == b and math.copysign(1.0, a) == math.copysign(1.0, b)
    )


def _ulps(a: float, b: float) -> int:
    if _same(a, b) or (a == b):
        return 0
    if math.isnan(a) or math.isnan(b):
        return 1 << 62
    return abs(bits(a) - bits(b))


def _digest(*arrays: np.ndarray) -> str:
    h = hashlib.sha256()
    for a in arrays:
        h.update(np.ascontiguousarray(a, dtype=np.float64).tobytes())
    return h.hexdigest()[:16]


class EachFunctionIsAccurate(unittest.TestCase):
    def test_within_two_ulps_of_the_c_library(self) -> None:
        names = {"arctan": "atan", "arcsin": "asin", "arccos": "acos"}
        for name, (_vector, scalar, lo, hi) in CASES.items():
            if name == "log":
                xs = np.abs(_inputs(20000, lo, hi))
            else:
                xs = _inputs(20000, lo, hi)
            ref = getattr(math, names.get(name, name))
            worst = 0
            for x in xs.tolist():
                try:
                    want = ref(x)
                except ValueError, OverflowError:
                    continue
                worst = max(worst, _ulps(scalar(x), want))
            with self.subTest(name=name):
                self.assertLessEqual(worst, 3 if name in ("tan", "cbrt") else 2)

    def test_atan2_within_two_ulps(self) -> None:
        ys, xs = _inputs(20000, -60, 60, 1), _inputs(20000, -60, 60, 2)
        worst = max(
            _ulps(fs.atan2(y, x), math.atan2(y, x))
            for y, x in zip(ys.tolist(), xs.tolist(), strict=True)
        )
        self.assertLessEqual(worst, 2)

    def test_special_values_and_errors_are_maths(self) -> None:
        for name in ("sin", "cos", "tan", "atan", "exp", "log", "cbrt", "asin", "acos"):
            mine, theirs = getattr(fs, name), getattr(math, name)
            for x in [*SPECIALS, 3.0, -3.0]:
                with self.subTest(name=name, x=x):
                    try:
                        want = theirs(x)
                    except (ValueError, OverflowError) as error:
                        with self.assertRaises(type(error)):
                            mine(x)
                        continue
                    self.assertLessEqual(_ulps(mine(x), want), 3)

    def test_exact_values(self) -> None:
        self.assertEqual(fs.sin(0.0), 0.0)
        self.assertTrue(math.copysign(1.0, fs.sin(-0.0)) < 0)
        self.assertEqual(fs.cos(0.0), 1.0)
        self.assertEqual(fs.atan2(0.0, -0.0), math.pi)
        self.assertEqual(fs.atan2(-0.0, -0.0), -math.pi)
        self.assertEqual(fs.atan2(1.0, 0.0), math.pi / 2)
        self.assertEqual(fs.exp(0.0), 1.0)
        self.assertEqual(fs.log(1.0), 0.0)
        self.assertEqual(fs.cbrt(27.0), 3.0)
        self.assertEqual(fs.cbrt(-8.0), -2.0)
        self.assertEqual(fs.acos(1.0), 0.0)
        self.assertEqual(fs.asin(1.0), math.pi / 2)
        # A huge argument, reduced exactly: sin(1e22) is a famous test of argument reduction.
        self.assertEqual(fs.sin(1e22), -0.8522008497671888)

    def test_sincos_is_sin_and_cos(self) -> None:
        for x in _inputs(5000, -30, 30).tolist() + [
            v for v in SPECIALS if math.isfinite(v)
        ]:
            s, c = fs.sincos(x)
            self.assertTrue(_same(s, fs.sin(x)) and _same(c, fs.cos(x)), x)


class TheArraysAreTheScalarsBitForBit(unittest.TestCase):
    def _check(self, vector, scalar, xs: np.ndarray) -> None:
        for chunk in (xs, xs[:5], xs[: fv.SMALL + 3]):
            got = vector(chunk)
            for x, g in zip(chunk.tolist(), got.tolist(), strict=True):
                try:
                    want = scalar(x)
                except ValueError, OverflowError:
                    continue  # math raises; the array gives NaN or infinity
                if not _same(want, g):
                    self.fail(f"{vector.__name__}({x!r}): {g!r}, the scalar {want!r}")

    def test_every_function(self) -> None:
        for name, (vector, scalar, lo, hi) in CASES.items():
            xs = np.concatenate([np.array(SPECIALS), _inputs(30000, lo, hi)])
            if name == "log":
                xs = np.abs(xs)
            with self.subTest(name=name):
                self._check(vector, scalar, xs)

    def test_arctan2(self) -> None:
        sp = np.array(SPECIALS)
        yy, xx = np.meshgrid(sp, sp)
        ys = np.concatenate([yy.ravel(), _inputs(30000, -80, 80, 1)])
        xs = np.concatenate([xx.ravel(), _inputs(30000, -80, 80, 2)])
        got = fv.arctan2(ys, xs)
        for y, x, g in zip(ys.tolist(), xs.tolist(), got.tolist(), strict=True):
            self.assertTrue(_same(fs.atan2(y, x), g), (y, x))
        small = fv.arctan2(ys[:7], xs[:7])
        self.assertTrue(np.array_equal(small, got[:7], equal_nan=True))

    def test_sincos_shapes(self) -> None:
        x = _inputs(60, -10, 10).reshape(3, 4, 5)
        s, c = fv.sincos(x)
        self.assertEqual(s.shape, (3, 4, 5))
        self.assertTrue(np.array_equal(s, fv.sin(x)) and np.array_equal(c, fv.cos(x)))


class GoldenDigests(unittest.TestCase):
    """The outputs every machine must reproduce bit for bit (made on Linux x86-64 when the rule was written)."""

    GOLDEN: ClassVar[dict[str, str]] = {
        "sin": "79740143f5f7b2b0",
        "cos": "051c2d6d5af1a6e9",
        "tan": "c5daa97b91498b0f",
        "arctan": "f33973dadb97ef41",
        "arcsin": "c9bbd088c7638ccc",
        "arccos": "bbe378a06c33580c",
        "exp": "5759d0bd780673d0",
        "log": "df87048d0d9006a1",
        "cbrt": "86a1c07c9b8fb9bb",
        "arctan2": "5ebd578a4621818d",
        "hypot": "b836f71740c281a8",
        "dot": "7b603503f92c8236",
        "matmul": "19149feff4259fb3",
        "norm": "37032df40cd6ebef",
        "solve": "80c4d08dcbc1d5e4",
        "eigh": "d9439e6f128e786f",
        "real_roots": "0b0d21e414beb779",
        "sum": "7d6cc1fdc2eada4c",
    }

    @staticmethod
    def outputs() -> dict[str, str]:
        found = {}
        for name, (vector, _scalar, lo, hi) in CASES.items():
            xs = _inputs(50000, lo, hi, SEED + 7)
            if name == "log":
                xs = np.abs(xs)
            with np.errstate(all="ignore"):
                found[name] = _digest(vector(xs))
        a, b = _inputs(50000, -60, 60, 11), _inputs(50000, -60, 60, 12)
        found["arctan2"] = _digest(fv.arctan2(a, b))
        found["hypot"] = _digest(fv.hypot(a, b))
        p, q = (
            _inputs(30000, -20, 20, 13).reshape(-1, 3),
            _inputs(30000, -20, 20, 14).reshape(-1, 3),
        )
        found["dot"] = _digest(fv.dot(p, q))
        m = _inputs(9, -2, 2, 15).reshape(3, 3)
        found["matmul"] = _digest(
            fv.matmul(p, m),
            fv.matmul(m, m),
            fv.matmul(
                _inputs(40 * 12, -3, 3, 16).reshape(40, 12),
                _inputs(12 * 5, -3, 3, 17).reshape(12, 5),
            ),
        )
        found["norm"] = _digest(
            fv.norm(p, axis=1), np.array([fv.norm(p[0]), fv.norm(p.ravel())])
        )
        sq = _inputs(36, -2, 2, 18).reshape(6, 6) + 6.0 * np.eye(6)
        found["solve"] = _digest(
            fv.solve(sq, np.arange(6.0)),
            fv.solve(sq, np.eye(6)),
            np.array([fv.det(sq)]),
        )
        vals, vecs = fv.eigh(fv.matmul(sq, sq.T))
        found["eigh"] = _digest(vals, vecs)
        quartics = np.concatenate(
            [np.ones((2000, 1)), _inputs(8000, -4, 6, 19).reshape(2000, 4)], axis=1
        )
        found["real_roots"] = _digest(np.nan_to_num(fv.real_roots(quartics), nan=7.0))
        found["sum"] = _digest(
            np.array(
                [np.sum(_inputs(n, -30, 30, 20 + n)) for n in (3, 7, 8, 9, 100, 12345)]
            )
        )
        return found

    def test_every_digest_is_the_golden_one(self) -> None:
        found = self.outputs()
        for name, want in self.GOLDEN.items():
            with self.subTest(name=name):
                self.assertEqual(found[name], want)


class TheLinearAlgebraIsRight(unittest.TestCase):
    def test_against_numpy(self) -> None:
        rng = np.random.default_rng(3)
        for _ in range(50):
            a = rng.normal(size=(5, 5)) + 5 * np.eye(5)
            b = rng.normal(size=5)
            np.testing.assert_allclose(
                fv.solve(a, b), np.linalg.solve(a, b), rtol=1e-10, atol=1e-12
            )
            np.testing.assert_allclose(fv.det(a), np.linalg.det(a), rtol=1e-10)
            np.testing.assert_allclose(
                fv.inv(a), np.linalg.inv(a), rtol=1e-9, atol=1e-12
            )
            s = a @ a.T
            np.testing.assert_allclose(
                fv.eigh(s)[0], np.linalg.eigh(s)[0], rtol=1e-10, atol=1e-10
            )
            w, v = fv.eigh(s)
            np.testing.assert_allclose(s @ v, v * w, rtol=1e-8, atol=1e-8)
            p, q = rng.normal(size=(7, 3)), rng.normal(size=(3, 4))
            np.testing.assert_allclose(fv.matmul(p, q), p @ q, rtol=1e-12, atol=1e-14)
            np.testing.assert_allclose(
                fv.dot(p, p), np.einsum("ij,ij->i", p, p), rtol=1e-13
            )
            np.testing.assert_allclose(
                fv.norm(p, axis=1), np.linalg.norm(p, axis=1), rtol=1e-13
            )
            self.assertAlmostEqual(
                fv.norm(p[0]), float(np.linalg.norm(p[0])), places=12
            )
        with self.assertRaises(np.linalg.LinAlgError):
            fv.solve(np.zeros((3, 3)), np.ones(3))

    def test_real_roots_against_numpy(self) -> None:
        rng = np.random.default_rng(4)
        for _ in range(500):
            co = np.concatenate(
                [[1.0], rng.normal(size=4) * 10.0 ** rng.integers(-3, 3, 4)]
            )
            ours = fv.real_roots(co)[0]
            ours = ours[np.isfinite(ours)]
            ev = np.roots(co)
            real = np.sort(ev[np.abs(ev.imag) <= 1e-6 * (1 + np.abs(ev.real))].real)
            self.assertEqual(len(ours), len(real), co)
            np.testing.assert_allclose(ours, real, rtol=1e-9, atol=1e-9)
        double = fv.real_roots([1.0, -2.0, 1.0, 0.0, 0.0])[0]  # s^2 (s - 1)^2
        np.testing.assert_allclose(double, [0.0, 0.0, 1.0, 1.0], atol=1e-30)


class TheCompiledTwinIsNumPysBitForBit(unittest.TestCase):
    """The library in ``forge_numeric/_native`` (where this machine has one) against the NumPy twin."""

    def setUp(self) -> None:
        from forge_numeric import _native

        if _native.LIB is None:
            self.skipTest(f"no compiled twin here: {_native.WHY_NOT}")

    def _both(self, f, *args):
        native = f(*args)
        saved, fv._use = fv._use, None
        try:
            numpy = f(*args)
        finally:
            fv._use = saved
        return native, numpy

    def test_every_function(self) -> None:
        with np.errstate(all="ignore"):
            for name, (vector, _scalar, lo, hi) in CASES.items():
                xs = np.concatenate([np.array(SPECIALS), _inputs(100000, lo, hi, 41)])
                if name == "log":
                    xs = np.abs(xs)
                a, b = self._both(vector, xs)
                with self.subTest(name=name):
                    self.assertTrue(
                        np.array_equal(a.view(np.uint64), b.view(np.uint64))
                    )
            sp = np.array(SPECIALS)
            yy, xx = np.meshgrid(sp, sp)
            ys = np.concatenate([yy.ravel(), _inputs(100000, -80, 80, 42)])
            xs = np.concatenate([xx.ravel(), _inputs(100000, -80, 80, 43)])
            for f in (fv.arctan2, fv.hypot):
                a, b = self._both(f, ys, xs)
                with self.subTest(name=f.__name__):
                    self.assertTrue(
                        np.array_equal(a.view(np.uint64), b.view(np.uint64))
                    )
            big = np.ldexp(_inputs(2000, -1, 1, 44), np.int32(1000))
            for f in (fv.hypot,):
                a, b = self._both(f, big, big[::-1])
                self.assertTrue(np.array_equal(a.view(np.uint64), b.view(np.uint64)))
            huge = np.ldexp(
                _inputs(500, -1, 1, 45), np.int32(60)
            )  # sines reduced exactly in Python
            for f in (fv.sin, fv.cos):
                a, b = self._both(f, huge)
                self.assertTrue(np.array_equal(a.view(np.uint64), b.view(np.uint64)))

    def test_the_golden_digests_both_ways(self) -> None:
        native = GoldenDigests.outputs()
        saved, fv._use = fv._use, None
        try:
            numpy = GoldenDigests.outputs()
        finally:
            fv._use = saved
        self.assertEqual(native, numpy)

    def test_the_library_is_built_from_the_source_beside_it(self) -> None:
        from forge_numeric import _native

        if _native.SOURCE.exists():
            import ctypes

            digest = ctypes.create_string_buffer(16)
            _native.LIB.fnum_source(digest)
            self.assertEqual(
                digest.raw.decode("ascii"), _native.fnv1a(_native.SOURCE.read_bytes())
            )


if __name__ == "__main__":
    unittest.main()
